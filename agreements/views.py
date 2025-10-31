# agreements/views.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import transaction
from django.forms.formsets import BaseFormSet
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from marketplace.models import Request, Offer
from .forms import AgreementEditForm, MilestoneFormSet, AgreementClauseSelectForm
from .models import Agreement, AgreementClauseItem, Milestone


# =========================
# أدوات مساعدة داخلية
# =========================

def _is_admin(user) -> bool:
    """تحديد صلاحية المدير/الـstaff وفق نظامك."""
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or getattr(user, "role", "") == "admin"
    )


def _is_emp_or_admin(user) -> bool:
    role = getattr(user, "role", None)
    return bool(_is_admin(user) or role == "employee")


def _get_selected_offer(req: Request) -> Offer | None:
    """يحصل على العرض المختار للطلب إن وُجد (يدعم الخاصية أو الاستعلام)."""
    off = getattr(req, "selected_offer", None)
    if off:
        return off
    return (
        req.offers.filter(status=Offer.Status.SELECTED)
        .select_related("employee")
        .first()
    )


def _assign_auto_order(formset: BaseFormSet) -> None:
    """يرقّم الدفعات 1..n قبل الحفظ (يعمل مع أي FormSet يشبه BaseFormSet)."""
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
    """يجمع مبالغ الدفعات (مع تجاهل العناصر المحذوفة)."""
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
    قفل خادمي: إن كانت الاتفاقية موجودة بالفعل، نتجاهل أي قيم واردة للمدة/الإجمالي
    ونُبقيهما على قيم قاعدة البيانات (احترازيًا).
    """
    if ag.pk and hasattr(form, "cleaned_data"):
        form.cleaned_data["duration_days"] = ag.duration_days
        form.cleaned_data["total_amount"] = ag.total_amount


def _update_request_status_on_send(req: Request) -> None:
    """تحويل حالة الطلب إلى AGREEMENT_PENDING إن وُجدت."""
    if hasattr(Request.Status, "AGREEMENT_PENDING"):
        req.status = Request.Status.AGREEMENT_PENDING
        req.save(update_fields=["status", "updated_at"])


def _move_request_on_accept(req: Request) -> None:
    """تحويل حالة الطلب إلى IN_PROGRESS عند قبول الاتفاقية (إن وُجدت)."""
    if hasattr(Request.Status, "IN_PROGRESS"):
        req.status = Request.Status.IN_PROGRESS
        req.save(update_fields=["status", "updated_at"])


def _return_request_to_offer_selected(req: Request) -> None:
    """إرجاع حالة الطلب إلى OFFER_SELECTED عند رفض الاتفاقية (إن وُجدت)."""
    if hasattr(Request.Status, "OFFER_SELECTED"):
        req.status = Request.Status.OFFER_SELECTED
        req.save(update_fields=["status", "updated_at"])


def _has_model_field(obj, field_name: str) -> bool:
    """
    يفحص هل الاسم يمثل **حقل قاعدة بيانات فعلي** في الموديل،
    وليس مجرد خاصية @property بنفس الاسم.
    """
    try:
        obj._meta.get_field(field_name)  # type: ignore[attr-defined]
        return True
    except FieldDoesNotExist:
        return False


# =========================
# واجهات الاستخدام
# =========================

@login_required
def open_by_request(request: HttpRequest, request_id: int) -> HttpResponse:
    """
    يفتح/ينشئ اتفاقية لطلب محدد:
    - إن وُجدت اتفاقية: إعادة توجيه لتفاصيلها.
    - إن لم توجد: إنشاء مسودة من العرض المختار ثم التحويل للتحرير.
    الصلاحية: الموظف المُسنَد أو الأدمن/الستاف.
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
    """تفاصيل الاتفاقية (لجميع الأطراف مع قيود الوصول)."""
    ag = get_object_or_404(
        Agreement.objects.select_related("request", "employee", "request__client")
        .prefetch_related("clause_items__clause", "milestones"),
        pk=pk,
    )
    req = ag.request

    # صلاحيات عرض:
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
    تحرير الاتفاقية (الموظف/الأدمن). العميل لا يحرر من هنا.
    - حفظ كمسودة
    - حفظ وإرسال للعميل (يتحقق من مجموع الدفعات)
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
                # قفل خادمي إضافي (احترازي)
                _lock_core_fields_if_needed(ag, form)
                ag = form.save()

                # ترقيم الدفعات وتثبيتها
                _assign_auto_order(formset)
                formset.save()

                if action == "send":
                    # تحقق: مجموع الدفعات = الإجمالي بدقة سنتين
                    total_m = _sum_milestones(formset).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    total_ag = (ag.total_amount or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if total_m != total_ag:
                        messages.error(
                            request,
                            f"مجموع الدفعات ({total_m}) لا يساوي الإجمالي ({total_ag}).",
                        )
                        # نعيد العرض دون ترقية الحالة
                        return render(
                            request,
                            "agreements/agreement_form.html",
                            {"agreement": ag, "req": req, "form": form, "formset": formset},
                        )

                    # تحويل حالة الاتفاقية + الطلب
                    ag.status = Agreement.Status.PENDING
                    ag.save(update_fields=["status", "updated_at"])
                    _update_request_status_on_send(req)

                    messages.success(request, "تم حفظ الاتفاقية وإرسالها للعميل.")
                    return redirect("agreements:detail", pk=ag.pk)

                # حفظ كمسودة
                ag.status = Agreement.Status.DRAFT
                ag.save(update_fields=["status", "updated_at"])
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
    """موافقة العميل على اتفاقية طلب معيّن."""
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
    ag.save(update_fields=["status", "updated_at"])
    _move_request_on_accept(req)

    messages.success(request, "تمت الموافقة على الاتفاقية. تم تحويل الطلب إلى قيد التنفيذ.")
    return redirect("agreements:detail", pk=ag.pk)


@login_required
def reject_by_request(request: HttpRequest, request_id: int) -> HttpResponse:
    """عرض صفحة سبب الرفض للعميل."""
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
    """حفظ سبب الرفض وإرجاع الطلب إلى مرحلة اختيار العرض."""
    ag = get_object_or_404(Agreement.objects.select_related("request"), pk=pk)
    req = ag.request

    if request.user.id != req.client_id and not _is_admin(request.user):
        messages.error(request, "غير مصرح برفض هذه الاتفاقية.")
        return redirect("agreements:detail", pk=ag.pk)

    reason = (request.POST.get("reason") or "").strip()
    if len(reason) < 5:
        messages.error(request, "الرجاء توضيح سبب الرفض (5 أحرف على الأقل).")
        return render(request, "agreements/agreement_reject.html", {"agreement": ag, "req": req})

    ag.rejection_reason = reason[:1000]
    ag.status = Agreement.Status.REJECTED
    ag.save(update_fields=["rejection_reason", "status", "updated_at"])

    _return_request_to_offer_selected(req)

    messages.success(request, "تم رفض الاتفاقية وإعادتها إلى مرحلة العروض.")
    return redirect("agreements:detail", pk=ag.pk)


# =========================
# تثبيت البنود (للأدمن/الموظف المالك)
# =========================

@login_required
@transaction.atomic
def finalize_clauses(request: HttpRequest, pk: int) -> HttpResponse:
    """
    تثبيت/تعديل بنود الاتفاقية.
    يسمح للـ staff/superuser أو الموظف المُسنَد على الاتفاقية.
    """
    agreement = get_object_or_404(
        Agreement.objects.select_related("employee", "request"),
        pk=pk,
    )

    user = request.user
    is_owner_emp = (user.id == agreement.employee_id)
    if not (_is_admin(user) or is_owner_emp):
        messages.error(request, "غير مصرح لك بتعديل بنود هذه الاتفاقية.")
        return redirect("agreements:detail", pk=agreement.pk)

    if request.method == "POST":
        form = AgreementClauseSelectForm(request.POST)
        if form.is_valid():
            # امسح البنود القديمة وأعد إنشاءها بترتيب جديد
            AgreementClauseItem.objects.filter(agreement=agreement).delete()
            pos = 1

            # 1) بنود جاهزة
            for clause in form.cleaned_data.get("clauses", []):
                AgreementClauseItem.objects.create(
                    agreement=agreement, clause=clause, position=pos
                )
                pos += 1

            # 2) بنود مخصّصة (سطر لكل بند)
            for line in form.cleaned_custom_lines():
                AgreementClauseItem.objects.create(
                    agreement=agreement, custom_text=line, position=pos
                )
                pos += 1

            messages.success(request, "تم حفظ بنود الاتفاقية بنجاح.")
            return redirect("agreements:detail", pk=agreement.pk)
        else:
            messages.error(request, "الرجاء تصحيح الأخطاء في نموذج البنود.")
    else:
        form = AgreementClauseSelectForm()

    return render(
        request,
        "agreements/finalize_clauses.html",
        {"agreement": agreement, "form": form},
    )


# =========================
# إجراءات المراحل (Milestone)
# =========================

def _redirect_to_request_detail(ms: Milestone) -> HttpResponse:
    """إعادة التوجيه لصفحة تفاصيل الطلب المرتبط بالاتفاقية."""
    req = ms.agreement.request
    return redirect("marketplace:request_detail", pk=req.pk)


@login_required
def milestone_deliver(request: HttpRequest, milestone_id: int, *args, **kwargs) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ms = get_object_or_404(Milestone.objects.select_related("agreement__request"), pk=milestone_id)
    req = ms.agreement.request

    # صلاحية: الموظف المعيّن فقط (أو staff/admin)
    if not (request.user.is_staff or getattr(request.user, "role", "") == "admin" or request.user.id == getattr(req, "assigned_employee_id", None)):
        messages.error(request, "ليست لديك صلاحية لتسليم هذه المرحلة.")
        return _redirect_to_request_detail(ms)

    # حراسة الحالة
    if bool(getattr(ms, "is_approved", False)):
        messages.info(request, "تم اعتماد هذه المرحلة مسبقًا.")
        return _redirect_to_request_detail(ms)
    if bool(getattr(ms, "is_delivered", False)):
        messages.info(request, "هذه المرحلة مُسلّمة بالفعل وتنتظر مراجعة العميل.")
        return _redirect_to_request_detail(ms)

    note = (request.POST.get("note") or "").strip()
    update_fields: list[str] = []

    if _has_model_field(ms, "delivered_at"):
        ms.delivered_at = timezone.now()
        update_fields.append("delivered_at")

    if _has_model_field(ms, "delivered_note"):
        ms.delivered_note = note
        update_fields.append("delivered_note")

    if _has_model_field(ms, "is_delivered"):
        ms.is_delivered = True  # type: ignore[attr-defined]
        update_fields.append("is_delivered")

    if _has_model_field(ms, "is_pending_review"):
        ms.is_pending_review = True  # type: ignore[attr-defined]
        update_fields.append("is_pending_review")

    if _has_model_field(ms, "is_rejected"):
        ms.is_rejected = False  # type: ignore[attr-defined]
        update_fields.append("is_rejected")

    if _has_model_field(ms, "updated_at"):
        setattr(ms, "updated_at", timezone.now())
        update_fields.append("updated_at")

    ms.save(update_fields=update_fields or None)

    messages.success(request, "تم تسليم المرحلة — أُرسلت للمراجعة لدى العميل.")
    return _redirect_to_request_detail(ms)


@login_required
def milestone_approve(request: HttpRequest, milestone_id: int, *args, **kwargs) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ms = get_object_or_404(Milestone.objects.select_related("agreement__request"), pk=milestone_id)
    req = ms.agreement.request

    # صلاحية: العميل فقط (أو staff/admin)
    if not (request.user.is_staff or getattr(request.user, "role", "") == "admin" or request.user.id == getattr(req, "client_id", None)):
        messages.error(request, "ليست لديك صلاحية لاعتماد هذه المرحلة.")
        return _redirect_to_request_detail(ms)

    if not bool(getattr(ms, "is_pending_review", False)):
        messages.warning(request, "لا يمكن اعتماد المرحلة في وضعها الحالي.")
        return _redirect_to_request_detail(ms)

    update_fields: list[str] = []

    if _has_model_field(ms, "approved_at"):
        ms.approved_at = timezone.now()
        update_fields.append("approved_at")

    if _has_model_field(ms, "is_approved"):
        ms.is_approved = True  # type: ignore[attr-defined]
        update_fields.append("is_approved")

    if _has_model_field(ms, "is_pending_review"):
        ms.is_pending_review = False  # type: ignore[attr-defined]
        update_fields.append("is_pending_review")

    if _has_model_field(ms, "is_rejected"):
        ms.is_rejected = False  # type: ignore[attr-defined]
        update_fields.append("is_rejected")

    if _has_model_field(ms, "updated_at"):
        setattr(ms, "updated_at", timezone.now())
        update_fields.append("updated_at")

    ms.save(update_fields=update_fields or None)

    # إن كانت لديك إشارة signals لإنشاء/تنشيط الفاتورة عند الاعتماد، ستعمل تلقائيًا.
    messages.success(request, "تم اعتماد المرحلة بنجاح.")
    return _redirect_to_request_detail(ms)


@login_required
def milestone_reject(request: HttpRequest, milestone_id: int, *args, **kwargs) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ms = get_object_or_404(Milestone.objects.select_related("agreement__request"), pk=milestone_id)
    req = ms.agreement.request

    # صلاحية: العميل فقط (أو staff/admin)
    if not (request.user.is_staff or getattr(request.user, "role", "") == "admin" or request.user.id == getattr(req, "client_id", None)):
        messages.error(request, "ليست لديك صلاحية لرفض هذه المرحلة.")
        return _redirect_to_request_detail(ms)

    if not bool(getattr(ms, "is_pending_review", False)):
        messages.warning(request, "لا يمكن رفض المرحلة في وضعها الحالي.")
        return _redirect_to_request_detail(ms)

    reason = (request.POST.get("reason") or "").strip()
    update_fields: list[str] = []

    if _has_model_field(ms, "rejected_reason"):
        ms.rejected_reason = reason[:500] if reason else ""
        update_fields.append("rejected_reason")

    if _has_model_field(ms, "is_rejected"):
        ms.is_rejected = True  # type: ignore[attr-defined]
        update_fields.append("is_rejected")

    if _has_model_field(ms, "is_pending_review"):
        ms.is_pending_review = False  # type: ignore[attr-defined]
        update_fields.append("is_pending_review")

    if _has_model_field(ms, "is_approved"):
        ms.is_approved = False  # type: ignore[attr-defined]
        update_fields.append("is_approved")

    if _has_model_field(ms, "updated_at"):
        setattr(ms, "updated_at", timezone.now())
        update_fields.append("updated_at")

    ms.save(update_fields=update_fields or None)

    messages.info(request, "تم رفض المرحلة. يمكنك طلب تعديل/إعادة التسليم عبر المحادثة.")
    return _redirect_to_request_detail(ms)
