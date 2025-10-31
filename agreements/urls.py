# agreements/urls.py
from __future__ import annotations

import inspect
from typing import Callable
from django.urls import path
from . import views

app_name = "agreements"

# =========================================================
# Helpers: توافق ديناميكي مع توقيعات الدوال في views.py
# =========================================================
def _call_with_pk_or_agreement_id(view_func: Callable, request, pk: int, **kwargs):
    """
    يستدعي الدالة المعطاة بتمرير المعامل الصحيح:
    - إن كانت الدالة تقبل 'agreement_id' نمرّر agreement_id=pk
    - إن كانت تقبل 'pk' نمرّر pk=pk
    - وإلا نحاول الاستدعاء المباشر ونترك Django يتعامل مع الخطأ (للكشف المبكّر)
    """
    try:
        params = inspect.signature(view_func).parameters
    except (ValueError, TypeError):
        # fallback بسيط في حال دالّة ملفوفة بديكوريتر يغيّب التوقيع
        try:
            return view_func(request, agreement_id=pk, **kwargs)
        except TypeError:
            return view_func(request, pk=pk, **kwargs)

    if "agreement_id" in params:
        return view_func(request, agreement_id=pk, **kwargs)
    if "pk" in params:
        return view_func(request, pk=pk, **kwargs)
    # آخر حل: جرّب agreement_id ثم pk
    try:
        return view_func(request, agreement_id=pk, **kwargs)
    except TypeError:
        return view_func(request, pk=pk, **kwargs)


def _detail_pk(request, pk: int, **kwargs):
    return _call_with_pk_or_agreement_id(getattr(views, "detail"), request, pk, **kwargs)


def _edit_pk(request, pk: int, **kwargs):
    return _call_with_pk_or_agreement_id(getattr(views, "edit"), request, pk, **kwargs)


def _finalize_pk(request, pk: int, **kwargs):
    # قد تكون الدالة باسم finalize_clauses أو finalize
    fn = getattr(views, "finalize_clauses", None) or getattr(views, "finalize", None)
    return _call_with_pk_or_agreement_id(fn, request, pk, **kwargs)


# Aliases: تحويل pk → request_id لمسارات by-request المتوافقة مع قوالب قديمة
def _open_by_request_alias_pk(request, pk: int, **kwargs):
    return views.open_by_request(request, request_id=pk, **kwargs)


def _accept_by_request_alias_pk(request, pk: int, **kwargs):
    return views.accept_by_request(request, request_id=pk, **kwargs)


def _reject_by_request_alias_pk(request, pk: int, **kwargs):
    return views.reject_by_request(request, request_id=pk, **kwargs)


urlpatterns = [
    # =====================================================
    # المسارات القياسية (المعتمدة)
    # =====================================================

    # فتح/إنشاء اتفاقية انطلاقًا من الطلب (يتوقع request_id)
    path("open/by-request/<int:request_id>/", views.open_by_request, name="open_by_request"),
    path("milestone/<int:milestone_id>/deliver/", views.milestone_deliver, name="milestone_deliver"),
    path("milestone/<int:milestone_id>/approve/", views.milestone_approve, name="milestone_approve"),
    path("milestone/<int:milestone_id>/reject/", views.milestone_reject, name="milestone_reject"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/clauses/", views.finalize_clauses, name="finalize_clauses"),

    # موافقة/رفض العميل على اتفاقية الطلب (يتوقع request_id)
    path("accept/by-request/<int:request_id>/", views.accept_by_request, name="accept_by_request"),
    path("reject/by-request/<int:request_id>/", views.reject_by_request, name="reject_by_request"),
]

# =========================================================
# مسارات عرض/تحرير/تثبيت الاتفاقية حسب المعرّف
# تدعم الدوال التي تستقبل pk أو agreement_id تلقائيًا
# =========================================================
if hasattr(views, "detail"):
    urlpatterns.append(path("<int:pk>/", _detail_pk, name="detail"))

if hasattr(views, "edit"):
    urlpatterns.append(path("<int:pk>/edit/", _edit_pk, name="edit"))

if hasattr(views, "finalize_clauses") or hasattr(views, "finalize"):
    urlpatterns.append(path("<int:pk>/finalize-clauses/", _finalize_pk, name="finalize_clauses"))

# =====================================================
# Aliases للتوافق العكسي مع قوالب قديمة (اختياري)
# (كانت تمرّر pk بدل request_id لمسارات by-request)
# =====================================================
urlpatterns += [
    path("open/by-request/pk/<int:pk>/", _open_by_request_alias_pk, name="open_by_request_pk"),
    path("accept/by-request/pk/<int:pk>/", _accept_by_request_alias_pk, name="accept_by_request_pk"),
    path("reject/by-request/pk/<int:pk>/", _reject_by_request_alias_pk, name="reject_by_request_pk"),
]

# =========================================================
# إجراءات الدفعات/المراحل (Milestones) — تُضاف فقط إذا وُجدت
# =========================================================
if hasattr(views, "milestone_deliver"):
    urlpatterns.append(
        path("milestone/<int:milestone_id>/deliver/", views.milestone_deliver, name="milestone_deliver")
    )
if hasattr(views, "milestone_approve"):
    urlpatterns.append(
        path("milestone/<int:milestone_id>/approve/", views.milestone_approve, name="milestone_approve")
    )
if hasattr(views, "milestone_reject"):
    urlpatterns.append(
        path("milestone/<int:milestone_id>/reject/", views.milestone_reject, name="milestone_reject")
    )
