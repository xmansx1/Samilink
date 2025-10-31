# agreements/forms.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils.text import Truncator
from django.utils.html import strip_tags

from .models import Agreement, Milestone, AgreementClause


# ========================= أدوات تنظيف نصوص آمنة =========================
def _clean_text(v: str) -> str:
    """
    تنقية نص بسيط: إزالة HTML، ضغط المسافات، وحفظ قيمة مختصرة.
    """
    if v is None:
        return v
    v = strip_tags(v or "")
    v = " ".join(v.split())
    return v


# ========================= نماذج الاتفاقية =========================
class AgreementForm(forms.ModelForm):
    """
    نموذج الإنشاء (قبل الإقفال):
    يحتوي الحقول الجوهرية. بعد الإنشاء ستُقفل duration_days/total_amount
    على مستوى الواجهة والخادم (نستخدم AgreementEditForm للتعديل لاحقًا).
    """
    class Meta:
        model = Agreement
        fields = ["title", "text", "duration_days", "total_amount"]
        labels = {
            "title": "عنوان الاتفاقية",
            "text": "نص الاتفاقية",
            "duration_days": "المدة (أيام)",
            "total_amount": "الإجمالي (ريال)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "عنوان واضح"}),
            "text": forms.Textarea(attrs={"class": "input", "rows": 6, "placeholder": "نص الاتفاقية (اختياري)"}),
            "duration_days": forms.NumberInput(attrs={"class": "input", "min": 1}),
            "total_amount": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": 0}),
        }

    def clean_title(self):
        title = _clean_text(self.cleaned_data.get("title", "")).strip()
        if not title:
            raise forms.ValidationError("يرجى إدخال عنوان الاتفاقية.")
        return Truncator(title).chars(200)

    def clean_text(self):
        text = _clean_text(self.cleaned_data.get("text", "")).strip()
        return Truncator(text).chars(10000)


class AgreementEditForm(forms.ModelForm):
    """
    نموذج التعديل بعد الإنشاء:
    يسمح بتعديل العنوان/النص فقط — بينما الحقول الجوهرية مقفلة.
    """
    class Meta:
        model = Agreement
        fields = ["title", "text"]
        labels = {"title": "عنوان الاتفاقية", "text": "نص الاتفاقية"}
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "عنوان واضح"}),
            "text": forms.Textarea(attrs={"class": "input", "rows": 6, "placeholder": "نص الاتفاقية (اختياري)"}),
        }

    def clean_title(self):
        title = _clean_text(self.cleaned_data.get("title", "")).strip()
        if not title:
            raise forms.ValidationError("يرجى إدخال عنوان الاتفاقية.")
        return Truncator(title).chars(200)

    def clean_text(self):
        text = _clean_text(self.cleaned_data.get("text", "")).strip()
        return Truncator(text).chars(10000)


# ========================= دفعات/مراحل الاتفاقية =========================
class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ["title", "amount", "due_days", "order"]
        labels = {
            "title": "عنوان الدفعة/المرحلة",
            "amount": "المبلغ (ريال)",
            "due_days": "مستحق بعد (أيام)",
            "order": "ترتيب",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "مثال: دفعة مقدّم"}),
            "amount": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": 0}),
            "due_days": forms.NumberInput(attrs={"class": "input", "min": 1}),
            "order": forms.NumberInput(attrs={"class": "input", "min": 1}),
        }

    def clean_title(self):
        title = _clean_text(self.cleaned_data.get("title", "")).strip()
        if not title:
            raise forms.ValidationError("يرجى إدخال عنوان الدفعة.")
        return Truncator(title).chars(160)


class _BaseMilestoneFormSet(BaseInlineFormSet):
    """
    تحققات مستوى الـ FormSet:
    - وجود صف واحد على الأقل (min_num=1).
    - عدم تكرار ترتيب order، وأن يبدأ من 1.
    - مجموع المبالغ == إجمالي الاتفاقية (بسماحية 0.01).
    """
    def clean(self):
        super().clean()

        if any(self.errors):
            # لو في أخطاء حقول، لا نُكرر الرسائل
            return

        instance: Agreement = self.instance
        forms_active = [f for f in self.forms if not getattr(f, "cleaned_data", {}).get("DELETE", False)]

        if not forms_active:
            raise forms.ValidationError("يجب إضافة دفعة واحدة على الأقل.")

        # 1) الترتيب: بداية من 1 + بدون تكرار
        orders = []
        for f in forms_active:
            order = f.cleaned_data.get("order")
            if not order or order < 1:
                raise forms.ValidationError("ترتيب كل دفعة يجب أن يكون 1 أو أكبر.")
            orders.append(order)
        if len(set(orders)) != len(orders):
            raise forms.ValidationError("ترتيب الدفعات لا يجب أن يحتوي على قيَم مكررة.")

        # 2) المبالغ: غير سالبة + مجموعها == إجمالي الاتفاقية
        total = Decimal("0.00")
        for f in forms_active:
            amount = f.cleaned_data.get("amount")
            if amount is None or amount < 0:
                raise forms.ValidationError("مبلغ كل دفعة يجب أن يكون رقمًا موجبًا أو صفرًا.")
            total += amount

        # سماحية تقريب طفيفة 0.01
        tol = (total - instance.total_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if tol != Decimal("0.00"):
            raise forms.ValidationError(
                f"مجموع مبالغ الدفعات ({total}) لا يساوي إجمالي الاتفاقية ({instance.total_amount})."
            )


MilestoneFormSet = inlineformset_factory(
    Agreement,
    Milestone,
    form=MilestoneForm,
    formset=_BaseMilestoneFormSet,
    extra=1,
    max_num=50,     # مرونة عالية
    can_delete=True,
    validate_min=True,
    min_num=1,
)


# ========================= تثبيت بنود الاتفاقية =========================
class AgreementClauseSelectForm(forms.Form):
    """
    شاشة تثبيت البنود بعد إنشاء الاتفاقية:
      - اختيار 1+ من البنود الجاهزة (يُدار تفعيلها من الأدمن).
      - إضافة بنود مخصّصة (سطر لكل بند).
    """
    clauses = forms.ModelMultipleChoiceField(
        label=("اختر البنود الجاهزة"),
        queryset=AgreementClause.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=("يمكن تحديد أكثر من بند. البنود الظاهرة مفعّلة فقط."),
    )
    custom_clauses = forms.CharField(
        label=("بنود مخصصة (اختياري)"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "dir": "rtl",
                "placeholder": "اكتب كل بند في سطر مستقل",
            }
        ),
        help_text=("اكتب كل بند في سطر مستقل. التنقية النهائية تتم داخل نموذج العنصر."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # عرض البنود المفعّلة فقط وبترتيب العنوان
        self.fields["clauses"].queryset = AgreementClause.objects.filter(is_active=True).order_by("title")

    def cleaned_custom_lines(self) -> list[str]:
        """
        تُرجع قائمة البنود المخصصة سطرًا-بسطر (بدون HTML).
        ملاحظة: التنقية النهائية تتم في AgreementClauseItem.clean().
        """
        data = self.cleaned_data.get("custom_clauses") or ""
        return [ln.strip() for ln in data.splitlines() if ln.strip()]
