# disputes/urls.py
from django.urls import path
from . import views

app_name = "disputes"

urlpatterns = [
    # فتح نزاع على طلب
    path("request/<int:request_id>/open/", views.dispute_create, name="open"),
    # تحديث حالة النزاع (حل/إلغاء/إعادة فتح) — للمسؤولين فقط
    path("<int:pk>/update-status/", views.dispute_update_status, name="update_status"),
    # (اختياري) عرض النزاع
    path("<int:pk>/", views.dispute_detail, name="detail"),
]
