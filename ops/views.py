from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from .forms import IncidentForm, LoginForm, RegisterForm, ShiftForm
from .models import Incident, IncidentUpdate, Service, Shift, Team, TeamMember, User
from .scheduling import assign_on_creation, is_lead, on_call_roster, reassign, validate_schedule, who_is_on_call
from .timeline import log_event

# A ticket leaves Open only by being assigned, automatically on creation or
# by a team lead. Solvers move it along from there.
ALLOWED_TRANSITIONS = {
    "open": [],
    "assigned": ["in_progress"],
    "in_progress": ["resolved"],
    "resolved": ["closed", "open"],
    "closed": ["open"],
}


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
    Active incidents, newest first. Solvers see tickets assigned to any
    team they are on or lead. Reporters see their own on their profile.
    """
    # The full incident list is for solvers only. Reporters see their own
    # tickets on their profile page instead.
    if request.user.role != "solver":
        return redirect("profile")
    team_ids = TeamMember.objects.filter(user=request.user).values_list("team_id", flat=True)
    led_ids = Team.objects.filter(lead=request.user).values_list("id", flat=True)
    incidents = (
        Incident.objects.filter(is_deleted=False)
        .filter(Q(assigned_team_id__in=team_ids) | Q(assigned_team_id__in=led_ids))
        .select_related("service", "reported_by")
        .order_by("-created_at")
    )
    for i in incidents:
        i.next_states = ALLOWED_TRANSITIONS.get(i.status, [])
    return render(request, "incidents/list.html", {"incidents": incidents})

@login_required
def incident_form(request):
    """
    GET shows an empty ticket form. POST validates it and creates the
    incident, recording the signed-in user as the reporter. Solvers cannot
    file tickets; only reporters can.
    """
    if request.user.role == "solver":
        messages.error(request, "Solvers cannot file tickets")
        return redirect("incidents")
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
            team = service.owning_team
            log_event(incident, request.user, "created",
                      f"Ticket created and routed to {team.name}" if team else "Ticket created")
            # Hand the ticket to whoever is on call for that team right now
            assign_on_creation(incident)
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
    # While a ticket is assigned, only the assigned solver may edit it.
    # Before that, only the reporter who filed it may.
    if incident.assigned_to_id:
        if request.user.id != incident.assigned_to_id:
            messages.error(request, "Only the assigned solver can edit this ticket")
            return redirect("incident_detail", pk=incident.pk)
    elif request.user.id != incident.reported_by_id:
        messages.error(request, "Only the reporter can edit a ticket nobody is assigned to")
        return redirect("incident_detail", pk=incident.pk)
    if request.method == "POST":
        # The service cannot be changed on edit; force the existing one.
        data = request.POST.copy()
        data["service"] = str(incident.service_id)
        form = IncidentForm(data)
        if form.is_valid():
            # Remember the old values so we can log exactly what changed.
            old = {
                "Title": incident.title,
                "Description": incident.description,
                "Building": incident.building or "(none)",
                "Room": incident.room or "(none)",
            }
            old_severity = incident.priority
            incident.title = form.cleaned_data["title"]
            incident.description = form.cleaned_data["description"]
            incident.building = form.cleaned_data["building"]
            incident.room = form.cleaned_data["room"]
            incident.priority = form.cleaned_data["priority"]
            incident.save()
            # Severity change is its own timeline tag
            if old_severity != incident.priority:
                log_event(incident, request.user, "severity",
                          f"Severity changed from {old_severity} to {incident.priority}")
            # One timeline entry per changed detail field, showing old to new
            new = {
                "Title": incident.title,
                "Description": incident.description,
                "Building": incident.building or "(none)",
                "Room": incident.room or "(none)",
            }
            for field in old:
                if old[field] != new[field]:
                    log_event(incident, request.user, "edit",
                              f"{field} changed from \"{old[field]}\" to \"{new[field]}\"")
            messages.success(request, f"Ticket #{incident.pk} updated")
            return redirect("incident_detail", pk=incident.pk)
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
    # Solvers work tickets, they do not remove them. Only the reporter deletes.
    if request.user.role == "solver":
        messages.error(request, "Solvers cannot delete tickets")
        return redirect("incident_detail", pk=incident.pk)
    if not _can_access_incident(request.user, incident):
        messages.error(request, "You do not have access to that ticket")
        return redirect("profile")
    if request.method == "POST":
        incident.is_deleted = True
        incident.save()
        messages.success(request, f"Ticket #{incident.pk} deleted")
    return redirect("profile")

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
    team_ids = TeamMember.objects.filter(user=request.user).values_list("team_id", flat=True)
    # Tickets involving the user: ones they filed or ones on their team(s).
    involving = Incident.objects.filter(is_deleted=False).filter(
        Q(reported_by=request.user) | Q(assigned_team_id__in=team_ids)
    ).distinct()
    filed = Incident.objects.filter(reported_by=request.user, is_deleted=False)
    # Solvers see the teams they are on and who else is on each team.
    my_teams = []
    if request.user.role == "solver":
        for team in Team.objects.filter(teammember__user=request.user):
            team.members = [tm.user for tm in TeamMember.objects.filter(team=team).select_related("user")]
            my_teams.append(team)
    # Newest first, so each column reads in date order
    return render(request, "profile.html", {
        "active_incidents": involving.exclude(status__in=["resolved", "closed"]).order_by("-created_at"),
        "closed_incidents": involving.filter(status__in=["resolved", "closed"]).order_by("-created_at"),
        "filed_incidents": filed.order_by("-created_at"),
        "my_teams": my_teams,
    })


def _can_access_incident(user, incident):
    """
    A user may access an incident if they reported it, or they are a solver
    on the team it is assigned to, or they lead that team.
    """
    if incident.reported_by_id == user.id:
        return True
    if user.role == "solver" and incident.assigned_team_id:
        if TeamMember.objects.filter(user=user, team_id=incident.assigned_team_id).exists():
            return True
        return Team.objects.filter(id=incident.assigned_team_id, lead=user).exists()
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

    if request.method != "POST":
        return redirect("incident_detail", pk=pk)

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
@never_cache
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
    team = incident.assigned_team
    on_call = who_is_on_call(team) if team else None
    can_reassign = (
        team is not None and is_lead(request.user, team)
        and incident.status not in ("resolved", "closed")
        and on_call is not None and on_call != incident.assigned_to
    )
    can_edit = (
        incident.assigned_to_id == request.user.id
        or (incident.assigned_to_id is None and incident.reported_by_id == request.user.id)
    )
    return render(request, "incidents/detail.html", {
        "incident": incident,
        "timeline": timeline,
        "on_call": on_call,
        "can_reassign": can_reassign,
        "can_edit": can_edit,
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


@login_required
def incident_reassign(request, pk):
    """
    A team lead hands the ticket to whoever is on call for its team right
    now. POST only. The rules live in scheduling.reassign.
    """
    incident = get_object_or_404(Incident, pk=pk, is_deleted=False)
    if request.method == "POST":
        on_call = who_is_on_call(incident.assigned_team) if incident.assigned_team_id else None
        problem = reassign(incident, on_call, request.user)
        if problem:
            messages.error(request, problem)
        else:
            messages.success(request, f"Ticket #{incident.pk} reassigned to "
                                      f"{on_call.first_name} {on_call.last_name}")
    return redirect("incident_detail", pk=pk)


def _future_shifts(team):
    """Shifts still running or yet to come, earliest first."""
    return Shift.objects.filter(team=team, ends_at__gt=timezone.now()).select_related("solver").order_by("starts_at")


def _lead_only(request, team):
    """The redirect to send a non-lead away with, or None when they lead the team."""
    if is_lead(request.user, team):
        return None
    messages.error(request, f"Only the lead of {team.name} can edit its schedule")
    return redirect("profile")


@login_required
def schedule(request, team_id):
    """
    One team's on-call schedule: the upcoming shifts and a form to add one.
    Only the team's lead gets in. A new shift is checked together with the
    rest of the future schedule, so a gap or an overlap is refused with a
    message naming the day and the window.
    """
    team = get_object_or_404(Team, pk=team_id)
    denied = _lead_only(request, team)
    if denied:
        return denied
    if request.method == "POST":
        form = ShiftForm(team, request.POST)
        if form.is_valid():
            shift = form.save(commit=False)
            shift.team = team
            shift.created_by = request.user
            problems = validate_schedule(team, list(_future_shifts(team)) + [shift])
            if problems:
                for problem in problems:
                    messages.error(request, problem)
            else:
                shift.save()
                messages.success(request, "Shift added")
                return redirect("schedule", team_id=team.pk)
    else:
        form = ShiftForm(team)
    return render(request, "schedule.html", {
        "team": team, "form": form, "shifts": _future_shifts(team), "editing": None,
        "open_form": request.method == "POST",
    })


@login_required
def shift_edit(request, team_id, shift_id):
    """Change one upcoming shift. Same checks as adding one."""
    team = get_object_or_404(Team, pk=team_id)
    shift = get_object_or_404(Shift, pk=shift_id, team=team)
    denied = _lead_only(request, team)
    if denied:
        return denied
    if request.method == "POST":
        form = ShiftForm(team, request.POST, instance=shift)
        if form.is_valid():
            changed = form.save(commit=False)
            others = [s for s in _future_shifts(team) if s.pk != shift.pk]
            problems = validate_schedule(team, others + [changed])
            if problems:
                for problem in problems:
                    messages.error(request, problem)
            else:
                changed.save()
                messages.success(request, "Shift updated")
                return redirect("schedule", team_id=team.pk)
    else:
        form = ShiftForm(team, instance=shift)
    return render(request, "schedule.html", {
        "team": team, "form": form, "shifts": _future_shifts(team), "editing": shift,
        "open_form": True,
    })


@login_required
def shift_delete(request, team_id, shift_id):
    """Remove one upcoming shift, unless that would leave a hole in the cover."""
    team = get_object_or_404(Team, pk=team_id)
    shift = get_object_or_404(Shift, pk=shift_id, team=team)
    denied = _lead_only(request, team)
    if denied:
        return denied
    if request.method == "POST":
        others = [s for s in _future_shifts(team) if s.pk != shift.pk]
        problems = validate_schedule(team, others)
        if problems:
            for problem in problems:
                messages.error(request, problem)
        else:
            shift.delete()
            messages.success(request, "Shift removed")
    return redirect("schedule", team_id=team.pk)


@login_required
def calendar(request):
    """
    One week of on-call cover: a row per team, a column per day, and in
    each cell who covers which hours. Solvers see every team they are on
    or lead, and a lead gets a link to edit the schedule of the teams they
    lead. Reporters have no schedule to look at and are sent to their
    profile. The week starts on Monday; ?start=YYYY-MM-DD picks another.
    """
    if request.user.role != "solver":
        messages.error(request, "The calendar is for solvers")
        return redirect("profile")
    today = timezone.localdate()
    try:
        first_day = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        first_day = today - timedelta(days=today.weekday())
    days = [first_day + timedelta(days=i) for i in range(7)]
    week_start = timezone.make_aware(datetime.combine(first_day, time.min))
    week_end = week_start + timedelta(days=7)
    now = timezone.now()

    teams = (Team.objects.filter(Q(teammember__user=request.user) | Q(lead=request.user))
             .distinct().order_by("name"))
    rows = []
    for team in teams:
        cells = [[] for _ in days]
        for shift in on_call_roster(team, week_start, week_end):
            # A shift can cross midnight, so clip it to each day it touches
            for i, day in enumerate(days):
                day_start = timezone.make_aware(datetime.combine(day, time.min))
                day_end = day_start + timedelta(days=1)
                if shift.starts_at < day_end and shift.ends_at > day_start:
                    begins = max(shift.starts_at, day_start)
                    ends = min(shift.ends_at, day_end)
                    end_label = "24:00" if ends == day_end else f"{timezone.localtime(ends):%H:%M}"
                    cells[i].append({
                        "when": f"{timezone.localtime(begins):%H:%M} to {end_label}",
                        "who": f"{shift.solver.first_name} {shift.solver.last_name}",
                        # Already over: shown greyed out, and not on the schedule page
                        "past": ends <= now,
                    })
        rows.append({"team": team, "cells": cells, "can_edit": is_lead(request.user, team)})

    return render(request, "calendar.html", {
        "days": days, "rows": rows, "today": today,
        "prev": (first_day - timedelta(days=7)).isoformat(),
        "next": (first_day + timedelta(days=7)).isoformat(),
    })
