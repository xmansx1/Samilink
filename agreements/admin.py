# agreements/admin.py
from django.contrib import admin
from .models import Agreement, Milestone
from .models import AgreementClause, AgreementClauseItem

@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "employee", "status", "total_amount", "duration_days", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("title", "text", "request__title", "employee__email", "request__client__email")
    autocomplete_fields = ("request", "employee")


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ("id", "agreement", "title", "amount", "order", "due_days")
    list_filter = ("agreement",)
    search_fields = ("title", "agreement__title", "agreement__request__title")
    autocomplete_fields = ("agreement",)
    ordering = ("agreement", "order", "id")


@admin.register(AgreementClause)
class AgreementClauseAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "key", "body")
    list_editable = ("is_active",)

class AgreementClauseItemInline(admin.TabularInline):
    model = AgreementClauseItem
    extra = 0
    fields = ("position", "clause", "custom_text")
    ordering = ("position",)
