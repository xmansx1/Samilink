# website/urls.py
from django.urls import path
from .views import HomeView, ServicesView, PrivacyView, TermsView

app_name = "website"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("services/", ServicesView.as_view(), name="services"),
    path("privacy/", PrivacyView.as_view(), name="privacy"),
    path("terms/", TermsView.as_view(), name="terms"),
]
