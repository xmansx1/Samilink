from django.urls import path
from .views import EmployeeListView, EmployeeDetailView, whatsapp_redirect

app_name = "profiles"

urlpatterns = [
    path("", EmployeeListView.as_view(), name="employees_list"),
    path("<slug:slug>/", EmployeeDetailView.as_view(), name="employee_detail"),
    path("w/emp/<int:user_id>/", whatsapp_redirect, name="whatsapp_redirect"),
]
