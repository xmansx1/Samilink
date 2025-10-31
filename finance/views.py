# finance/views.py
from __future__ import annotations
from decimal import Decimal
from datetime import date, timedelta
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q, Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from agreements.models import Agreement
from marketplace.models import Request
from .models import Invoice

# ========= صلاحيات =========
def _is_finance(user) -> bool:
    role = getattr(user, "role", "")
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False) or role == "finance")


# ========= أدوات فترة زمنية =========
def _period_bounds(request):
    """
    يقرأ period من GET: today | 7d | 30d | custom (مع from/to).
    يرجّع (date_from, date_to) (شاملين).
    """
    p = (request.GET.get("period") or "").strip()  # today/7d/30d/custom
    today = date.today()
    if p == "today":
        return today, today
    if p == "7d":
        return today - timedelta(days=6), today
    if p == "30d":
        return today - timedelta(days=29), today
    if p == "custom":
        df = request.GET.get("from") or ""
        dt = request.GET.get("to") or ""
        try:
            d1 = date.fromisoformat(df) if df else None
            d2 = date.fromisoformat(dt) if dt else None
        except ValueError:
            d1 = d2 = None
        return d1, d2
    # افتراضي: آخر 30 يوم
    return today - timedelta(days=29), today


# ======= لوحة المالية (كما هي) =======
@login_required
@require_GET
def finance_home(request):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض لوحة المالية.")
        return redirect("website:home")

    inprog = Request.objects.filter(status=getattr(Request.Status, "IN_PROGRESS"))
    total_agreements_amount = Agreement.objects.filter(request__in=inprog).aggregate(
        s=Sum("total_amount")
    )["s"] or Decimal("0.00")

    unpaid_sum = Invoice.objects.filter(status=Invoice.Status.UNPAID).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    paid_sum = Invoice.objects.filter(status=Invoice.Status.PAID).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

    return render(
        request,
        "finance/home.html",
        {
            "inprogress_count": inprog.count(),
            "total_agreements_amount": total_agreements_amount,
            "unpaid_sum": unpaid_sum,
            "paid_sum": paid_sum,
        },
    )


# ======= قائمة التنفيذ (كما هي) =======
@login_required
@require_GET
def inprogress_requests(request):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض هذه الصفحة.")
        return redirect("website:home")

    qs = (
        Request.objects.filter(status=getattr(Request.Status, "IN_PROGRESS"))
        .select_related("client", "assigned_employee", "agreement")
        .order_by("-updated_at", "-id")
    )
    total_reqs = qs.count()
    total_amount = Agreement.objects.filter(request__in=qs).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")
    unpaid_total = Invoice.objects.filter(agreement__request__in=qs, status=Invoice.Status.UNPAID).aggregate(
        s=Sum("amount")
    )["s"] or Decimal("0.00")

    return render(
        request,
        "finance/inprogress_list.html",
        {"requests": qs, "total_reqs": total_reqs, "total_amount": total_amount, "unpaid_total": unpaid_total},
    )


# ======= فواتير الاتفاقية (كما هي + تنبيه اختياري) =======
@login_required
@require_POST
def mark_invoice_paid(request, pk: int):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بهذا الإجراء.")
        return redirect("website:home")

    inv = get_object_or_404(Invoice.objects.select_related("agreement", "milestone", "agreement__request"), pk=pk)
    if inv.status != Invoice.Status.UNPAID:
        messages.warning(request, "هذه الفاتورة ليست غير مدفوعة.")
        return redirect("finance:agreement_invoices", agreement_id=inv.agreement_id)

    inv.status = Invoice.Status.PAID
    inv.paid_at = timezone.now()
    inv.method = (request.POST.get("method") or "").strip()[:50]
    inv.ref_code = (request.POST.get("ref_code") or "").strip()[:100]
    inv.save(update_fields=["status", "paid_at", "method", "ref_code", "updated_at"])

    # تنبيه اختياري: إذا لديك نظام إشعارات
    try:
        from core.notifications.utils import notify_user  # افتراضي: utils.notify_user(u, title, body)
        client = getattr(inv.agreement.request, "client", None)
        if client:
            notify_user(client, "تم تسجيل سداد فاتورة", f"تم تسجيل سداد فاتورة #{inv.id} بمبلغ {inv.amount} ر.س.")
    except Exception:
        pass

    messages.success(request, "تم وسم الفاتورة كمدفوعة.")
    return redirect("finance:agreement_invoices", agreement_id=inv.agreement_id)


