# website/views.py
from django.views.generic import TemplateView

class HomeView(TemplateView):
    template_name = "website/home.html"

class ServicesView(TemplateView):
    template_name = "website/services.html"
from django.views.generic import TemplateView

class HomeView(TemplateView):
    template_name = "website/home.html"

class ServicesView(TemplateView):
    template_name = "website/services.html"

class PrivacyView(TemplateView):
    template_name = "website/privacy.html"

class TermsView(TemplateView):
    template_name = "website/terms.html"
