from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Agreement
from marketplace.models import Request

@receiver(post_save, sender=Agreement)
def move_request_on_agreement(sender, instance: Agreement, created, **kwargs):
    req = instance.request
    if created:
        # عند إنشاء الاتفاقية: الطلب يصبح agreement_pending
        if req.status != Request.Status.AGREEMENT_PENDING:
            req.status = Request.Status.AGREEMENT_PENDING
            req.save(update_fields=["status", "updated_at"])
    else:
        # عند قبول العميل: الطلب يصبح in_progress
        if instance.status == Agreement.Status.ACCEPTED and req.status != Request.Status.IN_PROGRESS:
            req.status = Request.Status.IN_PROGRESS
            req.save(update_fields=["status", "updated_at"])
