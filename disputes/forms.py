# disputes/forms.py
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from .models import Dispute


class DisputeForm(forms.ModelForm):
    class Meta:
        model = Dispute
        fields = ["title", "reason", "details"]  # متطابقة مع الموديل
        labels = {
            "title": "عنوان النزاع",
            "reason": "سبب النزاع",
            "details": "تفاصيل إضافية",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "مثال: خلاف حول نطاق العمل"}),
            "reason": forms.TextInput(attrs={"class": "input", "placeholder": "السبب المختصر"}),
            "details": forms.Textarea(attrs={"class": "textarea", "rows": 4, "placeholder": "اشرح المشكلة بإيجاز"}),
        }

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if len(title) < 4:
            raise ValidationError("العنوان قصير جدًا.")
        return title

    def clean_reason(self):
        return (self.cleaned_data.get("reason") or "").strip()

    def clean_details(self):
        return (self.cleaned_data.get("details") or "").strip()
