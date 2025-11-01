# agreements/views.py
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.forms.formsets import BaseFormSet
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from datetime import timedelta

from marketplace.models import Request, Offer
from finance.models import Invoice
from .forms import AgreementEditForm, MilestoneFormSet, AgreementClauseSelectForm
from .models import Agreement, AgreementClauseItem, Milestone

logger = logging.getLogger(__name__)

# =========================
# Helpers (صلاحيات/حقول/حالات)
# =========================

def _is_admin(user) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or getattr(user, "role", "") == "admin"
    )

def _is_emp_or_admin(user) -> bool:
    return bool(_is_admin(user) or getattr(user, "role", "") == "employee")

def _get_selected_offer(req: Request) -> Offer | None:
    off = getattr(req, "selected_offer", None)
    if off:
        return off
    return req.offers.filter(status=Offer.Status.SELECTED).select_related("employee").first()

def _has_db_field(instance, field_name: str) -> bool:
    try:
        instance._meta.get_field(field_name)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False

def _set_db_field(instance, field_name: str, value, update_fields: list[str]) -> None:
    """
    يضبط القيمة إذا كان حقل قاعدة بيانات فعلي (وليس @property).
    يضيف الاسم إلى update_fields تلقائيًا.
    """
    # لو وُجد @property بنفس الاسم نتجنب الكتابة
    if hasattr(type(instance), field_name) and isinstance(getattr(type(instance), field_name), property):
        return
    try:
        instance._meta.get_field(field_name)  # raises FieldDoesNotExist إن لم يوجد
    except Exception:
        return
    setattr(instance, field_name, value)
    update_fields.append(field_name)

def _assign_auto_order(formset: BaseFormSet) -> None:
    idx = 1
    for form in formset.forms:
        cd = getattr(form, "cleaned_data", {}) or {}
        if cd.get("DELETE"):
            continue
        if hasattr(form, "instance") and form.instance:
            form.instance.order = idx
        cd["order"] = idx
        idx += 1

def _sum_milestones(formset: BaseFormSet) -> Decimal:
    total = Decimal("0.00")
    for form in formset.forms:
        cd = getattr(form, "cleaned_data", {}) or {}
        if not cd or cd.get("DELETE"):
            continue
        amt = cd.get("amount")
        if amt is not None:
            total += Decimal(amt)
    return total

def _lock_core_fields_if_needed(ag: Agreement, form: AgreementEditForm) -> None:
    """
    احترازيًا: إن كانت الاتفاقية موجودة، لا نسمح بتغيير المدة والإجمالي من POST.
    تبقى كما في قاعدة البيانات (قفل خادمي).
    """
    if ag.pk and hasattr(form, "cleaned_data"):
        form.cleaned_data["duration_days"] = ag.duration_days
        form.cleaned_data["total_amount"] = ag.total_amount

def _update_request_status_on_send(req: Request) -> None:
    """
    عند إرسال الاتفاقية للعميل → AGREEMENT_PENDING (إن وُجدت)،
    وإلا لا تغيّر شيئًا.
    """
    new_status = getattr(Request.Status, "AGREEMENT_PENDING", "agreement_pending")
    if hasattr(Request.Status, "AGREEMENT_PENDING"):
        req.status = new_status
        if _has_db_field(req, "updated_at"):
            req.updated_at = timezone.now()
            req.save(update_fields=["status", "updated_at"])
        else:
            req.save(update_fields=["status"])

def _move_request_on_accept(req: Request) -> None:
    """
    عند موافقة العميل على الاتفاقية → IN_PROGRESS.
    لا نُكمل الطلب هنا إطلاقًا.
    """
    in_progress = getattr(Request.Status, "IN_PROGRESS", "in_progress")
    req.status = in_progress
    updates = ["status"]
    if _has_db_field(req, "updated_at"):
        req.updated_at = timezone.now()
        updates.append("updated_at")
    req.save(update_fields=updates)

def _touch_request_in_progress(req: Request) -> None:
    """
    إن كان الطلب في حالات مبكرة (new/offer_selected/agreement_pending) نحوله إلى in_progress.
    إذا كان متقدمًا بالفعل لا نغيّر.
    """
    early = {getattr(Request.Status, "NEW", "new"),
             getattr(Request.Status, "OFFER_SELECTED", "offer_selected"),
             getattr(Request.Status, "AGREEMENT_PENDING", "agreement_pending")}
    if getattr(req, "status", None) in early:
        _move_request_on_accept(req)

