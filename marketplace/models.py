# marketplace/models.py
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.urls import reverse

User = settings.AUTH_USER_MODEL


class Request(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "طلب جديد"
        OFFER_SELECTED = "offer_selected", "تم اختيار عرض"
        AGREEMENT_PENDING = "agreement_pending", "اتفاقية بانتظار الموافقة"
        IN_PROGRESS = "in_progress", "قيد التنفيذ"
        COMPLETED = "completed", "مكتمل"
        DISPUTE = "dispute", "نزاع"
        CANCELLED = "cancelled", "ملغى"

    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name="requests_as_client")
    assigned_employee = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="requests_as_employee", null=True, blank=True
    )

    title = models.CharField("العنوان", max_length=160)
    details = models.TextField("التفاصيل", blank=True)
    estimated_duration_days = models.PositiveIntegerField("مدة تقديرية (أيام)", default=7)
    estimated_price = models.DecimalField("سعر تقريبي", max_digits=12, decimal_places=2, default=0)
    links = models.TextField("روابط مرتبطة (اختياري)", blank=True)

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW)
    has_milestones = models.BooleanField(default=False)
    has_dispute = models.BooleanField(default=False)

    # --- SLA ---
    offer_selected_at = models.DateTimeField("تاريخ اختيار العرض", null=True, blank=True)
    agreement_due_at = models.DateTimeField("موعد استحقاق إرسال الاتفاقية", null=True, blank=True)
    sla_agreement_overdue = models.BooleanField("تجاوز مهلة إنشاء الاتفاقية (تم التنبيه؟)", default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -------------------------
    # صلاحيات/سلامة بيانات أساسية
    # -------------------------
    def clean(self):
        if self.assigned_employee and getattr(self.assigned_employee, "role", None) != "employee":
            raise ValidationError("الإسناد يجب أن يكون إلى مستخدم بدور 'موظف'.")

    @property
    def agreement_overdue(self) -> bool:
        return bool(self.agreement_due_at and timezone.now() > self.agreement_due_at)

    @property
    def selected_offer(self):
        # توافقًا مع أي كود قديم قد يستدعي 'selected'
        try:
            return self.offers.select_related("employee").filter(status=Offer.Status.SELECTED).first()
        except NameError:
            return self.offers.select_related("employee").filter(status="selected").first()

    def mark_offer_selected_now(self, employee):
        """تحديثات موحّدة عند تحديد العرض/الإسناد (يضبط الـ SLA)."""
        self.assigned_employee = employee
        self.status = self.Status.OFFER_SELECTED
        now = timezone.now()
        self.offer_selected_at = now
        self.agreement_due_at = now + timedelta(days=3)
        self.sla_agreement_overdue = False

    # -------------------------
    # دوال المدير العام (admin-only) — تُستدعى من الفيوز
    # -------------------------
    def admin_cancel(self):
        """
        إلغاء الطلب: يفك الإسناد، يوقف الـ SLA، ويضع الحالة 'cancelled'.
        لا يحذف العروض أو الملاحظات (تبقى للأرشفة).
        """
        with transaction.atomic():
            self.assigned_employee = None
            self.status = self.Status.CANCELLED
            self.offer_selected_at = None
            self.agreement_due_at = None
            self.sla_agreement_overdue = False
            self.save(update_fields=[
                "assigned_employee", "status", "offer_selected_at",
                "agreement_due_at", "sla_agreement_overdue", "updated_at"
            ])

    def reset_to_new(self):
        """
        إعادة الطلب إلى حالة NEW:
        - رفض جميع العروض الحالية (نبقيها في السجل للأرشفة).
        - إزالة الإسناد.
        - تصفير الـ SLA.
        - ضبط الحالة NEW.
        """
        # استيراد متأخر لتفادي الحلقة المرجعية داخل الملف
        from .models import Offer
        with transaction.atomic():
            # رفض كل العروض باستثناء المرفوضة أصلاً للحفاظ على الاتساق
            Offer.objects.filter(request=self).exclude(status=Offer.Status.REJECTED)\
                .update(status=Offer.Status.REJECTED)
            # إعادة الضبط
            self.assigned_employee = None
            self.status = self.Status.NEW
            self.offer_selected_at = None
            self.agreement_due_at = None
            self.sla_agreement_overdue = False
            self.save(update_fields=[
                "assigned_employee", "status", "offer_selected_at",
                "agreement_due_at", "sla_agreement_overdue", "updated_at"
            ])

    def reassign_to(self, employee):
        """
        إعادة إسناد قسرية إلى موظف آخر (admin-only).
        لا تغيّر الحالة الجارية (OFFER_SELECTED/IN_PROGRESS/…)، فقط تبدّل الموظف.
        """
        if not employee or getattr(employee, "role", None) != "employee":
            raise ValidationError("لا يمكن الإسناد إلا لمستخدم بدور 'employee'.")
        self.assigned_employee = employee
        self.save(update_fields=["assigned_employee", "updated_at"])

    # -------------------------
    # روابط وتمثيل
    # -------------------------
    def get_absolute_url(self):
        try:
            return reverse("marketplace:request_detail", args=[self.pk])
        except Exception:
            return f"/marketplace/r/{self.pk}/"

    def __str__(self):
        return f"[{self.pk}] {self.title} — {self.get_status_display()}"

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["client"]),
            models.Index(fields=["assigned_employee"]),
            models.Index(fields=["agreement_due_at"]),
        ]
        verbose_name = "طلب"
        verbose_name_plural = "طلبات"


class Offer(models.Model):
    # لإصلاح التوافق مع الإشارات والفيوز: TextChoices + alias قديم
    class Status(models.TextChoices):
        PENDING = "pending", "قيد المراجعة"
        SELECTED = "selected", "العرض المختار"
        REJECTED = "rejected", "مرفوض"
        WITHDRAWN = "withdrawn", "مسحوب"

    STATUS_CHOICES = Status.choices  # توافق مع أي كود قديم يستخدم المتغيّر

    request = models.ForeignKey("marketplace.Request", related_name="offers", on_delete=models.CASCADE)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="offers", on_delete=models.CASCADE)

    proposed_duration_days = models.PositiveIntegerField()
    proposed_price = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    # صلاحيات
    def can_view(self, user):
        if not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(user, "role", "") in ("admin", "manager", "finance"):
            return True
        return user.id in (self.request.client_id, self.employee_id)

    def can_select(self, user):
        return (
            getattr(user, "is_authenticated", False)
            and user.id == self.request.client_id
            and self.status == self.Status.PENDING
            and self.request.status == Request.Status.NEW
        )

    def can_reject(self, user):
        return (
            getattr(user, "is_authenticated", False)
            and user.id == self.request.client_id
            and self.status == self.Status.PENDING
        )

    def __str__(self):
        return f"Offer#{self.pk} R{self.request_id} by {self.employee}"


class Note(models.Model):
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField("نص الملاحظة")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    is_internal = models.BooleanField("رؤية مقيدة (داخلي)", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ملاحظة"
        verbose_name_plural = "ملاحظات"

    def __str__(self):
        return f"Note#{self.pk} R{self.request_id} by {self.author_id}"
