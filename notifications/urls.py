from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    # صفحة HTML
    path("", views.page_index, name="index"),
    path("read/<int:pk>/", views.page_mark_read, name="page_mark_read"),
    path("read-all/", views.page_mark_all_read, name="page_mark_all_read"),
    path("delete/<int:pk>/", views.page_delete, name="page_delete"),
    path("delete-read-all/", views.page_delete_all_read, name="page_delete_all_read"),

    # REST-like APIs (للاستخدام مع أيقونة الجرس في الهيدر)
    path("api/unread-count", views.api_unread_count, name="api_unread_count"),
    path("api/list", views.api_list, name="api_list"),
    path("api/mark-read", views.api_mark_read, name="api_mark_read"),
    path("api/mark-all-read", views.api_mark_all_read, name="api_mark_all_read"),
]