def _return_request_to_offer_selected(req: Request) -> None:
    """
    عند رفض الاتفاقية تعود حالة الطلب إلى OFFER_SELECTED (إن وُجدت).
    """
    if hasattr(Request.Status, "OFFER_SELECTED"):
        req.status = Request.Status.OFFER_SELECTED
        updates = ["status"]
        if _has_db_field(req, "updated_at"):
            req.updated_at = timezone.now()
            updates.append("updated_at")
        req.save(update_fields=updates)

def _redirect_to_request_detail(ms: Milestone) -> HttpResponse:
    """إعادة توجيه آمنة لصفحة الطلب مع مرساة المرحلة."""
    req = getattr(getattr(ms, "agreement", None), "request", None)
    if not req:
        return redirect("/")
    try:
        url = req.get_absolute_url()
    except Exception:
        url = reverse("marketplace:request_detail", args=[req.id])
    return redirect(f"{url}#ms-{ms.id}")

# =========================
# Agreement: فتح/تفاصيل/تحرير/قبول/رفض/بنود
# =========================

@login_required
def open_by_request(request: HttpRequest, request_id: int) -> HttpResponse:
    """
    يفتح/ينشئ اتفاقية لطلب محدد:
    - إن وُجدت اتفاقية: إعادة توجيه لتفاصيلها.
    - إن لم توجد: إنشاء مسودة من العرض المختار ثم التحويل للتحرير.
    الصلاحية: الموظف المسند أو الأدمن/الستاف.
    """
    req = get_object_or_404(
        Request.objects.select_related("assigned_employee", "client"),
        pk=request_id,
    )

    ag = getattr(req, "agreement", None)
    if ag:
        messages.info(request, "تم فتح الاتفاقية الموجودة.")
        return redirect("agreements:detail", pk=ag.pk)

    if not _is_emp_or_admin(request.user):
        messages.error(request, "غير مصرح بإنشاء اتفاقية لهذا الطلب.")
        return redirect("marketplace:request_detail", pk=req.pk)

    selected = _get_selected_offer(req)
    if not selected:
        messages.error(request, "لا يمكن إنشاء اتفاقية بدون وجود عرض مختار.")
        return redirect("marketplace:request_detail", pk=req.pk)

    ag = Agreement.objects.create(
        request=req,
        employee=(getattr(req, "assigned_employee", None) or selected.employee or request.user),
        title=req.title or f"اتفاقية طلب #{req.pk}",
        duration_days=selected.proposed_duration_days or 7,
        total_amount=selected.proposed_price or Decimal("0.00"),
        status=Agreement.Status.DRAFT,
    )

    messages.success(request, "تم إنشاء مسودة الاتفاقية. يمكنك تحريرها وإرسالها للعميل.")
    return redirect("agreements:edit", pk=ag.pk)

@login_required
def detail(request: HttpRequest, pk: int) -> HttpResponse:
    """تفاصيل الاتفاقية (للأطراف المخوّلة فقط)."""
    ag = get_object_or_404(
        Agreement.objects.select_related("request", "employee", "request__client")
        .prefetch_related("clause_items__clause", "milestones"),
        pk=pk,
    )
    req = ag.request
    user = request.user

    allowed = (
        user.id == req.client_id
        or user.id == getattr(req, "assigned_employee_id", None)
        or user.id == ag.employee_id
        or _is_admin(user)
    )
    if not allowed:
        messages.error(request, "غير مصرح بعرض هذه الاتفاقية.")
        return redirect("marketplace:request_detail", pk=req.pk)

    ctx = {"agreement": ag, "req": req, "rejection_reason": ag.rejection_reason}
    return render(request, "agreements/agreement_detail.html", ctx)

