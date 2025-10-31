# finance/models.py
from __future__ import annotations
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Invoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "غير مدفوعة"
        PAID = "paid", "مدفوعة"
        CANCELLED = "cancelled", "ملغاة"

    agreement = models.ForeignKey(
        "agreements.Agreement", on_delete=models.CASCADE, related_name="invoices", verbose_name="الاتفاقية"
    )
    milestone = models.ForeignKey(
        "agreements.Milestone", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invoices", verbose_name="الدفعة"
    )

    amount = models.DecimalField("المبلغ", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNPAID)
    issued_at = models.DateTimeField("تاريخ الإصدار", default=timezone.now)
    paid_at = models.DateTimeField("تاريخ السداد", null=True, blank=True)
    method = models.CharField("طريقة السداد", max_length=50, blank=True)  # مثال: حوالة/مدى/فيزا
    ref_code = models.CharField("مرجع العملية", max_length=100, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices_created")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "issued_at"]),
            models.Index(fields=["agreement"]),
        ]
        ordering = ["-issued_at", "-id"]
        verbose_name = "فاتورة"
        verbose_name_plural = "فواتير"

    def __str__(self) -> str:
        return f"Invoice#{self.pk} A{self.agreement_id} — {self.get_status_display()} {self.amount}"

    @property
    def is_unpaid(self) -> bool:
        return self.status == self.Status.UNPAID
