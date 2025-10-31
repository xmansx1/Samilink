from django.urls import path
from django.http import HttpResponse

app_name = "uploads"

def index(request):
    return HttpResponse("Uploads OK")

urlpatterns = [
    path("", index, name="index"),
]
