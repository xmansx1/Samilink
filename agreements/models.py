# agreements/models.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.html import strip_tags

User = settings.AUTH_USER_MODEL

# ==============================
# ثوابت عربية لعرض اليوم/التاريخ
# ==============================
_AR_WEEKDAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

_AR_MONTHS = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل",
    5: "مايو", 6: "يونيو", 7: "يوليو", 8: "أغسطس",
    9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}


class Agreement(models.Model):
    """
    اتفاقية مرتبطة بطلب واحد (عقد أحادي لكل طلب).
    تُنشأ عادةً بواسطة الموظف المسند، وتُرسل للعميل للموافقة/الرفض.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        PENDING = "pending", "بانتظار موافقة العميل"
        ACCEPTED = "accepted", "تمت الموافقة"
        REJECTED = "rejected", "مرفوضة"

    # اتفاقية لكل طلب
    request = models.OneToOneField(
        "marketplace.Request",
        on_delete=models.CASCADE,
        related_name="agreement",
        verbose_name="الطلب",
    )
    # الموظف (عادةً = assigned_employee على الطلب/العرض)
    employee = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="agreements_as_employee",
        verbose_name="الموظف",
    )

    # معلومات النص/العنوان
    title = models.CharField("عنوان الاتفاقية", max_length=200)
    text = models.TextField("نص الاتفاقية", blank=True)

    # الحقول الجوهرية (تُقفل من الواجهة بعد الإنشاء)
    duration_days = models.PositiveIntegerField("المدة (أيام)", default=7)
    total_amount = models.DecimalField(
        "الإجمالي (ريال)", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    # الحالة + سبب الرفض
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    rejection_reason = models.TextField("سبب الرفض (إن وُجد)", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ============
    # تحقّقات عامة
    # ============
    def clean(self):
        # دور الموظف (اختياري لو عندك role على المستخدم)
        role = getattr(self.employee, "role", None)
        if role and role not in {"employee", "admin"}:
            raise ValidationError("يجب أن يكون الموظف بدور 'employee' أو 'admin'.")

        # التطابق مع الموظف المسند على الطلب (إن وُجد)
        assigned = getattr(self.request, "assigned_employee_id", None)
        if assigned and assigned != self.employee_id:
            raise ValidationError("الموظف المحدَّد في الاتفاقية يجب أن يطابق الموظف المُسنَد على الطلب.")

        if self.duration_days < 1:
            raise ValidationError("المدة يجب أن تكون رقمًا موجبًا.")

        if self.total_amount < 0:
            raise ValidationError("الإجمالي لا يمكن أن يكون سالبًا.")

        # مجموع الدفعات = إجمالي الاتفاقية (لو فيه دفعات)
        ms = list(self.milestones.all()) if self.pk else []
        if ms:
            sum_amounts = sum((m.amount or Decimal("0.00")) for m in ms)
            if (sum_amounts - self.total_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != Decimal("0.00"):
                raise ValidationError(f"مجموع مبالغ الدفعات ({sum_amounts}) لا يساوي إجمالي الاتفاقية ({self.total_amount}).")

        # تنقية نصوص حرّة
        if self.text:
            self.text = strip_tags(self.text).strip()
        if self.rejection_reason:
            self.rejection_reason = strip_tags(self.rejection_reason).strip()

    # ===========
    # خصائص/مساعدات للعرض
    # ===========
    def __str__(self):
        return f"Agreement#{self.pk} R{self.request_id} — {self.get_status_display()}"

    def get_day_name_ar(self) -> str:
        dt = getattr(self, "created_at", None) or timezone.now()
        return _AR_WEEKDAYS[dt.weekday()]

    def get_date_text_ar(self) -> str:
        dt = getattr(self, "created_at", None) or timezone.now()
        return f"{dt.day} {_AR_MONTHS[dt.month]} {dt.year}"

    def get_intro_paragraph_ar(self) -> str:
        """
        يُولّد نص الجزء الأول كما في التصميم المعتمد:
        - اليوم/التاريخ بالعربية
        - العميل/الموظف
        - عنوان الطلب/الاتفاقية
        - المبلغ والمدة
        """
        client = self.client_display
        employee = self.employee_display
        day_name = self.get_day_name_ar()
        date_text = self.get_date_text_ar()
        title = self.title or (getattr(self.request, "title", "") or "الاتفاق")
        return (
            f"أنه في يوم {day_name} الموافق {date_text}، "
            f"اتفق الطرف الأول (العميل) {client} مع الطرف الثاني (الموظف) {employee} "
            f"على تنفيذ “{title}” بمبلغ {self.total_amount} ر.س "
            f"ومدة تنفيذ {self.duration_days} يومًا."
        )

    @property
    def client_display(self) -> str:
        """
        اسم العميل للعرض فقط — يحاول جلبه من خصائص شائعة على الطلب.
        """
        req = self.request
        for attr in ("client", "customer", "user", "owner", "created_by"):
            obj = getattr(req, attr, None)
            if obj:
                # إن وُجد get_full_name استخدمه، وإلا حول الكائن لنص
                return getattr(obj, "get_full_name", lambda: str(obj))()
        return "—"

    @property
    def employee_display(self) -> str:
        emp = getattr(self, "employee", None)
        if not emp:
            return "—"
        return getattr(emp, "get_full_name", lambda: str(emp))()

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["employee"]),
        ]
        verbose_name = "اتفاقية"
        verbose_name_plural = "اتفاقيات"


class Milestone(models.Model):
    """
    دفعات/مراحل الاتفاقية.
    """
    agreement = models.ForeignKey(
        Agreement, on_delete=models.CASCADE, related_name="milestones", verbose_name="الاتفاقية"
    )
    title = models.CharField("عنوان الدفعة/المرحلة", max_length=160)
    amount = models.DecimalField("المبلغ (ريال)", max_digits=12, decimal_places=2)
    order = models.PositiveIntegerField("الترتيب", default=1)
    due_days = models.PositiveIntegerField("مستحق بعد (أيام) من البداية", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["agreement", "order"])]
        constraints = [
            models.UniqueConstraint(
                fields=["agreement", "order"], name="uniq_milestone_order_per_agreement"
            ),
        ]
        verbose_name = "دفعة"
        verbose_name_plural = "دفعات"

    def clean(self):
        if self.amount is None or self.amount < 0:
            raise ValidationError("مبلغ الدفعة يجب أن يكون رقمًا موجبًا أو صفرًا.")
        if self.order < 1:
            raise ValidationError("ترتيب الدفعة يجب أن يكون 1 أو أكبر.")

    def __str__(self):
        return f"Milestone#{self.pk} A{self.agreement_id} — {self.title} ({self.order})"


class AgreementClause(models.Model):
    """
    بند اتفاقية قابل لإعادة الاستخدام. يُدار من الأدمن.
    """
    key = models.SlugField("المعرف", unique=True, help_text="معرف فريد (بالإنجليزية) للبند")
    title = models.CharField("عنوان البند", max_length=200)
    body = models.TextField("نص البند")
    is_active = models.BooleanField("مفعل؟", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "بند اتفاقية"
        verbose_name_plural = "بنود الاتفاقية"
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} ({'مفعل' if self.is_active else 'موقوف'})"


class AgreementClauseItem(models.Model):
    """
    عنصر بند داخل اتفاقية معيّنة:
      - إما يشير إلى بند جاهز AgreementClause
      - أو يحمل نصًا مخصصًا custom_text
    """
    agreement = models.ForeignKey(
        "agreements.Agreement",
        on_delete=models.CASCADE,
        related_name="clause_items",
        verbose_name="الاتفاقية",
    )
    clause = models.ForeignKey(
        AgreementClause,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="البند الجاهز",
    )
    custom_text = models.TextField("نص مخصص", blank=True)
    position = models.PositiveIntegerField("الترتيب", default=1)

    class Meta:
        verbose_name = "بند ضمن الاتفاقية"
        verbose_name_plural = "بنود الاتفاقية المختارة"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["agreement", "position"],
                name="uniq_clauseitem_position_per_agreement",
            ),
        ]

    def clean(self):
        # يجب وجود بند جاهز أو نص مخصص
        if not self.clause and not (self.custom_text or "").strip():
            raise ValidationError("يجب تحديد بند جاهز أو كتابة نص مخصص.")

        # تنقية النص المخصص + حد أقصى
        if self.custom_text:
            cleaned = strip_tags(self.custom_text).strip()
            if len(cleaned) > 2000:
                raise ValidationError("النص المخصص طويل جدًا (أقصى 2000 حرف).")
            self.custom_text = cleaned

        if self.position < 1:
            raise ValidationError("ترتيب البند يجب أن يكون 1 أو أكبر.")

    def __str__(self):
        if self.clause:
            return f"[{self.position}] {self.clause.title}"
        return f"[{self.position}] بند مخصص: {self.custom_text[:30]}..."

    @property
    def display_text(self) -> str:
        return self.clause.body if self.clause else (self.custom_text or "")
