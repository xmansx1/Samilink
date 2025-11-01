from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.html import strip_tags
from django.urls import reverse

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
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
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

    # ============ تحقّقات عامة ============
    def clean(self) -> None:
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
                raise ValidationError(
                    f"مجموع مبالغ الدفعات ({sum_amounts}) لا يساوي إجمالي الاتفاقية ({self.total_amount})."
                )

        # تنقية نصوص حرّة
        if self.text:
            self.text = strip_tags(self.text).strip()
        if self.rejection_reason:
            self.rejection_reason = strip_tags(self.rejection_reason).strip()

        # تنعيم المبلغ (حماية ضد قيم ثلاثية الكسور)
        if self.total_amount is not None:
            self.total_amount = Decimal(self.total_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # =========== خصائص/مساعدات للعرض ===========
    def __str__(self) -> str:  # pragma: no cover
        return f"Agreement#{self.pk} R{self.request_id} — {self.get_status_display()}"

    def get_absolute_url(self) -> str:
        # عدّل الاسم/المسار حسب مشروعك إن لزم
        return reverse("agreements:agreement_detail", kwargs={"pk": self.pk})

    def get_day_name_ar(self) -> str:
        dt = getattr(self, "created_at", None) or timezone.now()
        return _AR_WEEKDAYS[dt.weekday()]

    def get_date_text_ar(self) -> str:
        dt = getattr(self, "created_at", None) or timezone.now()
        return f"{dt.day} {_AR_MONTHS[dt.month]} {dt.year}"

    def get_intro_paragraph_ar(self) -> str:
        """
        يُولّد نص الجزء الأول كما في التصميم المعتمد.
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
            obj: Any = getattr(req, attr, None)
            if obj:
                if hasattr(obj, "get_full_name"):
                    try:
                        return obj.get_full_name() or str(obj)
                    except Exception:  # pragma: no cover
                        return str(obj)
                name = getattr(obj, "name", None) or getattr(obj, "username", None) or getattr(obj, "email", None)
                return str(name or obj)
        return "—"

    @property
    def employee_display(self) -> str:
        emp = getattr(self, "employee", None)
        if not emp:
            return "—"
        if hasattr(emp, "get_full_name"):
            try:
                return emp.get_full_name() or str(emp)
            except Exception:  # pragma: no cover
                return str(emp)
        return str(getattr(emp, "name", None) or getattr(emp, "email", None) or emp)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["employee"]),
        ]
        constraints = [
            # ضمان عدم السالب في الإجمالي على مستوى DB (حيثما يدعم الـ backend)
            models.CheckConstraint(check=models.Q(total_amount__gte=0), name="agreement_total_amount_gte_0"),
            models.CheckConstraint(check=models.Q(duration_days__gte=1), name="agreement_duration_days_gte_1"),
        ]
        verbose_name = "اتفاقية"
        verbose_name_plural = "اتفاقيات"


# agreements/models.py  (أو الملف المناسب لديك)

from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

# استورد Agreement من مكانه الصحيح
# from .agreement_models import Agreement
# أو إن كان في نفس الملف:
# from .models import Agreement


class Milestone(models.Model):
    """
    دفعات/مراحل الاتفاقية (Transition أحادي المصدر عبر status):
    PENDING → DELIVERED → (APPROVED | REJECTED) → PAID
    - إعادة التسليم بعد الرفض: REJECTED → DELIVERED
    - لا يُسمح بالتسليم/الرفض/الاعتماد بعد السداد، ولا التسليم بعد الاعتماد.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "قيد التنفيذ"
        DELIVERED = "delivered", "تم التسليم"
        APPROVED = "approved", "معتمدة"
        REJECTED = "rejected", "مرفوضة"
        PAID = "paid", "مدفوعة"

    agreement = models.ForeignKey(
        "agreements.Agreement",  # عدّل إلى المسار الفعلي إن اختلف
        on_delete=models.CASCADE,
        related_name="milestones",
        verbose_name="الاتفاقية",
    )
    title = models.CharField("عنوان الدفعة/المرحلة", max_length=160)
    amount = models.DecimalField("المبلغ (ريال)", max_digits=12, decimal_places=2)
    order = models.PositiveIntegerField("الترتيب", default=1)
    due_days = models.PositiveIntegerField("مستحق بعد (أيام) من البداية", null=True, blank=True)

    # الحالة المعتمدة
    status = models.CharField("الحالة", max_length=12, choices=Status.choices, default=Status.PENDING)

    # آثار/تواقيت
    delivered_at = models.DateTimeField("وقت التسليم", null=True, blank=True)
    delivered_note = models.TextField("ملاحظة التسليم", blank=True)

    approved_at = models.DateTimeField("وقت الاعتماد", null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_milestones",
        verbose_name="اعتمدت بواسطة",
    )
    rejected_reason = models.TextField("سبب الرفض", blank=True)

    paid_at = models.DateTimeField("وقت السداد", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["agreement", "order"]),
            models.Index(fields=["status"]),
            models.Index(fields=["delivered_at"]),
            models.Index(fields=["approved_at"]),
            models.Index(fields=["paid_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["agreement", "order"], name="uniq_milestone_order_per_agreement"),
            models.CheckConstraint(check=models.Q(amount__gte=0), name="milestone_amount_gte_0"),
            models.CheckConstraint(check=models.Q(order__gte=1), name="milestone_order_gte_1"),
        ]
        verbose_name = "دفعة"
        verbose_name_plural = "دفعات"

    # -------- تحقّق/تطبيع --------
    def clean(self) -> None:
        if self.amount is None or self.amount < 0:
            raise ValidationError("مبلغ الدفعة يجب أن يكون رقمًا موجبًا أو صفرًا.")
        if self.order < 1:
            raise ValidationError("ترتيب الدفعة يجب أن يكون 1 أو أكبر.")
        self.amount = Decimal(self.amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # -------- روابط --------
    def get_absolute_url(self) -> str:
        # عدّل الاسم/المسار حسب مشروعك إن لزم
        return reverse("agreements:milestone_detail", kwargs={"pk": self.pk})

    # -------- خصائص مشتقة (قراءة فقط) --------
    @property
    def is_delivered(self) -> bool:
        return self.status == self.Status.DELIVERED

    @is_delivered.setter
    def is_delivered(self, value: bool) -> None:
        """
        توافق خلفي: يسمح لكود قديم بتعيين ms.is_delivered = True/False.
        - True  → mark_delivered() (مع الحفاظ على note الحالية إن وُجدت).
        - False → يرجع إلى PENDING إن لم تكن مدفوعة.
        """
        if bool(value):
            self.mark_delivered(note=(self.delivered_note or "").strip())
        else:
            if self.is_paid:
                raise ValidationError("لا يمكن إلغاء التسليم بعد السداد.")
            self.status = self.Status.PENDING
            self.delivered_at = None
            # لا نمسح delivered_note (تاريخيًا مفيدة)، ونمسح سبب الرفض
            self.rejected_reason = ""
            self.save(update_fields=["status", "delivered_at", "rejected_reason"])

    @property
    def is_pending_review(self) -> bool:
        # تعتبر "بانتظار المراجعة" عندما تكون المرحلة في حالة DELIVERED (قبل اعتماد/رفض)
        return self.status == self.Status.DELIVERED

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status == self.Status.REJECTED

    @property
    def is_paid(self) -> bool:
        return self.status == self.Status.PAID

    # -------- أفعال الحالة (Transitions) --------
    def mark_delivered(self, note: str = "") -> None:
        """
        تسليم/إعادة تسليم من الموظف:
        - يمنع لو الحالة APPROVED/PAID.
        - يزيل أي رفض سابق، ويحدّث وقت وملاحظة التسليم.
        - النتيجة: DELIVERED (بانتظار مراجعة العميل).
        """
        if self.is_approved or self.is_paid:
            raise ValidationError("لا يمكن تسليم مرحلة معتمَدة أو مدفوعة.")
        self.status = self.Status.DELIVERED
        self.delivered_at = timezone.now()
        self.delivered_note = (note or "").strip()
        # إعادة فتح المراجعة: تصفير الرفض/الاعتماد
        self.rejected_reason = ""
        self.approved_at = None
        self.approved_by = None
        self.save(update_fields=[
            "status", "delivered_at", "delivered_note",
            "rejected_reason", "approved_at", "approved_by"
        ])

    def approve(self, user) -> None:
        """
        اعتماد العميل (أو من يملك الصلاحية):
        - مسموح فقط عندما تكون DELIVERED.
        - يمنع إن كانت PAID.
        - النتيجة: APPROVED.
        """
        if self.is_paid:
            raise ValidationError("لا يمكن اعتماد مرحلة مدفوعة.")
        if not self.is_pending_review:
            raise ValidationError("لا يمكن الاعتماد قبل التسليم.")
        self.status = self.Status.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.rejected_reason = ""
        self.save(update_fields=["status", "approved_at", "approved_by", "rejected_reason"])

    def reject(self, reason: str) -> None:
        """
        رفض العميل:
        - مسموح فقط عندما تكون DELIVERED (بانتظار المراجعة).
        - يمنع إن كانت PAID.
        - النتيجة: REJECTED (مع سبب واضح).
        """
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise ValidationError("سبب الرفض قصير جدًا.")
        if self.is_paid:
            raise ValidationError("لا يمكن رفض مرحلة مدفوعة.")
        if not self.is_pending_review:
            raise ValidationError("لا يمكن الرفض قبل التسليم.")
        self.status = self.Status.REJECTED
        # لا نعدّل delivered_at/note (تبقى محفوظة كأثر)
        self.approved_at = None
        self.approved_by = None
        self.rejected_reason = reason
        self.save(update_fields=["status", "approved_at", "approved_by", "rejected_reason"])

    def mark_paid(self) -> None:
        """
        تعليم المرحلة كمدفوعة (مالية):
        - مسموح فقط عندما تكون APPROVED.
        """
        if not self.is_approved:
            raise ValidationError("لا يمكن السداد قبل اعتماد المرحلة.")
        self.status = self.Status.PAID
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "paid_at"])

    def __str__(self) -> str:  # pragma: no cover
        return f"Milestone#{self.pk} A{self.agreement_id} — {self.title} ({self.order})"


class AgreementClause(models.Model):
    """
    بند اتفاقية قابل لإعادة الاستخدام. يُدار من الأدمن.
    """
    key = models.SlugField("المعرّف الفريد", unique=True, help_text="معرف فريد (بالإنجليزية) للبند")
    title = models.CharField("عنوان البند", max_length=200)
    body = models.TextField("نص البند")
    is_active = models.BooleanField("مفعل؟", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "بند اتفاقية"
        verbose_name_plural = "بنود الاتفاقية"
        ordering = ["title"]

    def __str__(self) -> str:  # pragma: no cover
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

    def clean(self) -> None:
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

    def __str__(self) -> str:  # pragma: no cover
        if self.clause:
            return f"[{self.position}] {self.clause.title}"
        return f"[{self.position}] بند مخصص: {self.custom_text[:30]}..."

    @property
    def display_text(self) -> str:
        return self.clause.body if self.clause else (self.custom_text or "")
