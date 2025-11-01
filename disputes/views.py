# disputes/views.py
from __future__ import annotations

import logging
from typing import Tuple, Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from marketplace.models import Request
from .forms import DisputeForm
from .models import Dispute

logger = logging.getLogger(__name__)

# --- Notification adapter (safe imports) ---
# يحاول استخدام core.utils.notify_user وإن فشل يسقط على notifications.utils.create_notification
try:
    from core.utils import notify_user as _notify_user  # type: ignore
except Exception:
    _notify_user = None  # type: ignore

try:
    from notifications.utils import create_notification as _create_notification  # type: ignore
except Exception:
    _create_notification = None  # type: ignore


def _notify_safe(user, title: str, body: str, url: Optional[str] = None) -> None:
    if not user:
        return
    try:
        if _notify_user:
            _notify_user(user, title=title, body=body, link=url)
            return
        if _create_notification:
            _create_notification(recipient=user, title=title, body=body, url=url or "")
    except Exception:
        # لا نكسر التدفق بسبب الإشعار
        pass


# =========================
# Helpers (صلاحيات/تجميد)
# =========================

def _is_admin(user) -> bool:
    """صلاحيات إدارية/مالية موسعة."""
    role = getattr(user, "role", "")
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or role in {"admin", "finance"}
    )


def _can_open_dispute(user, req: Request) -> Tuple[bool, str]:
    """
    تحديد مَن يحق له فتح نزاع على الطلب:
    - العميل صاحب الطلب
    - الموظف المعيّن على الطلب
    - الإدارة/المالية
    يعاد (مسموح؟, دور الفاتح 'client'/'employee'/'admin' أو '')
    """
    if not user or not user.is_authenticated:
        return (False, "")
    if getattr(req, "client_id", None) == getattr(user, "id", None):
        return (True, "client")
    if getattr(req, "assigned_to_id", None) == getattr(user, "id", None):
        return (True, "employee")
    if _is_admin(user):
        return (True, "admin")
    return (False, "")


def _freeze_request(req: Request) -> None:
    """
    تجميد الطلب أثناء النزاع:
    - الحالة → DISPUTED (إن كانت متاحة)
    - is_frozen=True إن وُجد الحقل
    """
    updated_fields = []

    if hasattr(Request, "Status") and hasattr(Request.Status, "DISPUTED"):
        if req.status != Request.Status.DISPUTED:
            req.status = Request.Status.DISPUTED
            updated_fields.append("status")
    else:
        # fallback نصي (في حال عدم وجود Enum)
        if getattr(req, "status", None) != "disputed":
            req.status = "disputed"
            updated_fields.append("status")

    if hasattr(req, "is_frozen") and not getattr(req, "is_frozen", False):
        req.is_frozen = True
        updated_fields.append("is_frozen")

    if updated_fields:
        req.save(update_fields=updated_fields)


def _unfreeze_request(req: Request) -> None:
    """
    فكّ التجميد بعد حل/إلغاء النزاع:
    - الحالة: إن كانت DISPUTED نعيدها لحالة منطقية:
        * IN_PROGRESS إذا كان هناك اتفاقية/تنفيذ جارٍ
        * NEW خلاف ذلك
    - is_frozen=False إن وُجد الحقل
    """
    updated_fields = []

    # إعادة الحالة منطقياً
    if (hasattr(Request, "Status") and hasattr(Request.Status, "DISPUTED") and req.status == Request.Status.DISPUTED) \
       or (getattr(req, "status", None) == "disputed"):
        if getattr(req, "agreement", None):
            fallback = Request.Status.IN_PROGRESS if hasattr(Request.Status, "IN_PROGRESS") else "in_progress"
        else:
            fallback = Request.Status.NEW if hasattr(Request.Status, "NEW") else "new"

        if req.status != fallback:
            req.status = fallback
            updated_fields.append("status")

    if hasattr(req, "is_frozen") and getattr(req, "is_frozen", False):
        req.is_frozen = False
        updated_fields.append("is_frozen")

    if updated_fields:
        req.save(update_fields=updated_fields)


# ===============
# Views
# ===============

