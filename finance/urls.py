from django.urls import path
from django.http import HttpResponse

app_name = "finance"

def index(request):
    return HttpResponse("Finance OK")

urlpatterns = [
    path("", index, name="index"),
]
