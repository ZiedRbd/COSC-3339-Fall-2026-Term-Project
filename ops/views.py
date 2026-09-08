from django.shortcuts import render


# Each function shows one page
# The template file is created by whoever owns that page
def home(request):
    return render(request, "home.html")


def services(request):
    return render(request, "services.html")


def login_page(request):
    return render(request, "login.html")


def register(request):
    return render(request, "register.html")


def incident_list(request):
    return render(request, "incidents/list.html")
