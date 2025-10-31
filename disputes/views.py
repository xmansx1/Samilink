from __future__ import annotations
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from marketplace.models import ServiceRequest  # اسم الموديل عندك للطلبات
from .models import Dispute  # موديل النزاع
from .forms import DisputeForm  # فورم بسيط: fields=["title","description"]

from marketplace.models import Request
from notifications.utils import create_notification  # اختياري إن متاح
from .models import Dispute

def _is_admin(u):
    return u.is_authenticated and (getattr(u, "role", None) == "admin" or getattr(u, "is_staff", False))

def _can_open_dispute(user, req) -> tuple[bool, str]:
    if not user.is_authenticated:
        return False, "anonymous"
    if user.id == getattr(req, "client_id", None):
        return True, "client"
    if getattr(req, "assigned_employee_id", None) == user.id:
        return True, "employee"
    if _is_admin(user):
        return True, "admin"
    return False, "forbidden"

def _safe_set_request_on_hold(req: Request):
    """
    سياسة المنتج: النزاعات تؤدي لتجميد مالي فوري.
    سنحاول وضع الحالة إلى 'on_hold' إن كان الحقل/القيمة موجودة،
    وإلا نُحوِّل إلى 'in_dispute' إن وُجدت، وإلا لا نكسر شيئًا.
    """
    field = "status" if hasattr(req, "status") else ("state" if hasattr(req, "state") else None)
    if not field:
        return
    current = getattr(req, field)
    target = None
    for val in ("on_hold", "in_dispute"):
        # نختار أول قيمة مدعومة
        if hasattr(req, "Status") and hasattr(req.Status, val.upper()):
            target = getattr(req.Status, val.upper())
            break
        # fallback نصي
        if target is None:
            target = val
    if current != target:
        setattr(req, field, target)

def _notify_safe(user, title, body, url=""):
    try:
        create_notification(recipient=user, title=title, body=body, url=url)
    except Exception:
        pass

@login_required
@transaction.atomic
def dispute_create(request, request_id: int):
    """
    إنشاء نزاع (POST فقط) من العميل أو الموظف المُسنَد أو الإداري.
    المتطلبات: form يرسل title, reason, details اختياريًا.
    """
    if request.method != "POST":
        raise PermissionDenied

    req = get_object_or_404(Request, pk=request_id)
    ok, role = _can_open_dispute(request.user, req)
    if not ok:
        raise PermissionDenied

    title = (request.POST.get("title") or "").strip()
    reason = (request.POST.get("reason") or "").strip()
    details = (request.POST.get("details") or "").strip()
    milestone_id = request.POST.get("milestone_id") or None

    if len(title) < 3 or len(reason) < 3:
        messages.error(request, "يجب إدخال عنوان وسبب واضحين (٣ أحرف على الأقل).")
        return redirect("marketplace:request_detail", pk=req.pk)

    # يمنع وجود نزاع مفتوح مسبقًا لنفس الطلب (constraint في الموديل)
    try:
        d = Dispute.objects.create(
            request=req,
            milestone_id=int(milestone_id) if milestone_id else None,
            opened_by=request.user,
            opener_role=role,
            title=title,
            reason=reason,
            details=details,
        )
    except Exception as e:
        messages.error(request, f"تعذر فتح نزاع: {e}")
        return redirect("marketplace:request_detail", pk=req.pk)

    # تجميد الطلب ماليًا/عملياتيًا
    _safe_set_request_on_hold(req)
    try:
        req.save(update_fields=["status", "updated_at"] if hasattr(req, "updated_at") else ["status"])
    except Exception:
        # تجاهل إن لم يوجد الحقل
        pass

    # إشعارات
    try:
        url = reverse("marketplace:request_detail", args=[req.pk])
        # أبلغ العميل/الموظف/الإداريين المعنيين
        target_users = set()
        if getattr(req, "client", None):
            target_users.add(req.client)
        if getattr(req, "assigned_employee", None):
            target_users.add(req.assigned_employee)
        for u in target_users:
            if u and u.id != request.user.id:
                _notify_safe(u, "تم فتح نزاع", f"تم فتح نزاع على الطلب #{req.pk}: {title}", url=url)
    except Exception:
        pass

    messages.warning(request, "تم فتح النزاع وجرى إيقاف التعامل المالي مؤقتًا حتى الحسم.")
    return redirect("marketplace:request_detail", pk=req.pk)

