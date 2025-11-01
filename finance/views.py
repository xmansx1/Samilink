# finance/views.py
from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Tuple

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from agreements.models import Agreement, Milestone
from marketplace.models import Request
from .models import Invoice
from .permissions import is_finance

logger = logging.getLogger(__name__)

# ========= أدوات صلاحيات =========
def _is_finance(user) -> bool:
    """غلاف صغير لتوحيد الاستدعاء داخل هذا الملف."""
    return is_finance(user)

# ========= أدوات فترة زمنية =========
def _period_bounds(request) -> Tuple[date | None, date | None]:
    """
    يقرأ period من GET: today | 7d | 30d | custom (مع from/to).
    يرجّع (date_from, date_to) (شاملين).
    """
    p = (request.GET.get("period") or "").strip()
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

# ========= منطق حالة الطلب (مركزّي وآمن) =========
SAFE_PROGRESS_STATES = {"new", "offer_selected", "agreement_pending"}

def _touch_request_in_progress(req: Request) -> bool:
    """
    يدفع حالة الطلب إلى in_progress فقط إن كان ما يزال في الحالات المبكرة.
    لا يكمّل الطلب هنا إطلاقًا.
    يرجّع True إن حدث تحديث فعلاً.
    """
    try:
        cur = getattr(req, "status", None)
        if cur in SAFE_PROGRESS_STATES:
            req.status = getattr(Request.Status, "IN_PROGRESS", "in_progress")
            if hasattr(req, "updated_at"):
                req.updated_at = timezone.now()
                req.save(update_fields=["status", "updated_at"])
            else:
                req.save(update_fields=["status"])
            return True
        return False
    except Exception:
        logger.exception("فشل دفع الطلب إلى in_progress (req_id=%s)", getattr(req, "id", None))
        return False

def _can_complete_request(req: Request) -> bool:
    """
    لا نُكمل الطلب إذا كان في نزاع أو في حالة تمنع الإكمال.
    ابقِ المسار مفتوحًا للمنازعات (لا تحويل إلى مكتمل أثناء النزاع).
    """
    cur = getattr(req, "status", "") or ""
    DISPUTED = getattr(Request.Status, "DISPUTED", "disputed")
    CANCELLED = getattr(Request.Status, "CANCELLED", "cancelled")
    return cur not in {DISPUTED, CANCELLED}

def _complete_request_if_all_paid(agreement: Agreement) -> bool:
    """
    يكمّل الطلب إذا (وفقط إذا) جميع فواتير الاتفاقية مدفوعة.
    يرجع True إذا تم التغيير فعلاً.
    """
    try:
        inv_qs = getattr(agreement, "invoices", None)
        if not inv_qs:
            return False
        invoices = list(inv_qs.all())
        if not invoices:
            return False

        all_paid = all(getattr(inv, "status", None) == Invoice.Status.PAID or getattr(inv, "is_paid", False)
                       for inv in invoices)
        if not all_paid:
            return False

        req: Request | None = getattr(agreement, "request", None)
        if not req:
            return False

        if not _can_complete_request(req):
            # يوجد نزاع أو حالة تمنع الإكمال — لا نغيّر الحالة.
            return False

        if getattr(req, "status", "") == getattr(Request.Status, "COMPLETED", "completed"):
            return False

        update_fields: List[str] = ["status"]
        req.status = getattr(Request.Status, "COMPLETED", "completed")
        if hasattr(req, "completed_at"):
            req.completed_at = timezone.now()
            update_fields.append("completed_at")
        if hasattr(req, "updated_at"):
            req.updated_at = timezone.now()
            update_fields.append("updated_at")
        req.save(update_fields=update_fields)

        # (اختياري) تأشير الاتفاقية مكتملة إن كان لديها حقل status
        if hasattr(agreement, "status"):
            if getattr(agreement, "status") != "completed":
                agreement.status = "completed"
                if hasattr(agreement, "updated_at"):
                    agreement.updated_at = timezone.now()
                    agreement.save(update_fields=["status", "updated_at"])
                else:
                    agreement.save(update_fields=["status"])
        return True
    except Exception:
        logger.exception("فشل إكمال الطلب تلقائيًا عند سداد كل الفواتير (agreement_id=%s)", getattr(agreement, "id", None))
        return False

