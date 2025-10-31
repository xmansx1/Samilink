from __future__ import annotations

from typing import Iterable, Optional, TYPE_CHECKING, Any
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse

# لتجنب تحذير "Variable not allowed in type expression" في محررات النوع:
# نستورد النوع الحقيقي فقط وقت الفحص الساكن، وليس وقت التشغيل.
if TYPE_CHECKING:
    from core.models import Notification as NotificationModel  # type: ignore[assignment]
else:
    NotificationModel = Any  # في وقت التشغيل لا نستخدم النوع بالأنوتيشن

# محاولة استيراد نموذج Notification وقت التشغيل (قد لا يكون موجودًا في بعض البيئات)
try:
    from core.models import Notification  # noqa: F401
except Exception:
    Notification = None  # سيجعل دوال الإشعار ترجع None ولن تكسر التنفيذ


def _site_base_url() -> str:
    """
    يُعيد SITE_BASE_URL من الإعدادات بصيغة آمنة (بدون سلاش أخير).
    """
    url = getattr(settings, "SITE_BASE_URL", "").strip()
    return url[:-1] if url.endswith("/") else url


def create_notification(
    *,
    user,
    title: str,
    body: str,
    link: Optional[str] = None,
    level: str = "info",
) -> Optional["NotificationModel"]:
    """
    ينشئ إشعارًا للمستخدم. يرجع كائن Notification أو None في حال عدم توفر الموديل.
    """
    if Notification is None:
        return None

    with transaction.atomic():
        return Notification.objects.create(  # type: ignore[attr-defined]
            user=user,
            title=title[:200],
            body=body[:2000],
            link=(link or "")[:500],
            level=level,
        )


def notify_user(
    user,
    *,
    title: str,
    body: str,
    link: Optional[str] = None,
    level: str = "info",
    by_email: bool = False,
    email_subject: Optional[str] = None,
) -> None:
    """
    يُنشئ إشعارًا للمستخدم، واختياريًا يرسل بريدًا (لا يكسر التدفق عند الفشل).
    """
    create_notification(user=user, title=title, body=body, link=link, level=level)

    if by_email and getattr(user, "email", None):
        try:
            send_mail(
                subject=email_subject or title,
                message=body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@samilink.sa"),
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass  # لا نفشل سير النظام بسبب البريد


def notify_users(
    users: Iterable,
    *,
    title: str,
    body: str,
    link: Optional[str] = None,
    level: str = "info",
    by_email: bool = False,
    email_subject: Optional[str] = None,
) -> int:
    """
    يرسل إشعارًا لمجموعة مستخدمين. يُرجع عدد المستلمين.
    """
    cnt = 0
    for u in users:
        notify_user(
            u,
            title=title,
            body=body,
            link=link,
            level=level,
            by_email=by_email,
            email_subject=email_subject,
        )
        cnt += 1
    return cnt


def notify_finance_of_invoice(invoice, *, base_url: Optional[str] = None) -> int:
    """
    يُنبّه موظفي المالية عند إنشاء/تعديل فاتورة مرحلة.
    يعتمد على users.role='finance' وإلا يسقط إلى is_staff.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    qs = User.objects.filter(role="finance", is_active=True)
    if not qs.exists():
        qs = User.objects.filter(is_staff=True, is_active=True)

    # بناء رابط الفاتورة
    base = (base_url or _site_base_url()).strip()
    if base:
        link = f"{base}{reverse('finance:invoice_detail', args=[invoice.id])}"
    else:
        # الأفضل تمرير build_absolute_uri من الـ view عند الإمكان
        link = reverse("finance:invoice_detail", args=[invoice.id])

    title = f"فاتورة مرحلة #{invoice.id}"
    body = (
        f"تم إنشاء/تحديث فاتورة بقيمة {getattr(invoice, 'amount', '')} ر.س "
        f"للأتفاقية #{getattr(getattr(invoice, 'agreement', None), 'id', '')}."
    )
    return notify_users(qs, title=title, body=body, link=link, level="info")
