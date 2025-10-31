# accounts/forms.py
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .models import normalize_to_e164

User = get_user_model()


# ---------------------------------------------
# تسجيل الدخول بالبريد الإلكتروني فقط
# ---------------------------------------------
class LoginForm(forms.Form):
    email = forms.EmailField(
        label="البريد الإلكتروني",
        widget=forms.EmailInput(attrs={
            "placeholder": "example@mail.com",
            "autocomplete": "email",
            "class": "input",
        }),
    )
    password = forms.CharField(
        label="كلمة المرور",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password",
            "class": "input",
        }),
    )

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        validate_email(email)
        return email

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        password = cleaned.get("password")

        if email and password:
            user = authenticate(email=email, password=password)
            if not user:
                raise ValidationError("بيانات الدخول غير صحيحة.")
            if not user.is_active:
                raise ValidationError("الحساب غير مفعّل.")
            cleaned["user"] = user
        return cleaned


# ---------------------------------------------
# إنشاء حساب — البريد إلزامي، الجوال اختياري
# ---------------------------------------------
class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(
        label="كلمة المرور",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="تأكيد كلمة المرور",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["email", "phone", "name"]
        labels = {
            "email": "البريد الإلكتروني",
            "phone": "الجوال (اختياري)",
            "name": "الاسم",
        }
        widgets = {
            "email": forms.EmailInput(attrs={"class": "input", "placeholder": "example@mail.com", "autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"class": "input", "placeholder": "05… أو 00966… أو +966…", "autocomplete": "tel"}),
            "name": forms.TextInput(attrs={"class": "input", "placeholder": "اسمك الكامل"}),
        }

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        validate_email(email)
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("هذا البريد مستخدم مسبقًا.")
        return email

    def clean_phone(self) -> str | None:
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return None
        try:
            return normalize_to_e164(phone)
        except ValidationError as e:
            raise ValidationError(e.messages[0] if e.messages else "رقم جوال غير صالح.")

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("كلمتا المرور غير متطابقتين.")
        return cleaned

    def save(self, commit: bool = True):
        # لا نستخدم تعبيرًا نوعيًا على user هنا لتجنّب تحذير Pylance
        user = super().save(commit=False)
        user.email = (self.cleaned_data["email"] or "").strip().lower()
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


# ---------------------------------------------
# تعديل الملف الشخصي
# ---------------------------------------------
class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email", "name", "phone"]
        labels = {
            "email": "البريد الإلكتروني",
            "name": "الاسم",
            "phone": "الجوال",
        }
        widgets = {
            "email": forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
            "name": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input", "placeholder": "05… أو +966…", "autocomplete": "tel"}),
        }

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        validate_email(email)
        qs = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("هذا البريد مستخدم من حساب آخر.")
        return email

    def clean_phone(self) -> str | None:
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return None
        try:
            return normalize_to_e164(phone)
        except ValidationError as e:
            raise ValidationError(e.messages[0] if e.messages else "رقم جوال غير صالح.")