# ======= لوحة المالية =======
@login_required
@require_GET
def finance_home(request):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض لوحة المالية.")
        return redirect("website:home")

    inprog = Request.objects.filter(status=getattr(Request.Status, "IN_PROGRESS", "in_progress"))
    total_agreements_amount = (
        Agreement.objects.filter(request__in=inprog).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")
    )

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

# ======= قائمة الطلبات قيد التنفيذ =======
@login_required
@require_GET
def inprogress_requests(request):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض هذه الصفحة.")
        return redirect("website:home")

    qs = (
        Request.objects.filter(status=getattr(Request.Status, "IN_PROGRESS", "in_progress"))
        .select_related("client", "assigned_employee")
        .order_by("-updated_at", "-id")
    )
    total_reqs = qs.count()
    total_amount = Agreement.objects.filter(request__in=qs).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")
    unpaid_total = (
        Invoice.objects.filter(agreement__request__in=qs, status=Invoice.Status.UNPAID).aggregate(s=Sum("amount"))["s"]
        or Decimal("0.00")
    )

    return render(
        request,
        "finance/inprogress_list.html",
        {"requests": qs, "total_reqs": total_reqs, "total_amount": total_amount, "unpaid_total": unpaid_total},
    )

# ======= وسم فاتورة كمدفوعة (ذرّي + تحديث الحالات) =======
@login_required
@require_POST
@transaction.atomic
def mark_invoice_paid(request, pk: int):
    """
    وسم الفاتورة كمدفوعة بشكل ذرّي:
    - يتحقق من صلاحية المستخدم (مالية/Staff/Admin).
    - يحدّث حالة الفاتورة + paid_at/paid_ref إن لزم.
    - إن كانت الفاتورة مرتبطة بـ Milestone: يحدّث أعلام/حالة المرحلة إلى مدفوعة.
    - لا يُكمِّل الطلب إلا إذا **جميع** فواتير الاتفاقية مدفوعة (مع تجاهل الإكمال إن كان الطلب مُتنازعًا).
    """
    user = request.user
    if not (_is_finance(user) or getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        messages.error(request, "لا تملك صلاحية مالية لتنفيذ هذا الإجراء.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # قفل الصف منعًا لسباقات السداد
    inv = get_object_or_404(
        Invoice.objects.select_for_update().select_related("agreement", "milestone", "agreement__request"),
        pk=pk,
    )

    if getattr(inv, "status", None) == Invoice.Status.PAID or getattr(inv, "is_paid", False):
        messages.info(request, "الفاتورة مدفوعة مسبقًا.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    try:
        # 1) تحديث الفاتورة نفسها
        inv_updates: List[str] = []

        if hasattr(inv, "status"):
            inv.status = Invoice.Status.PAID
            inv_updates.append("status")
        # دعم نماذج تضع is_paid بدلاً من status
        if hasattr(inv, "is_paid"):
            inv.is_paid = True
            inv_updates.append("is_paid")

        paid_ref = (request.POST.get("paid_ref") or "").strip()
        if hasattr(inv, "paid_ref"):
            inv.paid_ref = (paid_ref[:64] if paid_ref else getattr(inv, "paid_ref", ""))
            inv_updates.append("paid_ref")

        if hasattr(inv, "paid_at") and not getattr(inv, "paid_at", None):
            inv.paid_at = timezone.now()
            inv_updates.append("paid_at")

        if hasattr(inv, "updated_at"):
            inv.updated_at = timezone.now()
            inv_updates.append("updated_at")

        if inv_updates:
            inv.save(update_fields=inv_updates)

        # 2) تحديث الـ Milestone المرتبط (إن وجد) — دعم الحالتين (status أو أعلام منطقية)
        ms: Milestone | None = getattr(inv, "milestone", None)
        if ms:
            ms_updates: List[str] = []

            # حالة نصية
            STATUS_PAID = getattr(getattr(ms, "Status", None), "PAID", "paid")
            if hasattr(ms, "status") and getattr(ms, "status") != STATUS_PAID:
                ms.status = STATUS_PAID
                ms_updates.append("status")

            # أعلام منطقية
            if hasattr(ms, "is_paid") and not getattr(ms, "is_paid", False):
                ms.is_paid = True  # type: ignore[attr-defined]
                ms_updates.append("is_paid")
            if hasattr(ms, "is_approved") and not getattr(ms, "is_approved", False):
                # أغلب النماذج تعتبر المرحلة مدفوعة بعد أن كانت معتمدة مسبقًا؛ لا نُجبر الاعتماد إن لم يكن.
                pass
            if hasattr(ms, "updated_at"):
                ms.updated_at = timezone.now()
                ms_updates.append("updated_at")
            if hasattr(ms, "paid_at"):
                ms.paid_at = getattr(inv, "paid_at", timezone.now())
                if "paid_at" not in ms_updates:
                    ms_updates.append("paid_at")

            if ms_updates:
                ms.save(update_fields=ms_updates)

        # 3) إكمال الطلب فقط لو تم سداد جميع الفواتير
        ag: Agreement | None = getattr(inv, "agreement", None)
        if ag:
            done = _complete_request_if_all_paid(ag)
            if done:
                messages.success(request, "تم سداد جميع الدفعات — اكتمل الطلب تلقائيًا.")
            else:
                messages.success(request, "تم وسم الفاتورة كمدفوعة.")
        else:
            messages.success(request, "تم وسم الفاتورة كمدفوعة.")

        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        logger.exception("فشل وسم الفاتورة كمدفوعة: %s", e)
        transaction.set_rollback(True)
        messages.error(request, "حدث خطأ غير متوقع أثناء تحديث الدفع. لم يتم حفظ أي تغييرات.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

# ======= تفاصيل فاتورة بسيطة (لروابط الإشعارات) =======
@login_required
def invoice_detail(request, pk: int):
    inv = get_object_or_404(
        Invoice.objects.select_related("agreement", "milestone", "agreement__request"),
        pk=pk,
    )
    # نمرّر المفتاحين inv و invoice للتوافق مع القوالب
    return render(request, "finance/invoice_detail.html", {"inv": inv, "invoice": inv})

# ======= فواتير اتفاقية معيّنة (توليد المفقود) =======
@login_required
@transaction.atomic
def agreement_invoices(request, agreement_id: int):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض هذه الصفحة.")
        return redirect("website:home")

    ag = get_object_or_404(
        Agreement.objects.select_related("request", "employee").prefetch_related("milestones", "invoices"),
        pk=agreement_id,
    )

    existing = set(ag.invoices.filter(milestone__isnull=False).values_list("milestone_id", flat=True))
    to_create: List[Invoice] = []
    for m in ag.milestones.all():
        if m.id not in existing:
            to_create.append(
                Invoice(
                    agreement=ag,
                    milestone=m,
                    amount=m.amount,
                    status=Invoice.Status.UNPAID if hasattr(Invoice, "Status") else getattr(Invoice, "status", "unpaid"),
                    # لو عندك created_by أو حقول إضافية ادعمها هنا بشروط hasattr
                )
            )
    if to_create:
        Invoice.objects.bulk_create(to_create)
        messages.info(request, f"تم توليد {len(to_create)} فاتورة جديدة بناءً على الدفعات.")

    invoices = ag.invoices.select_related("milestone").order_by("status", "issued_at", "id")
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

    status_q = request.GET.get("status") or ""  # unpaid/paid/all
    method_q = request.GET.get("method") or ""  # bank, cash, card, transfer...
    q = (request.GET.get("q") or "").strip()
    date_from = request.GET.get("from") or ""
    date_to = request.GET.get("to") or ""

    invs = (
        Invoice.objects.select_related("agreement", "agreement__request", "milestone")
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
            Q(agreement__request__id__icontains=q)
            | Q(agreement__id__icontains=q)
            | Q(ref_code__icontains=q)
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
        .exclude(method__isnull=True)
        .exclude(method__exact="")
        .values_list("method", flat=True)
        .distinct()
        .order_by("method")
    )

    return render(
        request,
        "finance/client_payments.html",
        {
            "invoices": invs,
            "totals": totals,
            "status_q": status_q,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "method_q": method_q,
            "methods": methods,
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
        Invoice.objects.select_related("agreement", "agreement__request", "milestone")
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
            Q(agreement__request__id__icontains=q)
            | Q(agreement__id__icontains=q)
            | Q(ref_code__icontains=q)
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
        .exclude(method__isnull=True)
        .exclude(method__exact="")
        .values_list("method", flat=True)
        .distinct()
        .order_by("method")
    )

    return render(
        request,
        "finance/employee_dues.html",
        {
            "invoices": invs,
            "totals": totals,
            "status_q": status_q,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "method_q": method_q,
            "methods": methods,
        },
    )

# ======= تقرير التحصيل (مالية) + تجميع =======
@login_required
@require_GET
def collections_report(request):
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بعرض هذا التقرير.")
        return redirect("website:home")

    status_q = request.GET.get("status") or ""  # unpaid/paid/all
    method_q = request.GET.get("method") or ""
    q = (request.GET.get("q") or "").strip()

    d1, d2 = _period_bounds(request)
    invs = Invoice.objects.select_related("agreement", "agreement__request", "milestone").all()

    # نطاق زمني يعتمد paid_at إن كانت مدفوعة، وإلا issued_at
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
            Q(agreement__request__id__icontains=q)
            | Q(agreement__id__icontains=q)
            | Q(ref_code__icontains=q)
        )

    invs = invs.order_by("-paid_at", "-issued_at", "-id")

    totals = invs.aggregate(
        total=Sum("amount"),
        unpaid=Sum("amount", filter=Q(status=Invoice.Status.UNPAID)),
        paid=Sum("amount", filter=Q(status=Invoice.Status.PAID)),
    )
    methods = (
        Invoice.objects.exclude(method__isnull=True)
        .exclude(method__exact="")
        .values_list("method", flat=True)
        .distinct()
        .order_by("method")
    )

    by_method = invs.values("method").annotate(cnt=Count("id"), amt=Sum("amount")).order_by("method")

    return render(
        request,
        "finance/collections_report.html",
        {
            "invoices": invs,
            "totals": totals,
            "methods": methods,
            "status_q": status_q,
            "method_q": method_q,
            "q": q,
            "period": (request.GET.get("period") or ""),
            "from": request.GET.get("from") or "",
            "to": request.GET.get("to") or "",
            "d1": d1,
            "d2": d2,
            "by_method": by_method,
        },
    )

# ======= تصدير CSV لنفس مرشحات التقرير =======
@login_required
@require_GET
def export_invoices_csv(request):
    """تصدير الفواتير حسب نفس مرشحات تقرير التحصيل (للمالية فقط)."""
    if not _is_finance(request.user):
        messages.error(request, "غير مصرح بالتصدير.")
        return redirect("website:home")

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
            Q(agreement__request__id__icontains=q)
            | Q(agreement__id__icontains=q)
            | Q(ref_code__icontains=q)
        )
    invs = invs.order_by("-paid_at", "-issued_at", "-id")

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="invoices_export.csv"'
    writer = csv.writer(resp)
    writer.writerow(
        ["InvoiceID", "AgreementID", "RequestID", "Milestone", "Amount", "Status", "IssuedAt", "PaidAt", "Method", "RefCode"]
    )
    for inv in invs:
        writer.writerow(
            [
                inv.id,
                inv.agreement_id,
                getattr(getattr(inv, "agreement", None), "request_id", ""),
                getattr(getattr(inv, "milestone", None), "title", "") if getattr(inv, "milestone_id", None) else "",
                f"{inv.amount}",
                inv.get_status_display() if hasattr(inv, "get_status_display") else getattr(inv, "status", ""),
                inv.issued_at.strftime("%Y-%m-%d %H:%M") if getattr(inv, "issued_at", None) else "",
                inv.paid_at.strftime("%Y-%m-%d %H:%M") if getattr(inv, "paid_at", None) else "",
                getattr(inv, "method", "") or "",
                getattr(inv, "ref_code", "") or "",
            ]
        )
    return resp
