# disputes/forms.py
from django import forms
from .models import Dispute

class DisputeForm(forms.ModelForm):
    class Meta:
        model = Dispute
        fields = ["title", "description"]
        widgets = {
            "title": forms.TextInput(attrs={"class":"input","placeholder":"عنوان مختصر"}),
            "description": forms.Textarea(attrs={"class":"input","rows":4,"placeholder":"اشرح المشكلة بإيجاز"}),
        }
