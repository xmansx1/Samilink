from django.db import models
from django.conf import settings
from django.urls import reverse
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class Notification(models.Model):
    """تنبيه داخلي بسيط قابل للربط بأي كيان (اختياري)."""
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    # فاعل الإجراء (اختياري)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="actor_notifications"
    )
    # نصوص التنبيه
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=512, blank=True)  # رابط اختياري يفتح له التنبيه (مثلاً تفاصيل الطلب)

    # ربط عام اختياري بأي Model
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey('content_type', 'object_id')

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient} → {self.title}"

    def get_absolute_url(self):
        return self.url or "#"
