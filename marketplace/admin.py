from django.contrib import admin
from .models import Request, Offer, Note

@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "client", "assigned_employee", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "details", "client__email", "assigned_employee__email")
    autocomplete_fields = ("client", "assigned_employee")

@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "employee", "proposed_price", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("note", "employee__email", "request__title")  # كان text ← صُحّح إلى note
    autocomplete_fields = ("request", "employee")

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "author", "is_internal", "created_at")
    list_filter = ("is_internal",)
    search_fields = ("text", "author__email", "request__title")
    autocomplete_fields = ("request", "author", "parent")
