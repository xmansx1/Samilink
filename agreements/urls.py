# agreements/urls.py
from __future__ import annotations

from django.urls import path
from . import views

app_name = "agreements"

# ============================================
# ملاحظات توافق:
# - الدوال في views التالية تستخدم الوسيط pk:
#     open_by_request(request, pk)
#     accept_by_request(request, pk)
#     reject_by_request(request, pk)
#     detail(request, pk)
#     finalize_clauses(request, pk)
#     edit(request, pk)            # إن كانت موجودة لديك
#
# - لضمان التوافق مع مسارات قديمة تستخدم request_id / agreement_id
#   قمنا بإنشاء "مُحَوِّلات" بسيطة تمُرِّر pk لِـ views.
# ============================================

# ---- محولات أسماء المعاملات (Aliases) ----
def _open_by_request_alias(request, request_id: int, **kwargs):
    # يحوّل request_id -> pk
    return views.open_by_request(request, pk=request_id)

def _accept_by_request_alias(request, request_id: int, **kwargs):
    return views.accept_by_request(request, pk=request_id)

def _reject_by_request_alias(request, request_id: int, **kwargs):
    return views.reject_by_request(request, pk=request_id)

def _detail_alias(request, agreement_id: int, **kwargs):
    return views.detail(request, pk=agreement_id)

def _edit_alias(request, agreement_id: int, **kwargs):
    # استخدم هذا فقط إذا كانت لديك views.edit
    return views.edit(request, pk=agreement_id)

def _finalize_alias(request, pk: int, **kwargs):
    # مجرد تمرير مباشر (اسم موحّد أساسًا)
    return views.finalize_clauses(request, pk=pk)


urlpatterns = [
    # ======================
    # المسارات "القياسية" الحديثة (أسماء وسيط موحّدة: pk)
    # ======================

    # إنشاء/فتح اتفاقية بناءً على رقم الطلب
    path("open/by-request/<int:pk>/", views.open_by_request, name="open_by_request"),

    # قبول/رفض من جهة الطلب (للعميل)
    path("accept/by-request/<int:pk>/", views.accept_by_request, name="accept_by_request"),
    path("reject/by-request/<int:pk>/", views.reject_by_request, name="reject_by_request"),

    # تفاصيل/تعديل الاتفاقية مباشرة بواسطة رقم الاتفاقية
    path("<int:pk>/", views.detail, name="detail"),

    # ملاحظة: وفّرنا edit إن كانت لديك دالة views.edit
    path("<int:pk>/edit/", views.edit, name="edit"),

    # تثبيت البنود لاتفاقية (اختيار بنود الأدمن + تخصيص)
    path("<int:pk>/finalize-clauses/", views.finalize_clauses, name="finalize_clauses"),

    # ======================
    # توافق عكسي (Legacy Aliases) لمنع NoReverseMatch
    # هذه تُحوِّل request_id / agreement_id إلى pk داخليًا
    # ======================

    # كانت سابقًا: open-by-request/<int:request_id>/
    path("open-by-request/<int:request_id>/", _open_by_request_alias, name="open_by_request_legacy"),

    # كانت سابقًا: accept-by-request/<int:request_id>/ و reject-by-request/<int:request_id>/
    path("accept-by-request/<int:request_id>/", _accept_by_request_alias, name="accept_by_request_legacy"),
    path("reject-by-request/<int:request_id>/", _reject_by_request_alias, name="reject_by_request_legacy"),

    # كانت سابقًا: <int:agreement_id>/ و <int:agreement_id>/edit/
    path("<int:agreement_id>/legacy/", _detail_alias, name="detail_legacy"),
    path("<int:agreement_id>/edit/legacy/", _edit_alias, name="edit_legacy"),

    # في نسخ سابقة استخدمت نفس الاسم finalize-clauses مع pk مباشر — أبقيناه أعلاه
    # ولو كان لديك مسار قديم مختلف؛ أضف Alias إضافي هنا يحوّل للاسم الجديد.
]
