# accounts/admin.py
from __future__ import annotations

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.hashers import make_password
from django.utils.translation import gettext_lazy as _
from .models import User


# ============================
# Admin Forms (Create / Change)
# ============================
class EmailUserCreationForm(forms.ModelForm):
    """
    نموذج إنشاء مستخدم عبر الـ Admin يعتمد البريد فقط.
    """
    password1 = forms.CharField(label=_("كلمة المرور"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("تأكيد كلمة المرور"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "name", "phone", "role", "is_active", "is_staff")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("هذا البريد مستخدم مسبقًا."))
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("كلمتا المرور غير متطابقتين."))
        return cleaned

    def save(self, commit: bool = True):
        user: User = super().save(commit=False)
        user.email = (self.cleaned_data["email"] or "").strip().lower()
        user.password = make_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class EmailUserChangeForm(forms.ModelForm):
    """
    نموذج تعديل مستخدم عبر الـ Admin.
    كلمة المرور تُعرض كحقل للقراءة فقط؛ استخدم "تغيير كلمة المرور" القياسي عند الحاجة.
    """
    password = forms.CharField(
        label=_("كلمة المرور"),
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text=_("اتركها فارغة إن لم ترغب بتغييرها من هنا."),
    )

    class Meta:
        model = User
        fields = ("email", "name", "phone", "role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("هذا البريد مستخدم من حساب آخر."))
        return email

    def save(self, commit: bool = True):
        user: User = super().save(commit=False)
        pwd = self.cleaned_data.get("password")
        if pwd:
            user.password = make_password(pwd)
        if commit:
            user.save()
            # حفظ العلاقات many-to-many بعد الحفظ
            self.save_m2m()
        return user


# ============
# Admin Config
# ============
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    إدارة مستخدم بالبريد فقط (لا يوجد username).
    """
    add_form = EmailUserCreationForm
    form = EmailUserChangeForm
    model = User

    ordering = ("-date_joined",)
    date_hierarchy = "date_joined"

    list_display = ("email", "name", "phone", "role", "is_active", "is_staff", "date_joined", "last_login")
    list_filter = ("role", "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "name", "phone")

    readonly_fields = ("last_login", "date_joined")

    fieldsets = (
        (_("المعلومات الأساسية"), {"fields": ("email", "name", "phone", "password")}),
        (_("الأذونات"), {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("تواريخ"), {"fields": ("last_login", "date_joined")}),
    )

    # شاشة الإضافة
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "name", "phone", "role", "is_active", "is_staff", "password1", "password2"),
        }),
    )

    # إزالة أي إشارات لحقل username الافتراضي
    filter_horizontal = ("groups", "user_permissions")

    def get_queryset(self, request):
        # تحسينات طفيفة: prefetch للأذونات/المجموعات
        qs = super().get_queryset(request)
        return qs.select_related().prefetch_related("groups", "user_permissions")
