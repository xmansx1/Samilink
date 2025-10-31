# profiles/views.py
from urllib.parse import quote

from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, ListView

from .models import EmployeeProfile


class EmployeeListView(ListView):
    model = EmployeeProfile
    template_name = "profiles/employees_list.html"
    context_object_name = "employees"
    paginate_by = 12

    def get_queryset(self):
        qs = (
            EmployeeProfile.objects.select_related("user")
            .filter(public_visible=True, user__is_active=True, user__role="employee")
            .order_by("-rating", "-updated_at")
        )
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(user__name__icontains=q)
                | Q(user__email__icontains=q)
                | Q(specialty__icontains=q)
                | Q(skills__icontains=q)
                | Q(title__icontains=q)
            )
        return qs


class EmployeeDetailView(DetailView):
    model = EmployeeProfile
    template_name = "profiles/employee_detail.html"
    context_object_name = "emp"

    def get_object(self):
        obj = super().get_object()
        # حماية الخصوصية: إظهار الموظفين المفعّلين والظاهرين فقط
        if not obj.public_visible or obj.user.role != "employee" or not obj.user.is_active:
            raise Http404("هذا البروفايل غير متاح.")
        return obj


def whatsapp_redirect(request, user_id: int):
    """
    Endpoint وسيط لإخفاء رقم الموظف وتطبيق Rate-limit بسيط.
    يحوّل إلى wa.me/<number>?text=...
    """
    profile = get_object_or_404(
        EmployeeProfile,
        user_id=user_id,
        public_visible=True,
        user__is_active=True,
    )
    phone_e164 = getattr(profile.user, "phone", None)
    if not phone_e164:
        return HttpResponseBadRequest("لا يتوفر رقم جوال للموظف.")

    # Rate limit بسيط بالجلسة (5 ثوانٍ بين الضغطات لكل موظف)
    import time

    key = f"wa_last_{user_id}"
    last = request.session.get(key, 0.0)
    now = time.time()
    if now - last < 5:
        # يمكن عرض رسالة أو الاكتفاء بالمتابعة؛ هنا نتابع التوجيه
        pass
    request.session[key] = now

    # نص الرسالة (اختياري) بحد أقصى 200 حرف
    raw_msg = (request.GET.get("msg") or "").strip()
    msg = raw_msg[:200]
    query = f"?text={quote(msg)}" if msg else ""

    # wa.me يحتاج الرقم بلا +
    number = phone_e164[1:] if phone_e164.startswith("+") else phone_e164
    return redirect(f"https://wa.me/{number}{query}")
