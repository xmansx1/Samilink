from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("email", "name", "phone", "role", "is_active", "is_staff", "date_joined")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "name", "phone")

    fieldsets = (
        (_("المعلومات الأساسية"), {"fields": ("email", "phone", "name", "password")}),
        (_("الأذونات"), {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("تواريخ"), {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ("last_login", "date_joined")

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "phone", "name", "role", "password1", "password2", "is_active", "is_staff"),
        }),
    )
