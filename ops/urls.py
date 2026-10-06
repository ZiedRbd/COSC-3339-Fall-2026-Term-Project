from django.urls import path
from . import views


# Each line maps an address to the function that handles it
urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("login/", views.login_page, name="login"),
    path("register/", views.register, name="register"),
    path("incidents/list", views.incident_list, name="incidents"),
    path("incidents/form", views.incident_form, name="form"),
    path("incidents/landing", views.landing, name="landing"),
    path("incidents/<int:pk>/edit/", views.incident_edit, name="incident_edit"),
    path("incidents/<int:pk>/delete/", views.incident_delete, name="incident_delete"),
    path("logout/", views.logout_view, name='logout'),
    path("incidents/<int:pk>/transition/", views.incident_transition, name="incident_transition"),
    path("incidents/<int:pk>/", views.incident_detail, name="incident_detail"),
    path("incidents/<int:pk>/comment/", views.incident_comment, name="incident_comment"),

]
