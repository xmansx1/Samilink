# marketplace/urls.py
from django.urls import path
from django.shortcuts import redirect
from . import views

app_name = "marketplace"

def request_list_alias(request):
    """يمكن تعديلها لاحقًا لتوجّه لما يناسبك (طلباتي/الطلبات الجديدة/مهامي)."""
    return redirect("marketplace:my_requests")

urlpatterns = [
    # ======================
    # الطلبات (Requests)
    # ======================
    path("r/new/", views.RequestCreateView.as_view(), name="request_create"),
    path("r/mine/", views.MyRequestsListView.as_view(), name="my_requests"),
    path("r/new-requests/", views.NewRequestsForEmployeesView.as_view(), name="new_requests"),
    path("r/assigned/", views.MyAssignedRequestsView.as_view(), name="my_tasks"),
    path("r/<int:pk>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("r/", request_list_alias, name="request_list"),

    # ملاحظات على الطلب
    path("r/<int:pk>/notes/add/", views.request_add_note, name="request_add_note"),

    # ======================
    # تغيير حالة الطلب (حسب الصلاحيات)
    # الموظف المُسنَد أو المدير:
    #   - تغيير الحالة ضمن الانتقالات المسموحة
    # المدير فقط:
    #   - يستطيع الإلغاء دائمًا مع سبب
    # ======================
    path("r/<int:pk>/state/change/", views.request_change_state, name="request_change_state"),
    path("r/<int:pk>/state/cancel/", views.request_cancel, name="request_cancel"),

    # ======================
    # العروض (Offers)
    # (المسارات الأصلية باقية دون حذف)
    # ======================
    # نمط CBV محفوظ باسم مختلف لتفادي التعارض
    path("o/<int:request_id>/new/", views.OfferCreateView.as_view(), name="offer_create_cbv"),
    path("o/<int:offer_id>/select/", views.select_offer, name="offer_select_cbvstyle"),

    # نمط الدوال
    path("r/<int:request_id>/offer/new/", views.offer_create, name="offer_create_fn"),
    path("offers/<int:offer_id>/", views.offer_detail, name="offer_detail"),
    path("offers/<int:offer_id>/select/", views.offer_select, name="offer_select_fn"),
    path("offers/<int:offer_id>/reject/", views.offer_reject, name="offer_reject"),

    # ======================
    # صلاحيات المدير العام على الطلب
    # ======================
    path("r/<int:pk>/admin/reset-to-new/", views.admin_request_reset_to_new, name="admin_request_reset_to_new"),
    path("r/<int:pk>/admin/delete/", views.admin_request_delete, name="admin_request_delete"),
    path("r/<int:pk>/admin/reassign/", views.admin_request_reassign, name="admin_request_reassign"),
]
