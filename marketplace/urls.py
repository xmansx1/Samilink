# marketplace/urls.py
from django.urls import path
from django.shortcuts import redirect
from . import views

app_name = "marketplace"

# ======================
# Aliases / Redirects
# ======================
def request_list_alias(request):
    """حاليًا تحيل إلى 'طلباتي' للعميل."""
    return redirect("marketplace:my_requests")

def offer_create_legacy_cbv_redirect(request, request_id: int):
    """توافق لمسار قديم: o/<int:request_id>/new/ → r/<int:request_id>/offer/new/"""
    return redirect("marketplace:offer_create", request_id=request_id)

def offer_select_legacy_cbv_redirect(request, offer_id: int):
    """توافق لمسار قديم: o/<int:offer_id>/select/ → offers/<int:offer_id>/select/"""
    return redirect("marketplace:offer_select", offer_id=offer_id)


urlpatterns = [
    # ======================
    # الطلبات (Requests)
    # ======================
    path("r/new/", views.RequestCreateView.as_view(), name="request_create"),
    path("r/mine/", views.MyRequestsListView.as_view(), name="my_requests"),
    path("r/new-requests/", views.NewRequestsForEmployeesView.as_view(), name="new_requests"),

    # مسار قديم (عرض الطلبات المسندة) لكن باسم مختلف لتجنب تضارب الأسماء:
    path("r/assigned/", views.MyAssignedRequestsView.as_view(), name="assigned_requests"),

    # تفاصيل و قائمة افتراضية
    path("r/<int:pk>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("r/", request_list_alias, name="request_list"),

    # نزاعات
    path("disputed/", views.disputed_tasks, name="disputed_tasks"),

    # ملاحظات على الطلب
    path("r/<int:pk>/notes/add/", views.request_add_note, name="request_add_note"),

    # ======================
    # تغيير حالة الطلب
    # ======================
    path("r/<int:pk>/status/change/", views.request_change_state, name="request_change_status"),
    path("r/<int:pk>/state/change/", views.request_change_state, name="request_change_state"),  # توافق
    path("r/<int:pk>/state/cancel/", views.request_cancel, name="request_cancel"),

    # ======================
    # العروض (Offers)
    # ======================
    path("r/<int:request_id>/offer/new/", views.OfferCreateView.as_view(), name="offer_create"),
    path("offers/<int:offer_id>/", views.offer_detail, name="offer_detail"),
    path("offers/<int:offer_id>/select/", views.offer_select, name="offer_select"),
    path("offers/<int:offer_id>/reject/", views.offer_reject, name="offer_reject"),

    # توافق لمسارات قديمة
    path("o/<int:request_id>/new/", offer_create_legacy_cbv_redirect, name="offer_create_cbv"),
    path("o/<int:offer_id>/select/", offer_select_legacy_cbv_redirect, name="offer_select_cbvstyle"),

    # ======================
    # مهامي (الاسم الرسمي الذي تستخدمه القوائم)
    # ======================
    path("my-tasks/", views.MyTasksView.as_view(), name="my_tasks"),
]
