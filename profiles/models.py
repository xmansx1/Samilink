from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

User = settings.AUTH_USER_MODEL

def employee_upload(instance, filename):
    return f"employees/{instance.user_id}/{timezone.now():%Y%m%d%H%M%S}_{filename}"

class EmployeeProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee_profile")
    slug = models.SlugField(unique=True, max_length=180, editable=False)

    title = models.CharField("المسمى/اللقب المهني", max_length=120, blank=True)
    specialty = models.CharField("التخصص", max_length=120, blank=True)
    skills = models.CharField("مهارات (مفصولة بفواصل)", max_length=400, blank=True,
                              help_text="مثال: Django, REST, Tailwind")

    bio = models.TextField("نبذة مختصرة", blank=True)
    photo = models.ImageField("صورة", upload_to=employee_upload, blank=True, null=True)

    hourly_rate = models.DecimalField("سعر الساعة (اختياري)", max_digits=9, decimal_places=2,
                                      blank=True, null=True)
    rating = models.DecimalField("تقييم", max_digits=3, decimal_places=1,
                                 validators=[MinValueValidator(0), MaxValueValidator(5)],
                                 default=0)
    public_visible = models.BooleanField("ظهور عام", default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "بروفايل موظف"
        verbose_name_plural = "بروفايلات الموظفين"
        indexes = [
            models.Index(fields=["public_visible", "rating"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return f"{self.user.name or self.user.email} — {self.specialty or 'موظف'}"

    def save(self, *args, **kwargs):
        # توليد slug مستقر من اسم المستخدم أو بريده
        base = (self.user.name or self.user.email.split("@")[0]).strip()
        base = slugify(base, allow_unicode=True)
        if not self.slug or not self.pk:
            candidate = base or f"emp-{self.user_id}"
            slug = candidate
            i = 2
            while EmployeeProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{candidate}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    # عرض جميل للمهارات
    @property
    def skills_list(self):
        return [s.strip() for s in (self.skills or "").split(",") if s.strip()]

    # رابط واتساب آمن عبر الوسيط
    @property
    def whatsapp_proxy_url(self):
        # لا نظهر الرقم مباشرة — نستخدم Endpoint وسيط
        return f"/employees/w/emp/{self.user_id}/"
