from __future__ import annotations
from django.conf import settings
from django.db import models
from django.utils import timezone

# ملاحظة: نفترض أن طلباتك في app "marketplace" ونموذجها اسمه Request
# ولو اسم/مسار مختلف عدِّله هنا:
from marketplace.models import Request

class Dispute(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "مفتوح"
        IN_REVIEW = "in_review", "قيد المراجعة"
        RESOLVED = "resolved", "محسوم"
        CANCELED = "canceled", "ملغى"

    class OpenerRole(models.TextChoices):
        CLIENT = "client", "عميل"
        EMPLOYEE = "employee", "موظف"
        ADMIN = "admin", "إداري"

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="disputes")
    # اختياري: إن كانت لديك Milestone في agreements:
    milestone_id = models.IntegerField(null=True, blank=True)  # نضع ID رقمي عام لتجنّب الاعتمادية الصارمة
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opened_disputes")
    opener_role = models.CharField(max_length=16, choices=OpenerRole.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    title = models.CharField(max_length=200)
    reason = models.TextField()  # السبب مختصر/واضح
    details = models.TextField(blank=True)  # تفاصيل إضافية

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resolved_disputes"
    )
    resolved_note = models.TextField(blank=True)
    opened_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    # للحماية المؤسسية: نزاع واحد مفتوح في كل مرة لكل طلب
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request"],
                condition=models.Q(status__in=["open", "in_review"]),
                name="uniq_open_dispute_per_request",
            )
        ]
        ordering = ["-opened_at"]

    def __str__(self) -> str:
        return f"Dispute #{self.pk} on Request #{self.request_id} [{self.status}]"
