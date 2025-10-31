from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.core.exceptions import ValidationError

User = get_user_model()

class LoginForm(forms.Form):
    username = forms.CharField(label="البريد أو الجوال", widget=forms.TextInput(attrs={
        "placeholder": "example@mail.com أو +9665XXXXXXXX أو 05XXXXXXXX",
        "class": "input"
    }))
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "input"}))

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get("username")
        password = cleaned.get("password")
        if username and password:
            user = authenticate(username=username, password=password)
            if not user:
                raise ValidationError("بيانات الدخول غير صحيحة.")
            if not user.is_active:
                raise ValidationError("الحساب غير مفعّل.")
            cleaned["user"] = user
        return cleaned

class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "input"}))
    password2 = forms.CharField(label="تأكيد كلمة المرور", widget=forms.PasswordInput(attrs={"class": "input"}))

    class Meta:
        model = User
        fields = ["email", "phone", "name"]
        labels = {
            "email": "البريد الإلكتروني",
            "phone": "الجوال (اختياري)",
            "name": "الاسم",
        }
        widgets = {
            "email": forms.EmailInput(attrs={"class": "input", "placeholder": "example@mail.com"}),
            "phone": forms.TextInput(attrs={"class": "input", "placeholder": "05… أو 00966… أو +966…"}),
            "name": forms.TextInput(attrs={"class": "input", "placeholder": "اسمك الكامل"}),
        }

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("كلمتا المرور غير متطابقتين.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["name", "phone"]
        labels = {"name": "الاسم", "phone": "الجوال"}
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input", "placeholder": "05… أو +966…"}),
        }
