from django.contrib import admin
from .models import Dispute

@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "status", "opener_role", "opened_by", "opened_at", "resolved_at")
    list_filter = ("status", "opener_role")
    search_fields = ("title", "reason", "details")
    autocomplete_fields = ("opened_by", "resolved_by")