@login_required
def agreement_invoices(request, agreement_id: int):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض هذه الصفحة.")
        return redirect("website:home")

    ag = get_object_or_404(
        Agreement.objects.select_related("request", "employee").prefetch_related("milestones", "invoices"),
        pk=agreement_id,
    )

    existing = set(ag.invoices.filter(milestone__isnull=False).values_list("milestone_id", flat=True))
    to_create = []
    for m in ag.milestones.all():
        if m.id not in existing:
            to_create.append(
                Invoice(agreement=ag, milestone=m, amount=m.amount, status=Invoice.Status.UNPAID, created_by=request.user)
            )
    if to_create:
        Invoice.objects.bulk_create(to_create)
        messages.info(request, f"تم توليد {len(to_create)} فاتورة جديدة بناءً على الدفعات.")

    invoices = ag.invoices.select_related("milestone").order_by("status", "issued_at")
    totals = invoices.aggregate(
        total=Sum("amount"),
        unpaid=Sum("amount", filter=Q(status=Invoice.Status.UNPAID)),
        paid=Sum("amount", filter=Q(status=Invoice.Status.PAID)),
    )
    return render(request, "finance/invoice_list.html", {"agreement": ag, "invoices": invoices, "totals": totals})


# ======= مدفوعاتي (عميل) — + فلتر طريقة السداد =======
@login_required
@require_GET
def client_payments(request):
    user = request.user
    role = getattr(user, "role", "")
    if role != "client" and not _is_finance(user):
        messages.error(request, "هذه الصفحة مخصّصة للعميل.")
        return redirect("website:home")

    status_q = request.GET.get("status") or ""    # unpaid/paid/all
    method_q = request.GET.get("method") or ""    # bank, cash, card, transfer...
    q = (request.GET.get("q") or "").strip()
    date_from = request.GET.get("from") or ""
    date_to = request.GET.get("to") or ""

    invs = (
        Invoice.objects
        .select_related("agreement", "agreement__request", "milestone")
        .filter(agreement__request__client_id=user.id)
        .order_by("-issued_at", "-id")
    )
    if status_q == "unpaid":
        invs = invs.filter(status=Invoice.Status.UNPAID)
    elif status_q == "paid":
        invs = invs.filter(status=Invoice.Status.PAID)

    if method_q:
        invs = invs.filter(method__iexact=method_q)

    if q:
        invs = invs.filter(
            Q(agreement__request__id__icontains=q) |
            Q(agreement__id__icontains=q) |
            Q(ref_code__icontains=q)
        )
    if date_from:
        invs = invs.filter(issued_at__date__gte=date_from)
    if date_to:
        invs = invs.filter(issued_at__date__lte=date_to)

    totals = invs.aggregate(
        total=Sum("amount"),
        unpaid=Sum("amount", filter=Q(status=Invoice.Status.UNPAID)),
        paid=Sum("amount", filter=Q(status=Invoice.Status.PAID)),
    )
    methods = (
        Invoice.objects.filter(agreement__request__client_id=user.id)
        .exclude(method__isnull=True).exclude(method__exact="")
        .values_list("method", flat=True).distinct().order_by("method")
    )

    return render(
        request,
        "finance/client_payments.html",
        {
            "invoices": invs, "totals": totals, "status_q": status_q, "q": q,
            "date_from": date_from, "date_to": date_to, "method_q": method_q, "methods": methods,
        },
    )


# ======= مستحقاتي (موظف) — + فلتر طريقة السداد =======
@login_required
@require_GET
def employee_dues(request):
    user = request.user
    role = getattr(user, "role", "")
    if role != "employee" and not _is_finance(user):
        messages.error(request, "هذه الصفحة مخصّصة للموظف.")
        return redirect("website:home")

    status_q = request.GET.get("status") or ""
    method_q = request.GET.get("method") or ""
    q = (request.GET.get("q") or "").strip()
    date_from = request.GET.get("from") or ""
    date_to = request.GET.get("to") or ""

    invs = (
        Invoice.objects
        .select_related("agreement", "agreement__request", "milestone")
        .filter(agreement__employee_id=user.id)
        .order_by("-issued_at", "-id")
    )
    if status_q == "unpaid":
        invs = invs.filter(status=Invoice.Status.UNPAID)
    elif status_q == "paid":
        invs = invs.filter(status=Invoice.Status.PAID)

    if method_q:
        invs = invs.filter(method__iexact=method_q)

    if q:
        invs = invs.filter(
            Q(agreement__request__id__icontains=q) |
            Q(agreement__id__icontains=q) |
            Q(ref_code__icontains=q)
        )
    if date_from:
        invs = invs.filter(issued_at__date__gte=date_from)
    if date_to:
        invs = invs.filter(issued_at__date__lte=date_to)

    totals = invs.aggregate(
        total=Sum("amount"),
        unpaid=Sum("amount", filter=Q(status=Invoice.Status.UNPAID)),
        paid=Sum("amount", filter=Q(status=Invoice.Status.PAID)),
    )
    methods = (
        Invoice.objects.filter(agreement__employee_id=user.id)
        .exclude(method__isnull=True).exclude(method__exact="")
        .values_list("method", flat=True).distinct().order_by("method")
    )

    return render(
        request,
        "finance/employee_dues.html",
        {
            "invoices": invs, "totals": totals, "status_q": status_q, "q": q,
            "date_from": date_from, "date_to": date_to, "method_q": method_q, "methods": methods,
        },
    )


