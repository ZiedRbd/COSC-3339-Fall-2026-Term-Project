from django.shortcuts import render, redirect
from .forms import RegisterForm
from .models import User


# Each function shows one page
# The template file is created by whoever owns that page
def home(request):
    return render(request, "home.html")


def services(request):
    return render(request, "services.html")


def login_page(request):
    return render(request, "login.html")


def register(request):
    """
    Two situations land here.

    GET  - user just opened the page. Show an empty form.
    POST - user hit submit. Check the form. If it passes create the
           user with a hashed password and send them to login. If it
           fails show the page again with the errors filled in.
    """
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            User.objects.create_user(
                username=form.cleaned_data["email"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
            )
            return redirect("login")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


def incident_list(request):
    return render(request, "incidents/list.html")