@login_required
@transaction.atomic
def dispute_update_status(request, dispute_id: int):
    """
    تغيير حالة النزاع: in_review / resolved / canceled
    - الإداري: جميع الحالات.
    - العميل/الموظف: يمكنهما (طلب إلغاء) فقط لو كانا صاحبي النزاع.
    """
    d = get_object_or_404(Dispute, pk=dispute_id)
    req = d.request
    user = request.user

    new_status = (request.POST.get("status") or "").strip()
    allowed = {Dispute.Status.IN_REVIEW, Dispute.Status.RESOLVED, Dispute.Status.CANCELED}

    if new_status not in allowed:
        messages.error(request, "حالة نزاع غير مسموح بها.")
        return redirect("marketplace:request_detail", pk=req.pk)

    # صلاحيات
    if _is_admin(user):
        pass
    else:
        # صاحب النزاع فقط يمكنه طلب الإلغاء (وليس الحسم)
        if new_status != Dispute.Status.CANCELED or d.opened_by_id != user.id:
            raise PermissionDenied

    # تطبيق التغيير
    d.status = new_status
    if new_status == Dispute.Status.RESOLVED:
        d.resolved_by = user
        d.resolved_at = d.resolved_at or d.opened_at.__class__.now()
        d.resolved_note = (request.POST.get("resolved_note") or "").strip()
    d.save()

    # إن حُسم النزاع: نفك التجميد ونُعيد الحالة
    if new_status in (Dispute.Status.RESOLVED, Dispute.Status.CANCELED):
        # إعادة الطلب إلى وضعه الطبيعي (مثال آمن: in_progress)
        field = "status" if hasattr(req, "status") else ("state" if hasattr(req, "state") else None)
        if field:
            target = None
            # نفضّل in_progress إن مدعومة وإلا نرجع آخر حالة منطقية
            for val in ("in_progress", "awaiting_review", "awaiting_payment"):
                if hasattr(req, "Status") and hasattr(req.Status, val.upper()):
                    target = getattr(req.Status, val.upper()); break
                if target is None:
                    target = val
            try:
                setattr(req, field, target)
                req.save(update_fields=[field, "updated_at"] if hasattr(req, "updated_at") else [field])
            except Exception:
                pass

    messages.success(request, "تم تحديث حالة النزاع.")
    return redirect("marketplace:request_detail", pk=req.pk)

def _can_open_dispute(user, req: "Request") -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False) or getattr(user, "role", "") == "admin":
        return True
    return user.id in (req.client_id, getattr(req, "assigned_employee_id", None))

@login_required
def open_request_dispute(request: HttpRequest, pk: int) -> HttpResponse:
    req = get_object_or_404(Request, pk=pk)
    if not _can_open_dispute(request.user, req):
        return HttpResponseForbidden("لا تملك صلاحية فتح نزاع على هذا الطلب.")

    if request.method == "POST":
        form = DisputeForm(request.POST)
        if form.is_valid():
            d: Dispute = form.save(commit=False)
            d.request = req
            d.opened_by = request.user
            d.save()
            messages.success(request, "تم فتح النزاع بنجاح.")
            return redirect(req.get_absolute_url())
        messages.error(request, "فضلاً صحّح الأخطاء في النموذج.")
    else:
        form = DisputeForm()

    return render(request, "disputes/open.html", {"form": form, "req": req})
