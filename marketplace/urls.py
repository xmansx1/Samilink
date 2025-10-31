# marketplace/urls.py
from django.urls import path
from django.shortcuts import redirect
from . import views

app_name = "marketplace"

def request_list_alias(request):
    """يمكن تعديلها لاحقًا لتوجّه لما يناسبك (طلباتي/الطلبات الجديدة/مهامي)."""
    return redirect("marketplace:my_requests")

urlpatterns = [
    # الطلبات
    path("r/new/", views.RequestCreateView.as_view(), name="request_create"),
    path("r/mine/", views.MyRequestsListView.as_view(), name="my_requests"),
    path("r/new-requests/", views.NewRequestsForEmployeesView.as_view(), name="new_requests"),
    path("r/assigned/", views.MyAssignedRequestsView.as_view(), name="my_tasks"),
    path("r/<int:pk>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("r/", request_list_alias, name="request_list"),
    path("r/<int:pk>/notes/add/", views.request_add_note, name="request_add_note"),

    # العروض (المساران محفوظان بدون حذف، لكن بأسماء مختلفة لتفادي التعارض)
    path("o/<int:request_id>/new/", views.OfferCreateView.as_view(), name="offer_create_cbv"),
    path("o/<int:offer_id>/select/", views.select_offer, name="offer_select_cbvstyle"),

    path("r/<int:request_id>/offer/new/", views.offer_create, name="offer_create_fn"),
    path("offers/<int:offer_id>/", views.offer_detail, name="offer_detail"),
    path("offers/<int:offer_id>/select/", views.offer_select, name="offer_select_fn"),
    path("offers/<int:offer_id>/reject/", views.offer_reject, name="offer_reject"),
    # صلاحيات المدير العام على الطلب
    path("r/<int:pk>/admin/reset-to-new/", views.admin_request_reset_to_new, name="admin_request_reset_to_new"),
    path("r/<int:pk>/admin/delete/", views.admin_request_delete, name="admin_request_delete"),
    path("r/<int:pk>/admin/reassign/", views.admin_request_reassign, name="admin_request_reassign"),
]
