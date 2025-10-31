from django.urls import path
from .views import whatsapp_redirect_user

app_name = "core"

urlpatterns = [
    path("w/u/<int:user_id>/", whatsapp_redirect_user, name="whatsapp_user"),
]
