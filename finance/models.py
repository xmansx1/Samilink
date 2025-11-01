# finance/models.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse

User = settings.AUTH_USER_MODEL


class InvoiceQuerySet(models.QuerySet):
    def unpaid(self):
        return self.filter(status=Invoice.Status.UNPAID)

    def paid(self):
        return self.filter(status=Invoice.Status.PAID)

    def cancelled(self):
        return self.filter(status=Invoice.Status.CANCELLED)

    def for_agreement(self, agreement_id: int):
        return self.filter(agreement_id=agreement_id)

    def overdue(self):
        now = timezone.now()
        return self.unpaid().filter(due_at__isnull=False, due_at__lt=now)


class Invoice(models.Model):
    """
    نموذج الفاتورة الماليّة المرتبطة باتفاقية، وقد تُسند إلى مرحلة محددة.
    يدعم تواريخ الإصدار/الاستحقاق/السداد، وحالات: غير مدفوعة / مدفوعة / ملغاة.
    """

    class Status(models.TextChoices):
        UNPAID = "unpaid", "غير مدفوعة"
        PAID = "paid", "مدفوعة"
        CANCELLED = "cancelled", "ملغاة"

    # ارتباطات
    agreement = models.ForeignKey(
        "agreements.Agreement",
        on_delete=models.CASCADE,
        related_name="invoices",
        verbose_name="الاتفاقية",
    )
    milestone = models.ForeignKey(
        "agreements.Milestone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        verbose_name="الدفعة",
        help_text="فاتورة مرتبطة بمرحلة محددة (إن وُجدت). يُفضّل فاتورة واحدة لكل مرحلة.",
    )

    # مبالغ وحالة
    amount = models.DecimalField("المبلغ", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNPAID)

    # تواريخ
    issued_at = models.DateTimeField("تاريخ الإصدار", default=timezone.now, db_index=True)
    due_at = models.DateTimeField("موعد السداد", null=True, blank=True, db_index=True)
    paid_at = models.DateTimeField("تاريخ السداد", null=True, blank=True, db_index=True)

    # معلومات دفع
    method = models.CharField("طريقة السداد", max_length=50, blank=True)  # مثال: حوالة/مدى/فيزا
    ref_code = models.CharField(
        "مرجع العملية",
        max_length=100,
        blank=True,
        db_index=True,
        help_text="مرجع الدفع من بوابة/حوالة. غير فريد بالضرورة.",
    )

    # تتبّع وإنشاء/تحديث
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices_created",
        verbose_name="أنشأها",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["status", "issued_at"]),
            models.Index(fields=["agreement"]),
            models.Index(fields=["paid_at"]),
            models.Index(fields=["due_at"]),
        ]
        constraints = [
            # فاتورة واحدة كحد أقصى لكل Milestone (إن كانت موجودة)
            models.UniqueConstraint(
                fields=["milestone"],
                condition=Q(milestone__isnull=False),
                name="uniq_invoice_per_milestone",
            ),
        ]
        ordering = ["-issued_at", "-id"]
        verbose_name = "فاتورة"
        verbose_name_plural = "فواتير"

    # ======================
    #  تمثيل وروابط
    # ======================

    def __str__(self) -> str:  # pragma: no cover
        return f"Invoice#{self.pk} A{self.agreement_id} — {self.get_status_display()} {self.amount}"

    def get_absolute_url(self) -> str:
        return reverse("finance:invoice_detail", kwargs={"pk": self.pk})

    def get_mark_paid_url(self) -> str:
        # تأكد أن اسم المسار مطابق لملف urls في تطبيق finance
        return reverse("finance:mark_invoice_paid", kwargs={"pk": self.pk})

    # ======================
    #  خصائص مشتقة
    # ======================

    @property
    def is_unpaid(self) -> bool:
        return self.status == self.Status.UNPAID

    @property
    def is_paid(self) -> bool:
        return self.status == self.Status.PAID

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.Status.CANCELLED

    @property
    def is_overdue(self) -> bool:
        """متأخرة: غير مدفوعة وتجاوزت موعد السداد."""
        return bool(self.is_unpaid and self.due_at and self.due_at < timezone.now())

    @property
    def remaining_days(self) -> Optional[int]:
        """
        الأيام المتبقية حتى موعد السداد (قد تكون سالبة إن تجاوز الموعد).
        تُعيد None إذا لم يُحدد due_at.
        """
        if not self.due_at:
            return None
        delta = self.due_at - timezone.now()
        return int(delta.total_seconds() // 86400)

    # ======================
    #  ضمان سلامة البيانات
    # ======================

    def clean(self):
        super().clean()

        # المبلغ لا يكون سالبًا
        if self.amount is None:
            self.amount = Decimal("0.00")
        if self.amount < 0:
            raise ValidationError({"amount": "المبلغ لا يمكن أن يكون سالبًا."})

        # إن كانت الفاتورة مرتبطة بمرحلة، يجب أن تتطابق الاتفاقية
        if self.milestone_id and self.agreement_id:
            ms_agreement_id = getattr(self.milestone, "agreement_id", None)
            if ms_agreement_id and ms_agreement_id != self.agreement_id:
                raise ValidationError("الاتفاقية المرتبطة لا تتطابق مع اتفاقية المرحلة.")

        # due_at إن وُجد يجب أن لا يسبق issued_at
        if self.due_at and self.issued_at and self.due_at < self.issued_at:
            raise ValidationError({"due_at": "موعد السداد لا يمكن أن يسبق تاريخ الإصدار."})

        # paid_at إن وُجد يجب أن لا يسبق issued_at
        if self.paid_at and self.issued_at and self.paid_at < self.issued_at:
            raise ValidationError({"paid_at": "تاريخ السداد لا يمكن أن يسبق تاريخ الإصدار."})

    def save(self, *args, **kwargs):
        # توحيد amount إلى دقتين عشريتين بشكل آمن
        if isinstance(self.amount, Decimal):
            self.amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # في حال تم تمرير milestone فقط بدون agreement، اربط الاتفاقية تلقائيًا
        if self.milestone_id and not self.agreement_id:
            self.agreement_id = self.milestone.agreement_id

        # إن كانت الحالة مدفوعة ولم يُحدد paid_at؛ اضبطه الآن
        if self.status == self.Status.PAID and self.paid_at is None:
            self.paid_at = timezone.now()

        # تحقق صلاحية الحقول قبل الحفظ
        self.full_clean(exclude=None)

        return super().save(*args, **kwargs)

    # ======================
    #  واجهة برمجية للدفع
    # ======================

    def mark_paid(
        self,
        *,
        by_user: Optional[object] = None,
        method: str = "",
        ref_code: str = "",
        paid_at=None,
        save: bool = True,
    ):
        """
        يوسم الفاتورة كمدفوعة ويحدّث الحقول ذات الصلة.
        يفضّل استدعاؤها ضمن transaction.atomic() من الفيو.
        """
        if self.status == self.Status.PAID:
            return self  # لا تكرار

        self.status = self.Status.PAID
        self.method = (method or self.method or "")[:50]
        self.ref_code = (ref_code or self.ref_code or "")[:100]
        self.paid_at = paid_at or self.paid_at or timezone.now()

        # إسناد المستخدم الذي نفّذ العملية (إن كان لديك حقل updated_by اختياري)
        if by_user and hasattr(self, "updated_by"):
            setattr(self, "updated_by", by_user)

        if save:
            self.save(update_fields=["status", "method", "ref_code", "paid_at", "updated_at"])

        # ملاحظة: تحديث milestone/agreement/request يتم في view أو signals
        return self

    # ======================
    #  توابع استعلام مساعدة
    # ======================

    @classmethod
    def unpaid_for_agreement(cls, agreement_id: int):
        return cls.objects.for_agreement(agreement_id).unpaid()

    @classmethod
    def all_paid_for_agreement(cls, agreement_id: int) -> bool:
        return not cls.unpaid_for_agreement(agreement_id).exists()

    # ======================
    #  مُساعدات عملية إضافية
    # ======================

    def set_due_in_days(self, days: int = 3, save: bool = True):
        """
        يضبط موعد السداد بعد N أيام من الآن (الافتراضي 3 أيام — متوافق مع SLA).
        """
        self.due_at = timezone.now() + timezone.timedelta(days=max(0, int(days)))
        if save:
            self.save(update_fields=["due_at", "updated_at"])

    @classmethod
    def create_for_milestone(
        cls,
        *,
        milestone,
        amount: Optional[Decimal] = None,
        due_days: int = 3,
        created_by=None,
    ) -> "Invoice":
        """
        ينشئ فاتورة لمرحلة إن لم تكن موجودة. يشتق الاتفاقية والمبلغ تلقائيًا عند الحاجة.
        """
        if milestone is None:
            raise ValidationError("لا يمكن إنشاء فاتورة: المرحلة غير مرفقة.")

        with transaction.atomic():
            inv, created = cls.objects.select_for_update().get_or_create(
                milestone=milestone,
                defaults={
                    "agreement": milestone.agreement,
                    "amount": (
                        amount
                        if amount is not None
                        else getattr(milestone, "amount", None)
                        or (milestone.agreement.total_amount / max(milestone.agreement.milestones.count(), 1))
                    ),
                    "status": cls.Status.UNPAID,
                    "issued_at": timezone.now(),
                    "created_by": created_by if created_by else None,
                },
            )
            # اضبط due_at إن لم تكن محددة
            if not inv.due_at:
                inv.set_due_in_days(days=due_days, save=True)
            return inv
