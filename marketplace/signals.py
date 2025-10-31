from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Offer, Request
from django.utils import timezone
from datetime import timedelta

@receiver(pre_save, sender=Offer)
def _normalize_offer_status(sender, instance: Offer, **kwargs):
    """
    طبّع القيمة لتكون ضمن TextChoices دائمًا (حماية من مدخلات نصية عشوائية).
    """
    valid = {c[0] for c in Offer.STATUS_CHOICES}
    if instance.status not in valid:
        instance.status = Offer.Status.PENDING

@receiver(post_save, sender=Offer)
def handle_offer_selection(sender, instance: Offer, created, **kwargs):
    """
    عند اختيار عرض:
    - إسناد الموظف للطلب.
    - تحديث حالة الطلب إلى OFFER_SELECTED.
    - ضبط طوابع SLA (الآن + 3 أيام).
    - رفض بقية العروض.
    """
    if instance.status == Offer.Status.SELECTED:
        req = instance.request
        # تحديث الطلب + SLA
        req.mark_offer_selected_now(instance.employee)
        req.save(update_fields=[
            "assigned_employee", "status", "offer_selected_at", "agreement_due_at",
            "sla_agreement_overdue", "updated_at"
        ])
        # رفض بقية العروض
        Offer.objects.filter(request=req).exclude(pk=instance.pk).update(status=Offer.Status.REJECTED)
