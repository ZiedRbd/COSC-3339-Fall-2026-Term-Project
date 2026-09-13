from django.shortcuts import render, redirect
from .forms import RegisterForm, IncidentForm, LoginForm
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from .models import User, Incident



# Each function shows one page
# The template file is created by whoever owns that page
def home(request):
    return render(request, "home.html")

def logout_view(request):
    logout(request)
    return redirect("home")

@never_cache
def login_page(request):
    """
    GET  - show the empty login form.
    POST - look up the user by email and password. If found log them
           in and send them to the incident list. If not show the page
           again with an error.
    """
    error = None
    if request.method == "POST":
        form =LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data.get("email")
            password = form.cleaned_data.get("password")
            user = authenticate(
                request,
                username=email,
                password=password
            )
            if user is not None:
                login(request, user)
                return redirect("landing")
            form.add_error(request, "Invalid email or password")
            return redirect("login")
    else:
        form = LoginForm()
    return render(request, "login.html", {"form": form})



def services(request):
    return render(request, "services.html")

@never_cache
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


@login_required
def landing(request):
    """
    Landing page after successful sign in
    """
    return render(request, "incidents/landing.html")

@login_required
def incident_list(request):
    """
    Show every incident that has not been soft deleted.
    Redirects to the login page if the user is not signed in.
    """
    incidents = Incident.objects.filter(is_deleted=False).only("title")
    return render(request, "incidents/list.html", {"incidents": incidents})


#ian
@login_required
def incident_form(request):
    if request.method == "POST":
        form = IncidentForm(request.POST)
        if form.is_valid():
            Incident.objects.create(
                title=form.cleaned_data['title'],
                description=form.cleaned_data['description'],
                service=form.cleaned_data['service'],
                reported_by=request.user,  # Injects the logged-in user
                priority=form.cleaned_data.get('priority', 'medium'),
                assigned_to=form.cleaned_data.get('assigned_to'),
                assigned_team=form.cleaned_data.get('assigned_team'),
            )
            return redirect('home')
    else:
        form = IncidentForm()
                
    return render(request, "incidents/form.html", {"form": form})

@login_required
def user_page(request):
    return render(request, "home.html")
