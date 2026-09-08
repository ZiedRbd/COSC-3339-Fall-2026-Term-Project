from django.urls import path
from . import views


# Each line maps an address to the function that handles it
urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("login/", views.login_page, name="login"),
    path("register/", views.register, name="register"),
    path("incidents/", views.incident_list, name="incidents"),
]
