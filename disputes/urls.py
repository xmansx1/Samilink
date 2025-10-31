from django.urls import path
from . import views

app_name = "disputes"

urlpatterns = [
    # فتح نزاع على طلب
    path("request/<int:request_id>/open/", views.dispute_create, name="open"),
    path("request/<int:request_id>/open/", views.open_request_dispute, name="open"),
    path("request/<int:pk>/open/", views.open_request_dispute, name="open"),

    # تحديث حالة نزاع
    path("update/<int:dispute_id>/", views.dispute_update_status, name="update"),
]
