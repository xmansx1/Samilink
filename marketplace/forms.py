# marketplace/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.utils.text import Truncator
from django.utils.html import strip_tags

from .models import Request, Offer, Note

User = get_user_model()


def _clean_text(v: str) -> str:
    """
    تنظيف بسيط وآمن للنصوص:
    - إزالة HTML لمنع أي إدراج غير مقصود.
    - تقليم المسافات الزائدة.
    """
    if v is None:
        return v
    v = strip_tags(v)
    v = " ".join(v.split())
    return v


class RequestCreateForm(forms.ModelForm):
    """نموذج إنشاء طلب للعميل."""
    class Meta:
        model = Request
        fields = ["title", "details", "estimated_duration_days", "estimated_price", "links"]
        labels = {
            "title": "العنوان",
            "details": "التفاصيل",
            "estimated_duration_days": "المدة التقديرية (أيام)",
            "estimated_price": "السعر التقريبي",
            "links": "روابط (اختياري)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "عنوان الطلب"}),
            "details": forms.Textarea(attrs={"class": "input", "rows": 5, "placeholder": "وصف مختصر للعمل المطلوب"}),
            "estimated_duration_days": forms.NumberInput(attrs={"class": "input", "min": 1}),
            "estimated_price": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": 0}),
            "links": forms.Textarea(attrs={"class": "input", "rows": 2, "placeholder": "روابط (اختياري)"}),
        }

    def clean_title(self):
        title = _clean_text(self.cleaned_data.get("title", "")).strip()
        if not title:
            raise forms.ValidationError("يرجى إدخال عنوان الطلب.")
        return Truncator(title).chars(160)

    def clean_details(self):
        details = _clean_text(self.cleaned_data.get("details", "")).strip()
        return Truncator(details).chars(5000)

    def clean_estimated_duration_days(self):
        days = self.cleaned_data.get("estimated_duration_days")
        if not days or days < 1:
            raise forms.ValidationError("المدة التقديرية يجب أن تكون رقمًا موجبًا.")
        return days

    def clean_estimated_price(self):
        price = self.cleaned_data.get("estimated_price")
        if price is None or price < 0:
            raise forms.ValidationError("السعر التقريبي يجب أن يكون صفرًا أو رقمًا موجبًا.")
        return price

    def clean_links(self):
        links = (self.cleaned_data.get("links") or "").strip()
        return Truncator(strip_tags(links)).chars(2000)


class OfferCreateForm(forms.ModelForm):
    """
    نموذج تقديم العرض من الموظف.
    أبقيناه كما هو ولكن عدّلنا الحقول لتتوافق مع الموديل (note بدل text).
    سيتم ضبط instance.request و instance.employee في OfferCreateView أو في RequestDetailView.post.
    """
    class Meta:
        model = Offer
        fields = ["note", "proposed_duration_days", "proposed_price"]
        labels = {
            "note": "تفاصيل العرض",
            "proposed_duration_days": "المدة المقترحة (أيام)",
            "proposed_price": "السعر المقترح",
        }
        widgets = {
            "note": forms.Textarea(attrs={"class": "input", "rows": 4, "placeholder": "تفاصيل عرضك"}),
            "proposed_duration_days": forms.NumberInput(attrs={"class": "input", "min": 1}),
            "proposed_price": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": 0}),
        }

    def clean_note(self):
        text = _clean_text(self.cleaned_data.get("note", "")).strip()
        if not text:
            raise forms.ValidationError("يرجى كتابة تفاصيل العرض.")
        return Truncator(text).chars(5000)

    def clean_proposed_duration_days(self):
        days = self.cleaned_data.get("proposed_duration_days")
        if not days or days < 1:
            raise forms.ValidationError("المدة المقترحة يجب أن تكون رقمًا موجبًا.")
        return days

    def clean_proposed_price(self):
        price = self.cleaned_data.get("proposed_price")
        if price is None or price < 0:
            raise forms.ValidationError("السعر المقترح يجب أن يكون صفرًا أو رقمًا موجبًا.")
        return price

    def clean(self):
        """
        منع الموظف من تقديم أكثر من عرض واحد لنفس الطلب (تحقق مبكر).
        يعتمد على أن الـ view عيّن instance.request و instance.employee مسبقًا.
        """
        cleaned = super().clean()
        req = getattr(self.instance, "request", None)
        emp = getattr(self.instance, "employee", None)
        if req and emp:
            if Offer.objects.filter(request=req, employee=emp, status__in=(Offer.Status.PENDING,)).exists():
                raise forms.ValidationError("لا يمكنك تقديم أكثر من عرض واحد لهذا الطلب.")
        return cleaned


class NoteForm(forms.ModelForm):
    """نموذج الملاحظات داخل الطلب (نقاش رسمي)."""
    class Meta:
        model = Note
        fields = ["text", "is_internal"]
        labels = {"text": "الملاحظة", "is_internal": "رؤية مقيدة (داخلي)"}
        widgets = {
            "text": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "أضف ملاحظة"}),
        }

    def clean_text(self):
        text = _clean_text(self.cleaned_data.get("text", "")).strip()
        if not text:
            raise forms.ValidationError("يرجى كتابة نص الملاحظة.")
        return Truncator(text).chars(5000)

# --- النموذج الثاني الذي كان موجودًا لديك: أبقيناه كما هو مع توافق الحقول ---
from django import forms as _forms_alias  # لتفادي أي التباس مع الاستيراد أعلاه

class OfferForm(_forms_alias.ModelForm):
    class Meta:
        model = Offer
        fields = ["proposed_duration_days", "proposed_price", "note"]
        widgets = {
            "proposed_duration_days": _forms_alias.NumberInput(attrs={"min": 1, "class": "input", "placeholder": "المدة بالأيام"}),
            "proposed_price": _forms_alias.NumberInput(attrs={"min": 1, "step": "0.5", "class": "input", "placeholder": "المبلغ بالريال"}),
            "note": _forms_alias.Textarea(attrs={"rows": 3, "class": "input", "placeholder": "تفاصيل العرض (اختياري)"}),
        }

    def clean_proposed_duration_days(self):
        v = self.cleaned_data["proposed_duration_days"]
        if v < 1 or v > 365:
            raise _forms_alias.ValidationError("المدة يجب أن تكون بين 1 و 365 يومًا.")
        return v

    def clean_proposed_price(self):
        v = self.cleaned_data["proposed_price"]
        if v <= 0:
            raise _forms_alias.ValidationError("المبلغ يجب أن يكون أكبر من صفر.")
        return v


# marketplace/forms.py  (أضِف في آخر الملف مثلاً)
from django.contrib.auth import get_user_model
from django import forms as _admin_forms

class AdminReassignForm(_admin_forms.Form):
    """اختيار موظف لإعادة الإسناد (admin-only)."""
    employee = _admin_forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(role="employee"),
        label="الموظف الجديد",
        widget=_admin_forms.Select(attrs={"class": "input"})
    )