# ======= تقرير التحصيل (مالية) + تصدير =======
@login_required
@require_GET
def collections_report(request):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض هذا التقرير.")
        return redirect("website:home")

    status_q = request.GET.get("status") or ""  # unpaid/paid/all
    method_q = request.GET.get("method") or ""
    q = (request.GET.get("q") or "").strip()

    d1, d2 = _period_bounds(request)  # تواريخ
    invs = Invoice.objects.select_related("agreement", "agreement__request", "milestone").all()

    # نطاق زمني يعتمد على paid_at إذا كانت Paid، وإلا issued_at
    if d1:
        invs = invs.filter(Q(paid_at__date__gte=d1) | Q(paid_at__isnull=True, issued_at__date__gte=d1))
    if d2:
        invs = invs.filter(Q(paid_at__date__lte=d2) | Q(paid_at__isnull=True, issued_at__date__lte=d2))

    if status_q == "unpaid":
        invs = invs.filter(status=Invoice.Status.UNPAID)
    elif status_q == "paid":
        invs = invs.filter(status=Invoice.Status.PAID)

    if method_q:
        invs = invs.filter(method__iexact=method_q)

    if q:
        invs = invs.filter(
            Q(agreement__request__id__icontains=q) |
            Q(agreement__id__icontains=q) |
            Q(ref_code__icontains=q)
        )

    invs = invs.order_by("-paid_at", "-issued_at", "-id")

    totals = invs.aggregate(
        total=Sum("amount"),
        unpaid=Sum("amount", filter=Q(status=Invoice.Status.UNPAID)),
        paid=Sum("amount", filter=Q(status=Invoice.Status.PAID)),
    )
    methods = (
        Invoice.objects.exclude(method__isnull=True).exclude(method__exact="")
        .values_list("method", flat=True).distinct().order_by("method")
    )

    # تجميع سريع لطُرق السداد (للبطاقات)
    by_method = invs.values("method").annotate(cnt=Count("id"), amt=Sum("amount")).order_by("method")

    return render(
        request,
        "finance/collections_report.html",
        {
            "invoices": invs, "totals": totals, "methods": methods,
            "status_q": status_q, "method_q": method_q, "q": q,
            "period": (request.GET.get("period") or ""), "from": request.GET.get("from") or "", "to": request.GET.get("to") or "",
            "d1": d1, "d2": d2, "by_method": by_method,
        },
    )


@login_required
@require_GET
def export_invoices_csv(request):
    """تصدير الفواتير حسب نفس مرشحات تقرير التحصيل (للمالية فقط)."""
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بالتصدير.")
        return redirect("website:home")

    # استخدم نفس لوجيك فلترة collections_report
    status_q = request.GET.get("status") or ""
    method_q = request.GET.get("method") or ""
    q = (request.GET.get("q") or "").strip()
    d1, d2 = _period_bounds(request)

    invs = Invoice.objects.select_related("agreement", "agreement__request", "milestone").all()
    if d1:
        invs = invs.filter(Q(paid_at__date__gte=d1) | Q(paid_at__isnull=True, issued_at__date__gte=d1))
    if d2:
        invs = invs.filter(Q(paid_at__date__lte=d2) | Q(paid_at__isnull=True, issued_at__date__lte=d2))
    if status_q == "unpaid":
        invs = invs.filter(status=Invoice.Status.UNPAID)
    elif status_q == "paid":
        invs = invs.filter(status=Invoice.Status.PAID)
    if method_q:
        invs = invs.filter(method__iexact=method_q)
    if q:
        invs = invs.filter(
            Q(agreement__request__id__icontains=q) |
            Q(agreement__id__icontains=q) |
            Q(ref_code__icontains=q)
        )
    invs = invs.order_by("-paid_at", "-issued_at", "-id")

    # إعداد CSV
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="invoices_export.csv"'
    writer = csv.writer(resp)
    writer.writerow(["InvoiceID", "AgreementID", "RequestID", "Milestone", "Amount", "Status", "IssuedAt", "PaidAt", "Method", "RefCode"])
    for inv in invs:
        writer.writerow([
            inv.id,
            inv.agreement_id,
            getattr(inv.agreement.request, "id", ""),
            getattr(inv.milestone, "title", "") if inv.milestone_id else "",
            f"{inv.amount}",
            inv.get_status_display(),
            inv.issued_at.strftime("%Y-%m-%d %H:%M") if inv.issued_at else "",
            inv.paid_at.strftime("%Y-%m-%d %H:%M") if inv.paid_at else "",
            inv.method or "",
            inv.ref_code or "",
        ])
    return resp
