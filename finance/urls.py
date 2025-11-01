# finance/urls.py
from django.urls import path
from . import views

app_name = "finance"

urlpatterns = [
    path("", views.finance_home, name="home"),
    path("in-progress/", views.inprogress_requests, name="inprogress"),
    path("agreement/<int:agreement_id>/invoices/", views.agreement_invoices, name="agreement_invoices"),
    path("invoice/<int:pk>/paid/", views.mark_invoice_paid, name="mark_invoice_paid"),
    path("invoice/<int:pk>/", views.invoice_detail, name="invoice_detail"),

    # جديد
    path("reports/collections/", views.collections_report, name="collections_report"),
    path("reports/export.csv", views.export_invoices_csv, name="export_invoices_csv"),

    # سابقًا: للعميل والموظف
    path("client/payments/", views.client_payments, name="client_payments"),
    path("employee/dues/", views.employee_dues, name="employee_dues"),
]
