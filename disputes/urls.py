from django.urls import path
from django.http import HttpResponse

app_name = "disputes"

def index(request):
    return HttpResponse("Disputes OK")

urlpatterns = [
    path("", index, name="index"),
]
