from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from .forms import IncidentForm, LoginForm, RegisterForm
from .models import Incident, Service, Team, User


def home(request):
    """Public landing page."""
    return render(request, "home.html")


def logout_view(request):
    """End the session and return to the home page."""
    logout(request)
    return redirect("home")


@never_cache
def login_page(request):
    """
    GET shows the login form. POST checks the email and password;
    on success the user is signed in and sent to the incident list,
    otherwise they return to the form with an error message.
    """
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data.get("email").lower()
            password = form.cleaned_data.get("password")
            # Returns the matching user, or None if the credentials are wrong
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                return redirect("incidents")
        messages.error(request, "Invalid email or password")
        return redirect("login")
    form = LoginForm()
    return render(request, "login.html", {"form": form})


def services(request):
    """
    List every team with its active services. The services are
    prefetched and attached to each team as `active_services` so the
    template can loop them without extra queries.
    """
    active_services = Prefetch(
        "service_set",
        queryset=Service.objects.filter(is_active=True),
        to_attr="active_services",
    )
    teams = Team.objects.prefetch_related(active_services)
    return render(request, "services.html", {"teams": teams})


@never_cache
def register(request):
    """
    GET shows the registration form. POST validates it; on success the
    user is created with a hashed password and sent to the login page,
    otherwise the form is shown again with its errors.
    """
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            # create_user hashes the password before saving
            User.objects.create_user(
                username=form.cleaned_data["email"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
            )
            messages.success(request, "Account created. Please log in.")
            return redirect("login")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


@login_required
def landing(request):
    """Dashboard shown after sign in with links to file or view tickets."""
    return render(request, "incidents/landing.html")


@login_required
def incident_list(request):
    """Active incidents, newest first. Soft-deleted tickets are excluded."""
    incidents = (
        Incident.objects.filter(is_deleted=False)
        .select_related("service", "reported_by")
        .order_by("-created_at")
    )
    return render(request, "incidents/list.html", {"incidents": incidents})


@login_required
def incident_form(request):
    """
    GET shows an empty ticket form. POST validates it and creates the
    incident, recording the signed-in user as the reporter.
    """
    if request.method == "POST":
        form = IncidentForm(request.POST)
        if form.is_valid():
            # reported_by comes from the session, not the form
            incident = Incident.objects.create(
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                building=form.cleaned_data["building"],
                room=form.cleaned_data["room"],
                service=form.cleaned_data["service"],
                priority=form.cleaned_data["priority"],
                reported_by=request.user,
            )
            messages.success(request, f"Ticket #{incident.pk} created")
            return redirect("incidents")
    else:
        form = IncidentForm()
    return render(request, "incidents/form.html", {"form": form})


@login_required
def incident_edit(request, pk):
    """
    GET shows the form pre-filled with the incident's current values.
    POST saves the changes and returns to the list. Returns 404 for an
    unknown or deleted incident.
    """
    incident = get_object_or_404(Incident, pk=pk, is_deleted=False)
    if request.method == "POST":
        form = IncidentForm(request.POST)
        if form.is_valid():
            incident.title = form.cleaned_data["title"]
            incident.description = form.cleaned_data["description"]
            incident.building = form.cleaned_data["building"]
            incident.room = form.cleaned_data["room"]
            incident.service = form.cleaned_data["service"]
            incident.priority = form.cleaned_data["priority"]
            incident.save()
            messages.success(request, f"Ticket #{incident.pk} updated")
            return redirect("incidents")
    else:
        # Pre-fill the form with the current values
        form = IncidentForm(initial={
            "title": incident.title,
            "description": incident.description,
            "building": incident.building,
            "room": incident.room,
            "service": incident.service,
            "priority": incident.priority,
        })
    return render(request, "incidents/form.html", {"form": form, "incident": incident})


@login_required
def incident_delete(request, pk):
    """
    Soft delete. Sets is_deleted so the ticket leaves the list while the
    row and its history are kept. Only responds to POST.
    """
    incident = get_object_or_404(Incident, pk=pk, is_deleted=False)
    if request.method == "POST":
        incident.is_deleted = True
        incident.save()
        messages.success(request, f"Ticket #{incident.pk} deleted")
    return redirect("incidents")
