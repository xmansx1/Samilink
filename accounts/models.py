# accounts/models.py
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


# ---------------------------------------------
# أدوات تطبيع الجوال إلى E.164 بدون مكتبات خارجية
# ---------------------------------------------
E164_VALIDATOR = RegexValidator(
    regex=r"^\+[1-9]\d{7,14}$",
    message="رقم دولي غير صحيح (E.164). مثال: +9665XXXXXXXX",
)

def _digits_only(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())

def normalize_to_e164(raw_phone: str, default_cc: str = "966") -> str | None:
    """
    يحوّل مدخل الهاتف إلى E.164:
    - يقبل: +966..., 00966..., 966..., 05..., 5..., وأرقام فقط.
    - default_cc: رمز الدولة الافتراضي (بدون +)، افتراضي 966 (السعودية).
    - يعيد None إذا كان الإدخال فارغًا/None.
    - يرفع ValidationError إن تعذّر التطبيع إلى رقم دولي صحيح.
    قواعد مبسطة:
      * يبدأ بـ + : نتحقق فقط من E.164.
      * يبدأ بـ 00 : نستبدلها بـ + ثم نتحقق.
      * يبدأ بـ default_cc مباشرة: نضيف +.
      * يبدأ بـ 0 متبوعًا برقم غير صفري: نزيل الصفر المبدئي ونضيف +default_cc.
      * يبدأ برقم غير صفري ولم يذكر +/00/cc: نضيف +default_cc مباشرة.
    """
    if not raw_phone:
        return None

    s = str(raw_phone).strip()
    # حالة يبدأ بـ +
    if s.startswith("+"):
        E164_VALIDATOR(s)  # يرفع ValidationError عند الخطأ
        return s

    # حالة يبدأ بـ 00 (تحويل إلى +)
    if s.startswith("00"):
        candidate = "+" + _digits_only(s[2:])
        E164_VALIDATOR(candidate)
        return candidate

    # أرقام فقط (مع إزالة أي فواصل/مسافات/رموز)
    digits = _digits_only(s)
    if not digits:
        raise ValidationError("رقم جوال غير صالح.")

    # إذا بدأ بالـ CC الافتراضي (مثل 966...): أضف +
    if digits.startswith(default_cc):
        candidate = f"+{digits}"
        E164_VALIDATOR(candidate)
        return candidate

    # إذا بدأ بـ 0 يليه رقم (غالبًا صيغة محلية: 05...): نحذف 0 ونضيف CC
    if digits.startswith("0"):
        local = digits[1:]
        candidate = f"+{default_cc}{local}"
        E164_VALIDATOR(candidate)
        return candidate

    # خلاف ذلك: اعتبره رقمًا محليًا بدون صفر بادئ — أضف CC
    candidate = f"+{default_cc}{digits}"
    E164_VALIDATOR(candidate)
    return candidate


# ---------------------------------------------
# مدير المستخدم — يعتمد البريد فقط كهوية
# ---------------------------------------------
class UserManager(BaseUserManager):
    use_in_migrations = True

    def _normalize_email_ci(self, email: str) -> str:
        # normalize_email تُصلح الدومين؛ ونحوّل الكل لحروف صغيرة لثبات المقارنة
        return (self.normalize_email(email) or "").strip().lower()

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("البريد الإلكتروني مطلوب")
        email = self._normalize_email_ci(email)

        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.CLIENT)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("superuser يجب أن يكون is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("superuser يجب أن يكون is_superuser=True")
        return self._create_user(email, password, **extra_fields)


# ---------------------------------------------
# نموذج المستخدم — البريد هو USERNAME_FIELD
# ---------------------------------------------
class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", "مدير عام"
        FINANCE = "finance", "مالية"
        EMPLOYEE = "employee", "موظف"
        CLIENT = "client", "عميل"

    # نستخدم البريد كهوية وحيدة للدخول
    email = models.EmailField("البريد الإلكتروني", unique=True, db_index=True)

    # الجوال اختياري؛ عند وجوده يُحفظ بصيغة دولية E.164
    phone = models.CharField(
        "الجوال",
        max_length=16,  # + ثم حتى 15 رقم
        blank=True,
        null=True,
        help_text="أدخل أي صيغة (05 أو 00966 أو 966 أو +966). سيُحفظ دوليًا تلقائيًا.",
        validators=[RegexValidator(r"^[\d\+\s\-\(\)]{3,}$", "صيغة رقم غير صالحة.")],
    )

    name = models.CharField("الاسم", max_length=150, blank=True)

    role = models.CharField("الدور", max_length=16, choices=Role.choices, default=Role.CLIENT)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "مستخدمون"
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["email"]),
            models.Index(fields=["phone"]),
        ]
        # ضمان تفرّد البريد بدون حساسية حالة الأحرف (يعمل بكفاءة على PostgreSQL)
        constraints = [
            models.UniqueConstraint(
                Lower("email"), name="uniq_user_email_ci"
            ),
        ]

    # -----------------------
    # تطبيع قبل الحفظ
    # -----------------------
    def clean(self):
        """
        - تطبيع البريد إلى lower/strip.
        - تطبيع رقم الجوال إلى E.164 قبل الحفظ.
        تُستدعى من admin/forms أو عبر full_clean().
        """
        super().clean()
        if self.email:
            self.email = (self.email or "").strip().lower()

        default_cc = getattr(settings, "PHONE_DEFAULT_COUNTRY_CODE", "966")  # 966 افتراضياً (السعودية)
        if self.phone:
            normalized = normalize_to_e164(self.phone, default_cc=default_cc)
            self.phone = normalized  # يخزن بصيغة دولية موحدة

    def save(self, *args, **kwargs):
        # نضمن التطبيع حتى عند حفظ بدون استدعاء full_clean()
        if self.email:
            self.email = (self.email or "").strip().lower()

        default_cc = getattr(settings, "PHONE_DEFAULT_COUNTRY_CODE", "966")
        if self.phone:
            self.phone = normalize_to_e164(self.phone, default_cc=default_cc)

        return super().save(*args, **kwargs)

    # -----------------------
    # خصائص/مساعدات
    # -----------------------
    @property
    def phone_e164(self) -> str | None:
        """يعيد رقم الجوال بصيغة دولية (كما يُخزن)."""
        return self.phone or None

    @property
    def whatsapp_link(self) -> str | None:
        """
        رابط واتساب مباشر آمن (wa.me) للرقم المخزن دوليًا.
        لا يضيف نصًا. يمكنك لاحقًا إضافة ?text=... مع urlencode.
        """
        if not self.phone:
            return None
        return f"https://wa.me/{self.phone[1:]}" if self.phone.startswith("+") else f"https://wa.me/{self.phone}"

    def get_full_name(self) -> str:
        return self.name or self.email

    def get_short_name(self) -> str:
        return (self.name or self.email).split(" ")[0]

    def __str__(self):
        return self.name or self.email
