# agreements/signals.py
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Milestone

# ملاحظة: نتجنب الاستيراد الدائري بوضع الاستيراد داخل الدوال عند الحاجة


@receiver(post_save, sender=Milestone)
def handle_milestone_post_save(sender, instance: Milestone, created: bool, **kwargs):
    """
    - عند اعتماد المرحلة APPROVED: إنشاء فاتورة تلقائيًا إذا لم توجد.
    - عند دفع جميع فواتير الاتفاقية: وضع الاتفاقية والطلب في COMPLETED.
    الكود دفاعي ليتعامل مع اختلافات طفيفة في الأسماء.
    """
    # أسماء الحالات المتوقعة
    STATUS_APPROVED = getattr(Milestone.Status, "APPROVED", "approved")
    STATUS_PAID = getattr(Milestone.Status, "PAID", "paid")

    milestone = instance
    agreement = getattr(milestone, "agreement", None)
    if agreement is None:
        return  # لا يوجد اتفاقية مرتبطة (حالة استثنائية)

    # استيرادات متأخرة لتفادي circular imports
    from finance.models import Invoice

    with transaction.atomic():
        # 1) إنشاء فاتورة تلقائيًا عند الموافقة على المرحلة
        if getattr(milestone, "status", "") == STATUS_APPROVED:
            # إن لم توجد فاتورة مرتبطة بهذه المرحلة
            inv_exists = Invoice.objects.filter(milestone=milestone).exists()
            if not inv_exists:
                Invoice.objects.create(
                    agreement=agreement,
                    milestone=milestone,
                    amount=getattr(milestone, "amount", 0),
                    status=getattr(Invoice.Status, "UNPAID", "unpaid"),
                )

        # 2) التحقق من اكتمال الاتفاقية/الطلب عند دفع كل المراحل
        # معيار الاكتمال: لا توجد فواتير غير مدفوعة على الاتفاقية
        unpaid = agreement.invoices.filter(status=getattr(Invoice.Status, "UNPAID", "unpaid")).exists()
        if not unpaid:
            # كل الفواتير مدفوعة ⇒ اعتبر كل المراحل مدفوعة أيضًا (في حال اختلاف الترتيب)
            # ونعلن اكتمال الاتفاقية والطلب
            # تحديث المرحلة الحالية إن لزم
            if getattr(milestone, "status", "") != STATUS_PAID and \
               Invoice.objects.filter(milestone=milestone, status=getattr(Invoice.Status, "PAID", "paid")).exists():
                milestone.status = STATUS_PAID
                # إن كان لديك حقل paid_at على milestone فحدّثه من invoice.paid_at
                paid_inv = Invoice.objects.filter(milestone=milestone, status=getattr(Invoice.Status, "PAID", "paid")).order_by("-paid_at").first()
                if paid_inv and hasattr(milestone, "paid_at"):
                    milestone.paid_at = paid_inv.paid_at
                milestone.save(update_fields=["status"] + (["paid_at"] if hasattr(milestone, "paid_at") else []))

            # إعلان اكتمال الاتفاقية
            if hasattr(agreement, "status"):
                agreement.status = "completed"
                agreement.save(update_fields=["status"])

            # إعلان اكتمال الطلب المرتبط
            req = getattr(agreement, "request", None)
            if req is not None and hasattr(req, "status"):
                req.status = "completed"
                req.save(update_fields=["status"])
