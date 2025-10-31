from django.contrib import admin
from .models import EmployeeProfile

@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "specialty", "rating", "public_visible", "updated_at")
    list_filter = ("public_visible",)
    search_fields = ("user__email", "user__name", "specialty", "skills", "title")
    prepopulated_fields = {}  # slug يُولّد تلقائيًا
    readonly_fields = ("created_at", "updated_at", "slug")