@login_required
@transaction.atomic
def dispute_create(request, request_id: int):
    """
    فتح نزاع على طلب:
    - POST: يستقبل (title, reason, details[, milestone_id])
    - يتحقق من صلاحيات الفاتح
    - ينشئ النزاع (مع UniqueConstraint في الموديل لمنع نزاع مفتوح آخر)
    - يجمّد الطلب (status=DISPUTED, is_frozen=True إن وجد)
    - يرسل إشعارات للعميل والموظف المعنيين
    """
    req = get_object_or_404(Request.objects.select_for_update(), pk=request_id)

    ok, role = _can_open_dispute(request.user, req)
    if not ok:
        raise PermissionDenied("لا تملك صلاحية فتح نزاع على هذا الطلب.")

    if request.method == "POST":
        form = DisputeForm(request.POST)
        if form.is_valid():
            dispute = form.save(commit=False)
            dispute.request = req
            dispute.opened_by = request.user
            if hasattr(dispute, "opener_role"):
                dispute.opener_role = role

            # milestone_id اختياري إن وجد في الموديل
            m_id = (request.POST.get("milestone_id") or "").strip()
            if m_id and hasattr(dispute, "milestone_id"):
                try:
                    dispute.milestone_id = int(m_id)
                except ValueError:
                    pass

            dispute.save()

            # تجميد الطلب
            _freeze_request(req)

            # إشعارات
            detail_url = reverse("marketplace:request_detail", args=[req.pk])
            if getattr(req, "client", None):
                _notify_safe(req.client, "تم فتح نزاع", f"فُتح نزاع على طلبك #{req.pk}: {dispute.title}", url=detail_url)
            if getattr(req, "assigned_to", None):
                _notify_safe(req.assigned_to, "تم فتح نزاع", f"فُتح نزاع على طلب #{req.pk}: {dispute.title}", url=detail_url)

            messages.warning(request, "تم فتح النزاع وتجميد الطلب مؤقتًا حتى الحسم.")
            return redirect(detail_url)
        else:
            messages.error(request, "فضلاً صحّح الأخطاء في النموذج.")
    else:
        form = DisputeForm()

    return render(request, "disputes/open.html", {"form": form, "req": req})


@login_required
@transaction.atomic
def dispute_update_status(request, pk: int):
    """
    تحديث حالة نزاع — للمسؤولين/المالية فقط.
    القيم المتوقعة من POST[name='action']: {resolve, cancel, review, reopen}
    - resolve/cancel: فكّ التجميد (عودة الطلب لحالة منطقية)
    - review: تحويل النزاع إلى IN_REVIEW
    - reopen: إعادة فتح النزاع (تجميد الطلب)
    """
    dispute = get_object_or_404(
        Dispute.objects.select_for_update().select_related("request", "opened_by"),
        pk=pk,
    )
    req = dispute.request

    if not _is_admin(request.user):
        raise PermissionDenied("صلاحيات غير كافية لإدارة النزاع.")

    action = (request.POST.get("action") or "").strip().lower()
    if action not in {"resolve", "cancel", "review", "reopen"}:
        messages.error(request, "طلب غير صحيح.")
        return redirect(reverse("marketplace:request_detail", args=[req.pk]))

    # تحويل الأكشن إلى حالة
    if action == "resolve":
        new_status = Dispute.Status.RESOLVED if hasattr(Dispute, "Status") else "resolved"
    elif action == "cancel":
        new_status = Dispute.Status.CANCELED if hasattr(Dispute, "Status") else "canceled"
    elif action == "review":
        new_status = Dispute.Status.IN_REVIEW if hasattr(Dispute, "Status") else "in_review"
    else:  # reopen
        new_status = Dispute.Status.OPEN if hasattr(Dispute, "Status") else "open"

    # تطبيق الحالة
    dispute.status = new_status
    update_fields = ["status"]

    if new_status in (getattr(Dispute.Status, "RESOLVED", "resolved"), getattr(Dispute.Status, "CANCELED", "canceled")):
        if hasattr(dispute, "resolved_by"):
            dispute.resolved_by = request.user
            update_fields.append("resolved_by")
        if hasattr(dispute, "resolved_note"):
            dispute.resolved_note = (request.POST.get("resolved_note") or "").strip()
            update_fields.append("resolved_note")

    dispute.save(update_fields=update_fields)

    # إدارة تجميد/فك تجميد الطلب
    if new_status in (getattr(Dispute.Status, "RESOLVED", "resolved"), getattr(Dispute.Status, "CANCELED", "canceled")):
        _unfreeze_request(req)
        messages.success(request, "تم إنهاء النزاع وفكّ التجميد.")
        # إشعارات إنهاء
        detail_url = reverse("marketplace:request_detail", args=[req.pk])
        if getattr(req, "client", None):
            _notify_safe(req.client, "تم إنهاء النزاع", f"تم إنهاء النزاع على طلب #{req.pk}.", url=detail_url)
        if getattr(req, "assigned_to", None):
            _notify_safe(req.assigned_to, "تم إنهاء النزاع", f"تم إنهاء النزاع على طلب #{req.pk}.", url=detail_url)
    elif new_status in (getattr(Dispute.Status, "OPEN", "open"),):
        _freeze_request(req)
        messages.warning(request, "تم إعادة فتح النزاع وتمّ تجميد الطلب.")
    else:
        messages.info(request, "تم تحديث حالة النزاع.")

    return redirect(reverse("marketplace:request_detail", args=[req.pk]))


@login_required
def dispute_detail(request, pk: int):
    """
    عرض نزاع بشكل بسيط — مفيد للروابط داخل الإشعارات أو للمراجعة اليدوية.
    """
    dispute = get_object_or_404(Dispute.objects.select_related("request", "opened_by"), pk=pk)
    return render(request, "disputes/detail.html", {"dispute": dispute, "req": dispute.request})
