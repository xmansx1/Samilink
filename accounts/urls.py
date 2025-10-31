from django.urls import path
from django.contrib.auth import views as auth_views
from .views import (
    LoginPageView, LogoutView, RegisterView,
    ProfileView, ProfileEditView,
    ResetPasswordView, ResetPasswordConfirmView
)

app_name = "accounts"

urlpatterns = [
    path("login/", LoginPageView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("register/", RegisterView.as_view(), name="register"),

    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/edit/", ProfileEditView.as_view(), name="profile_edit"),

    # استعادة كلمة المرور
    path("password/reset/", ResetPasswordView.as_view(), name="password_reset"),
    path("password/reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"
    ), name="password_reset_done"),
    path("password/reset/confirm/<uidb64>/<token>/", ResetPasswordConfirmView.as_view(),
         name="password_reset_confirm"),
    path("password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"
    ), name="password_reset_complete"),
]