@login_required
def edit(request: HttpRequest, pk: int) -> HttpResponse:
    """
    تحرير الاتفاقية (staff/employee):
    - حفظ كمسودة
    - حفظ + إرسال للعميل (يتحقق من مساواة مجموع الدفعات للإجمالي)
    """
    ag = get_object_or_404(
        Agreement.objects.select_related("request", "employee"),
        pk=pk,
    )
    req = ag.request

    if not _is_emp_or_admin(request.user):
        messages.error(request, "غير مصرح بتحرير الاتفاقية.")
        return redirect("agreements:detail", pk=ag.pk)

    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip()  # save | send
        form = AgreementEditForm(request.POST, instance=ag)
        formset: BaseFormSet = MilestoneFormSet(request.POST, instance=ag)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                _lock_core_fields_if_needed(ag, form)
                ag = form.save()
                _assign_auto_order(formset)
                formset.save()

                if action == "send":
                    total_m = _sum_milestones(formset).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    total_ag = (ag.total_amount or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if total_m != total_ag:
                        messages.error(request, f"مجموع الدفعات ({total_m}) لا يساوي الإجمالي ({total_ag}).")
                        return render(
                            request,
                            "agreements/agreement_form.html",
                            {"agreement": ag, "req": req, "form": form, "formset": formset},
                        )
                    ag.status = Agreement.Status.PENDING
                    updates = ["status"]
                    if _has_db_field(ag, "updated_at"):
                        ag.updated_at = timezone.now()
                        updates.append("updated_at")
                    ag.save(update_fields=updates)

                    _update_request_status_on_send(req)
                    messages.success(request, "تم حفظ الاتفاقية وإرسالها للعميل.")
                    return redirect("agreements:detail", pk=ag.pk)

                # حفظ كمسودة
                ag.status = Agreement.Status.DRAFT
                updates = ["status"]
                if _has_db_field(ag, "updated_at"):
                    ag.updated_at = timezone.now()
                    updates.append("updated_at")
                ag.save(update_fields=updates)
                messages.success(request, "تم حفظ التعديلات (مسودة).")
                return redirect("agreements:edit", pk=ag.pk)

        messages.error(request, "لم يتم الحفظ. الرجاء تصحيح الأخطاء.")
        return render(
            request,
            "agreements/agreement_form.html",
            {"agreement": ag, "req": req, "form": form, "formset": formset},
        )

    # GET
    form = AgreementEditForm(instance=ag)
    formset: BaseFormSet = MilestoneFormSet(instance=ag)
    return render(
        request,
        "agreements/agreement_form.html",
        {"agreement": ag, "req": req, "form": form, "formset": formset},
    )

@login_required
def accept_by_request(request: HttpRequest, request_id: int) -> HttpResponse:
    """موافقة العميل على الاتفاقية → يحوّل الطلب إلى in_progress فقط."""
    req = get_object_or_404(Request.objects.select_related("client"), pk=request_id)
    ag = getattr(req, "agreement", None)
    if not ag:
        messages.error(request, "لا توجد اتفاقية لهذا الطلب.")
        return redirect("marketplace:request_detail", pk=req.pk)

    if request.user.id != req.client_id and not _is_admin(request.user):
        messages.error(request, "غير مصرح بالموافقة على هذه الاتفاقية.")
        return redirect("agreements:detail", pk=ag.pk)

    if ag.status == Agreement.Status.ACCEPTED:
        messages.info(request, "الاتفاقية مقبولة مسبقًا.")
        return redirect("agreements:detail", pk=ag.pk)

    ag.status = Agreement.Status.ACCEPTED
    updates = ["status"]
    if _has_db_field(ag, "updated_at"):
        ag.updated_at = timezone.now()
        updates.append("updated_at")
    ag.save(update_fields=updates)

    _move_request_on_accept(req)
    messages.success(request, "تمت الموافقة على الاتفاقية. تم تحويل الطلب إلى قيد التنفيذ.")
    return redirect("agreements:detail", pk=ag.pk)

@login_required
def reject_by_request(request: HttpRequest, request_id: int) -> HttpResponse:
    """صفحة إدخال سبب رفض الاتفاقية (للعميل)."""
    req = get_object_or_404(Request.objects.select_related("client"), pk=request_id)
    ag = getattr(req, "agreement", None)
    if not ag:
        messages.error(request, "لا توجد اتفاقية لهذا الطلب.")
        return redirect("marketplace:request_detail", pk=req.pk)

    if request.user.id != req.client_id and not _is_admin(request.user):
        messages.error(request, "غير مصرح برفض هذه الاتفاقية.")
        return redirect("agreements:detail", pk=ag.pk)

    return render(request, "agreements/agreement_reject.html", {"agreement": ag, "req": req})

@login_required
@require_POST
def reject(request: HttpRequest, pk: int) -> HttpResponse:
    """حفظ سبب رفض الاتفاقية → يرجع الطلب إلى مرحلة العروض."""
    ag = get_object_or_404(Agreement.objects.select_related("request"), pk=pk)
    req = ag.request

    if request.user.id != req.client_id and not _is_admin(request.user):
        messages.error(request, "غير مصرح برفض هذه الاتفاقية.")
        return redirect("agreements:detail", pk=ag.pk)

    reason = (request.POST.get("reason") or "").strip()
    if len(reason) < 5:
        messages.error(request, "الرجاء توضيح سبب الرفض (5 أحرف على الأقل).")
        return render(request, "agreements/agreement_reject.html", {"agreement": ag, "req": req})

    updates = ["rejection_reason", "status"]
    ag.rejection_reason = reason[:1000]
    ag.status = Agreement.Status.REJECTED
    if _has_db_field(ag, "updated_at"):
        ag.updated_at = timezone.now()
        updates.append("updated_at")
    ag.save(update_fields=updates)

    _return_request_to_offer_selected(req)
    messages.success(request, "تم رفض الاتفاقية وإعادتها إلى مرحلة العروض.")
    return redirect("agreements:detail", pk=ag.pk)

@login_required
@transaction.atomic
def finalize_clauses(request: HttpRequest, pk: int) -> HttpResponse:
    """
    تثبيت/تعديل بنود الاتفاقية (staff/employee المالك).
    """
    agreement = get_object_or_404(Agreement.objects.select_related("employee", "request"), pk=pk)
    user = request.user
    is_owner_emp = (user.id == agreement.employee_id)

    if not (_is_admin(user) or is_owner_emp):
        messages.error(request, "غير مصرح لك بتعديل بنود هذه الاتفاقية.")
        return redirect("agreements:detail", pk=agreement.pk)

    if request.method == "POST":
        form = AgreementClauseSelectForm(request.POST)
        if form.is_valid():
            AgreementClauseItem.objects.filter(agreement=agreement).delete()
            pos = 1

            for clause in form.cleaned_data.get("clauses", []):
                AgreementClauseItem.objects.create(agreement=agreement, clause=clause, position=pos)
                pos += 1

            for line in form.cleaned_custom_lines():
                AgreementClauseItem.objects.create(agreement=agreement, custom_text=line, position=pos)
                pos += 1

            messages.success(request, "تم حفظ بنود الاتفاقية بنجاح.")
            return redirect("agreements:detail", pk=agreement.pk)
        else:
            messages.error(request, "الرجاء تصحيح الأخطاء في نموذج البنود.")
    else:
        form = AgreementClauseSelectForm()

    return render(request, "agreements/finalize_clauses.html", {"agreement": agreement, "form": form})

# =========================
# Milestones: تسليم/اعتماد/رفض
# =========================

@login_required
@transaction.atomic
def milestone_deliver(request: HttpRequest, milestone_id: int, *args, **kwargs) -> HttpResponse:
    """
    تسليم/إعادة تسليم المرحلة من الموظف المُسنَد (أو staff/admin).
    - يمنع التسليم بعد الاعتماد أو السداد.
    - يفتح المراجعة ويصفر أي رفض سابق.
    - يضمن بقاء الطلب “قيد التنفيذ” فقط (لا إكمال هنا).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ms = get_object_or_404(Milestone.objects.select_related("agreement__request"), pk=milestone_id)
    req = ms.agreement.request

    is_admin = _is_admin(request.user)
    is_assigned_employee = request.user.id == getattr(req, "assigned_employee_id", None)
    if not (is_admin or is_assigned_employee):
        messages.error(request, "ليست لديك صلاحية لتسليم هذه المرحلة.")
        return _redirect_to_request_detail(ms)

    if bool(getattr(ms, "is_approved", False)) or bool(getattr(ms, "is_paid", False)):
        messages.info(request, "لا يمكن تسليم المرحلة بعد اعتمادها أو سدادها.")
        return _redirect_to_request_detail(ms)

    note = (request.POST.get("note") or "").strip()
    updates: List[str] = []
    _set_db_field(ms, "delivered_at", timezone.now(), updates)
    _set_db_field(ms, "delivered_note", note, updates)
    _set_db_field(ms, "is_delivered", True, updates)
    _set_db_field(ms, "is_pending_review", True, updates)
    _set_db_field(ms, "is_rejected", False, updates)
    _set_db_field(ms, "rejected_reason", "", updates)
    _set_db_field(ms, "updated_at", timezone.now(), updates)
    ms.save(update_fields=updates or None)

    # تأكيد دفع الطلب باتجاه التنفيذ فقط (بدون إكمال)
    _touch_request_in_progress(req)

    messages.success(request, "تم تسليم المرحلة — أُرسلت للمراجعة لدى العميل.")
    return _redirect_to_request_detail(ms)

@login_required
@transaction.atomic
def milestone_approve(request: HttpRequest, milestone_id: int, *args, **kwargs) -> HttpResponse:
    """
    اعتماد المرحلة من قِبل العميل (أو staff/admin):
    - يغلق المراجعة ويثبت الاعتماد.
    - يُنشئ/يُحدّث الفاتورة المرتبطة (واحدة لكل Milestone).
    - يضبط issued_at الآن و due_at بعد 3 أيام.
    - لا يُكمل الطلب هنا.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ms = get_object_or_404(Milestone.objects.select_related("agreement__request", "agreement"), pk=milestone_id)
    req = ms.agreement.request

    is_admin = _is_admin(request.user)
    is_request_client = (request.user.id == getattr(req, "client_id", None))
    if not (is_admin or is_request_client):
        return HttpResponseForbidden("ليست لديك صلاحية لاعتماد هذه المرحلة")

    if not bool(getattr(ms, "is_pending_review", False)):
        messages.warning(request, "لا يمكن اعتماد المرحلة في وضعها الحالي.")
        return _redirect_to_request_detail(ms)

    if bool(getattr(ms, "is_paid", False)):
        messages.info(request, "هذه المرحلة مدفوعة بالفعل.")
        return _redirect_to_request_detail(ms)

    try:
        ms_updates: List[str] = []
        _set_db_field(ms, "approved_at", timezone.now(), ms_updates)
        _set_db_field(ms, "is_approved", True, ms_updates)
        _set_db_field(ms, "is_pending_review", False, ms_updates)
        _set_db_field(ms, "is_rejected", False, ms_updates)
        _set_db_field(ms, "updated_at", timezone.now(), ms_updates)
        ms.save(update_fields=ms_updates or None)

        # تأكيد دفع الطلب باتجاه التنفيذ فقط (بدون إكمال)
        _touch_request_in_progress(req)

        # إنشاء/جلب الفاتورة
        amount = getattr(ms, "amount", None)
        if not amount:
            total = getattr(ms.agreement, "total_amount", 0) or 0
            count = max(getattr(ms.agreement.milestones, "count", lambda: 0)(), 1)
            amount = (total / count) if total else 0

        inv, created = Invoice.objects.get_or_create(
            milestone=ms,
            defaults={
                "agreement": ms.agreement,
                "amount": amount,
                "status": getattr(Invoice.Status, "UNPAID", "unpaid"),
            },
        )

        inv_updates: List[str] = []
        if hasattr(inv, "issued_at") and not getattr(inv, "issued_at", None):
            inv.issued_at = timezone.now()
            inv_updates.append("issued_at")
        if hasattr(inv, "due_at") and not getattr(inv, "due_at", None):
            base_time = getattr(inv, "issued_at", None) or timezone.now()
            inv.due_at = base_time + timedelta(days=3)
            inv_updates.append("due_at")
        if inv_updates:
            inv.save(update_fields=inv_updates)

    except Exception as exc:
        logger.exception("milestone_approve failed (milestone_id=%s): %s", milestone_id, exc)
        messages.error(request, "حدث خطأ غير متوقع أثناء اعتماد المرحلة.")
        return _redirect_to_request_detail(ms)

    messages.success(request, "تم اعتماد المرحلة وإصدار الفاتورة المستحقة.")
    return _redirect_to_request_detail(ms)

@login_required
@transaction.atomic
def milestone_reject(request: HttpRequest, milestone_id: int, *args, **kwargs) -> HttpResponse:
    """
    رفض المرحلة من قِبل العميل (أو staff/admin) مع سبب واضح:
    - يغلق المراجعة ويثبت الرفض ويسجل السبب.
    - يسمح للموظف بإعادة التسليم لاحقًا.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ms = get_object_or_404(Milestone.objects.select_related("agreement__request"), pk=milestone_id)
    req = ms.agreement.request

    is_admin = _is_admin(request.user)
    is_request_client = (request.user.id == getattr(req, "client_id", None))
    if not (is_admin or is_request_client):
        return HttpResponseForbidden("ليست لديك صلاحية لرفض هذه المرحلة")

    if not bool(getattr(ms, "is_pending_review", False)):
        messages.warning(request, "لا يمكن رفض المرحلة في وضعها الحالي.")
        return _redirect_to_request_detail(ms)

    reason = (request.POST.get("reason") or "").strip()
    if len(reason) < 3:
        messages.error(request, "فضلاً أدخل سببًا واضحًا (٣ أحرف على الأقل).")
        return _redirect_to_request_detail(ms)

    updates: List[str] = []
    _set_db_field(ms, "rejected_reason", reason[:500], updates)
    _set_db_field(ms, "is_rejected", True, updates)
    _set_db_field(ms, "is_pending_review", False, updates)
    _set_db_field(ms, "is_approved", False, updates)
    _set_db_field(ms, "updated_at", timezone.now(), updates)
    ms.save(update_fields=updates or None)

    messages.info(request, "تم رفض المرحلة. يمكن للموظف إعادة التسليم بعد التصحيح.")
    return _redirect_to_request_detail(ms)
