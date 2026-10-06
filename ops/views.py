from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from .forms import IncidentForm, LoginForm, RegisterForm
from .models import Incident, IncidentUpdate, Service, Team, TeamMember, User

ALLOWED_TRANSITIONS = {
    "open": ["acknowledged"],
    "acknowledged": ["in_progress"],
    "in_progress": ["resolved"],
    "resolved": ["closed", "open"],
    "closed": ["open"],
}


def log_event(incident, author, update_type, body, old_status="", new_status=""):
    """Record one event on an incident's timeline."""
    IncidentUpdate.objects.create(
        incident=incident, author=author, update_type=update_type,
        body=body, old_status=old_status, new_status=new_status,
    )


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
    """
    Active incidents, newest first. Solvers see tickets assigned to any of
    their teams; reporters see the tickets they filed.
    """
    incidents = Incident.objects.filter(is_deleted=False)
    if request.user.role == "solver":
        # Solvers see tickets assigned to their teams plus any they filed
        team_ids = TeamMember.objects.filter(user=request.user).values_list("team_id", flat=True)
        incidents = incidents.filter(Q(assigned_team_id__in=team_ids) | Q(reported_by=request.user))
    else:
        incidents = incidents.filter(reported_by=request.user)
    incidents = incidents.select_related("service", "reported_by").order_by("-created_at")
    for i in incidents:
        i.next_states = ALLOWED_TRANSITIONS.get(i.status, [])
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
            service = form.cleaned_data["service"]
            incident = Incident.objects.create(
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                building=form.cleaned_data["building"],
                room=form.cleaned_data["room"],
                service=service,
                priority=form.cleaned_data["priority"],
                reported_by=request.user,
                # Route the ticket to the team that owns the service
                assigned_team=service.owning_team,
            )
            log_event(incident, request.user, "created",
                      f"Ticket created and assigned to {service.owning_team.name}")
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
    incident = get_object_or_404(Incident, Q(reported_by=request.user) | Q(assigned_to=request.user), pk=pk, is_deleted=False)
    if request.method == "POST":
        form = IncidentForm(request.POST)
        if form.is_valid():
            old_team = incident.assigned_team
            old_severity = incident.priority
            incident.title = form.cleaned_data["title"]
            incident.description = form.cleaned_data["description"]
            incident.building = form.cleaned_data["building"]
            incident.room = form.cleaned_data["room"]
            incident.service = form.cleaned_data["service"]
            incident.assigned_team = form.cleaned_data["service"].owning_team
            incident.priority = form.cleaned_data["priority"]
            incident.save()
            new_team = incident.service.owning_team
            if old_team != new_team:
                log_event(incident, request.user, "assignment",
                          f"Reassigned from {old_team} to {new_team}")
            if old_severity != incident.priority:
                log_event(incident, request.user, "severity",
                          f"Severity changed from {old_severity} to {incident.priority}")
            log_event(incident, request.user, "edit", "Ticket details updated")
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

@login_required
def profile(request):
    """
    Show the logged-in user's profile: identity, an editable bio, and their
    incidents split into active, closed/resolved, and all filed.
    """
    if request.method == "POST":
        request.user.bio = request.POST.get("bio", "")
        request.user.save()
        return redirect("profile")
    user_incidents = Incident.objects.filter(reported_by=request.user, is_deleted=False)
    return render(request, "profile.html", {
        "active_incidents": user_incidents.exclude(status__in=["resolved", "closed"]),
        "closed_incidents": user_incidents.filter(status__in=["resolved", "closed"]),
        "filed_incidents": user_incidents,
    })


def _can_access_incident(user, incident):
    """
    A user may access an incident if they reported it, or they are a solver
    on the team the incident is assigned to.
    """
    if incident.reported_by_id == user.id:
        return True
    if user.role == "solver" and incident.assigned_team_id:
        return TeamMember.objects.filter(user=user, team_id=incident.assigned_team_id).exists()
    return False


@login_required
def incident_transition(request, pk):
    """
    Move an incident to a new status. Only solvers may do this, and only
    along a transition the state machine allows. Every successful move is
    recorded as an IncidentUpdate row for the timeline.
    """
    incident = get_object_or_404(Incident, pk=pk, is_deleted=False)
    if not _can_access_incident(request.user, incident):
        messages.error(request, "You do not have access to that ticket")
        return redirect("incidents")

    #only solvers change state
    if request.user.role != "solver":
        messages.error(request, "Only solvers can change incident status")
        return redirect("incident_detail", pk=pk)

    new_status = request.POST.get("new_status")
    old_status = incident.status

    # the move must be legal from the current state
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, []):
        messages.error(request, f"Cannot move from {old_status} to {new_status}")
        return redirect("incident_detail", pk=pk)

    # Apply the change and log it to the timeline
    incident.status = new_status
    incident.save()
    log_event(
        incident, request.user, "status_change",
        f"Status changed from {old_status} to {new_status}",
        old_status=old_status, new_status=new_status,
    )
    messages.success(request, f"Ticket #{incident.pk} moved to {new_status}")
    return redirect("incident_detail", pk=pk)


@login_required
def incident_detail(request, pk):
    """
    Show one incident with its full timeline. The timeline is every
    IncidentUpdate row for this ticket, oldest first.
    """
    incident = get_object_or_404(Incident, pk=pk, is_deleted=False)
    if not _can_access_incident(request.user, incident):
        messages.error(request, "You do not have access to that ticket")
        return redirect("incidents")
    timeline = (
        IncidentUpdate.objects.filter(incident=incident)
        .select_related("author")
        .order_by("created_at")
    )
    incident.next_states = ALLOWED_TRANSITIONS.get(incident.status, [])
    return render(request, "incidents/detail.html", {
        "incident": incident,
        "timeline": timeline,
    })


@login_required
def incident_comment(request, pk):
    """
    Add a comment to an incident. A reporter adds a comment, a solver adds
    a note. Both are stored as IncidentUpdate rows and shown in the timeline;
    neither side can edit the other's entries.
    """
    incident = get_object_or_404(Incident, pk=pk, is_deleted=False)
    if not _can_access_incident(request.user, incident):
        messages.error(request, "You do not have access to that ticket")
        return redirect("incidents")
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if len(body) > 1000:
            messages.error(request, "Comment is too long (1000 characters max)")
            return redirect("incident_detail", pk=pk)
        if body:
            update_type = "solver_note" if request.user.role == "solver" else "comment"
            log_event(incident, request.user, update_type, body)
            messages.success(request, "Comment added")
    return redirect("incident_detail", pk=pk)
