from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, CreateView, TemplateView, UpdateView

from .forms import LoginForm, RegisterForm, ProfileUpdateForm

class LoginPageView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("website:home")

    def form_valid(self, form):
        user = form.cleaned_data["user"]
        login(self.request, user)
        messages.success(self.request, "تم تسجيل الدخول بنجاح.")
        next_url = self.request.GET.get("next")
        return redirect(next_url or self.get_success_url())

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

# اختياري: تخصيص عناوين استعادة كلمة المرور
class ResetPasswordView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

class ResetPasswordConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")
