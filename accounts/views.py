# accounts/views.py
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView, CreateView, TemplateView, UpdateView

from .forms import LoginForm, RegisterForm, ProfileUpdateForm


# ---------------------------------------------
# أداة صغيرة لتوجيه آمن يحترم next داخل نفس المضيف فقط
# ---------------------------------------------
def _safe_next(request, fallback_url: str) -> str:
    next_url = request.GET.get("next") or request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=getattr(settings, "SECURE_SSL_REDIRECT", False),
    ):
        return next_url
    return fallback_url


class LoginPageView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("website:home")

    def dispatch(self, request, *args, **kwargs):
        # لو المستخدم مسجّل دخول بالفعل، وجّهه مباشرة
        if request.user.is_authenticated:
            return redirect(_safe_next(request, self.get_success_url()))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.cleaned_data["user"]  # من LoginForm (email-only authenticate)
        login(self.request, user)
        messages.success(self.request, "تم تسجيل الدخول بنجاح.")
        return redirect(_safe_next(self.request, self.get_success_url()))

    def form_invalid(self, form):
        # رسائل واضحة عند الفشل
        messages.error(self.request, "تعذّر تسجيل الدخول. تأكد من البريد وكلمة المرور.")
        return super().form_invalid(form)


class LogoutView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/logout.html"

    def get(self, request, *args, **kwargs):
        logout(request)
        messages.info(request, "تم تسجيل الخروج.")
        return redirect("accounts:login")


class RegisterView(CreateView):
    template_name = "accounts/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("accounts:login")

    def form_valid(self, form):
        resp = super().form_valid(form)
        messages.success(self.request, "تم إنشاء الحساب. يمكنك تسجيل الدخول الآن.")
        return resp

    def form_invalid(self, form):
        messages.error(self.request, "تعذّر إنشاء الحساب. يرجى تصحيح الأخطاء بالأسفل.")
        return super().form_invalid(form)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"


class ProfileEditView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile_edit.html"
    form_class = ProfileUpdateForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "تم تحديث ملفك الشخصي.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "تعذّر تحديث الملف الشخصي. يرجى مراجعة الحقول.")
        return render(self.request, self.template_name, {"form": form})


# اختياري: تخصيص عناوين استعادة كلمة المرور
class ResetPasswordView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class ResetPasswordConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")
