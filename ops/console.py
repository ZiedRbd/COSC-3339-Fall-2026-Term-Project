"""
The administrator console: one page with a tab for each part of the
system. Every action opens in the same dialog on that page. The dialog's
content is a small piece of HTML this module returns, and the page asks
for it without leaving. The rules themselves live in ops/removal.py and
ops/overrides.py: the functions here only show them and call them.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .access import can_override, is_admin
from .console_forms import BuildingForm, ServiceForm, TeamForm, UserForm, full_name
from .lifecycle import STATUS_LABELS
from .models import Building, EscalationTier, Incident, Service, Team, TeamMember, User
from .overrides import HELD, override, override_warnings, possible_solvers
from .removal import (appoint_lead, holdings, leave_team, move_services, remove_building, remove_service,
                      remove_team, remove_ticket, remove_user, replace_in_tier, restore_building, restore_service,
                      restore_team, restore_ticket, restore_user, transfer_shifts)
from .scheduling import active_ticket_count, ensure_policy
from .timeline import MIN_REASON, clean_reason

TABS = [("users", "Users"), ("teams", "Teams"), ("services", "Services"), ("buildings", "Buildings"),
        ("tickets", "Tickets"), ("removed", "Removed")]
NEWEST_TICKETS = 150
UNFINISHED = ("open",) + HELD


def admin_only(view):
    """The console does not exist for anyone who is not an administrator."""
    @login_required
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not is_admin(request.user):
            raise Http404
        return view(request, *args, **kwargs)
    return guarded


def _finished(request, *sentences):
    """The dialog's work is done: the sentences show on the page once it has loaded again."""
    for sentence in sentences:
        messages.success(request, sentence)
    response = HttpResponse(status=204)
    response["X-Console-Done"] = "1"
    return response


def _form_dialog(request, form, title, submit):
    return render(request, "console/_form.html", {"form": form, "title": title, "submit": submit, "action": request.path})


def _solvers():
    return User.objects.filter(role="solver", is_active=True).order_by("first_name", "last_name", "pk")


def _role_label(user, led_team_ids):
    if user.is_superuser:
        return "Administrator"
    if user.role == "solver" and user.pk in led_team_ids:
        return "Team lead"
    return user.role.capitalize()


# ── The page ──────────────────────────────────────────────────────────


@admin_only
def console(request):
    leads = set(Team.objects.filter(is_active=True, lead__isnull=False).values_list("lead_id", flat=True))
    users = [
        {"user": user, "role": _role_label(user, leads),
         "teams": [membership.team.name for membership in user.teammember_set.all() if membership.team.is_active]}
        for user in User.objects.filter(is_active=True).prefetch_related("teammember_set__team")
                        .order_by("first_name", "last_name", "pk")]
    teams = [
        {"team": team,
         "members": [full_name(membership.user) for membership in team.teammember_set.all()
                     if membership.user.is_active and membership.user.role == "solver"],
         "services": [service.name for service in team.service_set.all() if service.is_active]}
        for team in Team.objects.filter(is_active=True).select_related("lead")
                        .prefetch_related("teammember_set__user", "service_set").order_by("name")]
    services = (Service.objects.filter(is_active=True).select_related("owning_team").order_by("name")
                .annotate(unfinished=Count("incident", filter=Q(incident__is_deleted=False,
                                                                incident__status__in=UNFINISHED))))
    every_ticket = Incident.objects.filter(is_deleted=False)
    tickets = (every_ticket.select_related("service", "assigned_to", "assigned_team", "reported_by")
               .order_by("-created_at")[:NEWEST_TICKETS])
    removed = {
        "users": User.objects.filter(is_active=False).select_related("removed_by").order_by("-removed_at"),
        "teams": Team.objects.filter(is_active=False).select_related("removed_by", "lead").order_by("-removed_at"),
        "services": Service.objects.filter(is_active=False).select_related("removed_by", "owning_team").order_by("-removed_at"),
        "buildings": Building.objects.filter(is_active=False).select_related("removed_by").order_by("-removed_at"),
        "tickets": Incident.objects.filter(is_deleted=True).select_related("removed_by", "service").order_by("-removed_at"),
    }
    buildings = Building.objects.filter(is_active=True).order_by("name")
    counts = {"users": len(users), "teams": len(teams), "services": len(services), "buildings": buildings.count(),
              "tickets": every_ticket.count(), "removed": sum(rows.count() for rows in removed.values())}
    wanted = request.GET.get("tab")
    return render(request, "console/console.html", {
        "tabs": [{"key": key, "label": label, "count": counts[key]} for key, label in TABS],
        "open_tab": wanted if wanted in dict(TABS) else "users",
        "users": users, "teams": teams, "services": services, "buildings": buildings, "tickets": tickets,
        "ticket_total": counts["tickets"], "newest_tickets": NEWEST_TICKETS, "removed": removed,
        "removed_total": counts["removed"],
    })


# ── Users ─────────────────────────────────────────────────────────────


@admin_only
def user_add(request):
    form = UserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        return _finished(request, f"{full_name(user)} was added as {'an' if user.role == 'auditor' else 'a'} {user.role}.")
    return _form_dialog(request, form, "Add a user", "Add user")


@admin_only
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk, is_active=True)
    form = UserForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        return _finished(request, f"{full_name(user)} was updated.")
    return _form_dialog(request, form, f"Edit {full_name(user)}", "Save changes")


def _handover_step(request, user, by):
    """One hand-over in the dialog: shifts to the rest of a team, a new lead, or a new person in a tier."""
    step = request.POST.get("step")
    if step == "shifts":
        team = get_object_or_404(Team, pk=request.POST.get("team"))
        prefer = User.objects.filter(pk=request.POST.get("person") or 0).first()
        return transfer_shifts(user, team, by, prefer=prefer)
    if step == "lead":
        team = get_object_or_404(Team, pk=request.POST.get("team"))
        return appoint_lead(team, get_object_or_404(User, pk=request.POST.get("person") or 0), by)
    if step == "tier":
        tier = get_object_or_404(EscalationTier, pk=request.POST.get("tier"))
        return replace_in_tier(tier, get_object_or_404(User, pk=request.POST.get("person") or 0), by)
    return None


def _handover_dialog(request, user, team, outcome):
    """What this person still holds, each with a way to hand it over, and the last step once nothing is left."""
    held = holdings(user, team)
    leads_this_team = team is not None and team.lead_id == user.pk
    if team is not None:
        # A lead may lead a team without being on it, so leading it is nothing to hand over here
        held["led"] = []
    everyone = list(_solvers().exclude(pk=user.pk))
    tickets = Incident.objects.filter(assigned_to=user, status__in=HELD, is_deleted=False)
    if team is not None:
        # A lead keeps the tickets of the team they lead when they come off it
        tickets = tickets.none() if leads_this_team else tickets.filter(assigned_team=team)

    def teammates(of_team):
        on_team = set(TeamMember.objects.filter(team=of_team).values_list("user_id", flat=True))
        return [person for person in everyone if person.pk in on_team]

    return render(request, "console/_handover.html", {
        "person": user, "name": full_name(user), "team": team, "outcome": outcome, "action": request.path,
        "shifts": [{"team": shift_team, "count": count, "others": teammates(shift_team)}
                   for shift_team, count in held["shifts"].items()],
        "led": [{"team": led_team, "candidates": everyone} for led_team in held["led"]],
        "tiers": [{"tier": tier, "candidates": teammates(tier.team)} for tier in held["tiers"]],
        "clear": not (held["shifts"] or held["led"] or held["tiers"]),
        "unfinished": tickets.count(), "leads_this_team": leads_this_team,
    })


@admin_only
def user_remove(request, pk):
    user = get_object_or_404(User, pk=pk, is_active=True)
    if user.pk == request.user.pk:
        return render(request, "console/_confirm.html", {
            "title": "Remove your own account", "refusals": ["You cannot remove the account you are signed in with."]})
    outcome = None
    if request.method == "POST":
        if request.POST.get("step") == "finish":
            outcome = remove_user(user, request.user)
            if outcome.ok:
                return _finished(request, *outcome.messages)
        else:
            outcome = _handover_step(request, user, request.user)
    return _handover_dialog(request, user, None, outcome)


# ── Teams ─────────────────────────────────────────────────────────────


@admin_only
def team_add(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        team = Team.objects.create(name=form.cleaned_data["name"], description=form.cleaned_data["description"],
                                   lead=form.cleaned_data["lead"])
        ensure_policy(team)
        return _finished(request, f"{team.name} was added with {full_name(team.lead)} as its lead. "
                                  "Add its solvers from Members and lead.")
    return _form_dialog(request, form, "Add a team", "Add team")


@admin_only
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk, is_active=True)
    form = TeamForm(request.POST or None, team=team)
    if request.method == "POST" and form.is_valid():
        team.name, team.description = form.cleaned_data["name"], form.cleaned_data["description"]
        team.save(update_fields=["name", "description"])
        return _finished(request, f"{team.name} was updated.")
    return _form_dialog(request, form, f"Edit {team.name}", "Save changes")


@admin_only
def team_members(request, pk):
    """Who is on the team and who leads it. A removed team can get a new lead here, which it needs before it is restored."""
    team = get_object_or_404(Team.objects.select_related("lead"), pk=pk)
    outcome = None
    if request.method == "POST":
        step = request.POST.get("step")
        person = get_object_or_404(User, pk=request.POST.get("person") or 0)
        if step == "add" and person.role == "solver" and person.is_active:
            TeamMember.objects.get_or_create(user=person, team=team)
            outcome = {"ok": True, "messages": [f"{full_name(person)} is now on {team.name}."]}
        elif step == "lead":
            outcome = appoint_lead(team, person, request.user)
            team.refresh_from_db()
    members = list(_solvers().filter(teammember__team=team))
    return render(request, "console/_members.html", {
        "team": team, "members": members, "outcome": outcome, "action": request.path,
        "to_add": _solvers().exclude(teammember__team=team),
        "lead_candidates": _solvers().exclude(pk=team.lead_id or 0),
    })


@admin_only
def team_leave(request, pk, user_pk):
    """A solver comes off one team, after handing over what they hold on it."""
    team = get_object_or_404(Team, pk=pk)
    user = get_object_or_404(User, pk=user_pk)
    outcome = None
    if request.method == "POST":
        if request.POST.get("step") == "finish":
            outcome = leave_team(user, team, request.user)
            if outcome.ok:
                return _finished(request, *outcome.messages)
        else:
            outcome = _handover_step(request, user, request.user)
    return _handover_dialog(request, user, team, outcome)


@admin_only
def team_remove(request, pk):
    team = get_object_or_404(Team, pk=pk, is_active=True)
    outcome = None
    if request.method == "POST":
        if request.POST.get("step") == "move":
            outcome = move_services(team, get_object_or_404(Team, pk=request.POST.get("team") or 0, is_active=True),
                                    request.user)
        else:
            outcome = remove_team(team, request.user)
            if outcome.ok:
                return _finished(request, *outcome.messages)
    services = Service.objects.filter(owning_team=team, is_active=True).order_by("name")
    unfinished = Incident.objects.filter(assigned_team=team, is_deleted=False, status__in=UNFINISHED).count()
    return render(request, "console/_remove_team.html", {
        "team": team, "outcome": outcome, "action": request.path, "services": services, "unfinished": unfinished,
        "clear": not services and not unfinished,
        "other_teams": Team.objects.filter(is_active=True).exclude(pk=team.pk).order_by("name"),
    })


# ── Services and buildings ────────────────────────────────────────────


@admin_only
def service_add(request):
    form = ServiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = form.save()
        return _finished(request, f"{service.name} was added for {service.owning_team.name}.")
    return _form_dialog(request, form, "Add a service", "Add service")


@admin_only
def service_edit(request, pk):
    service = get_object_or_404(Service, pk=pk, is_active=True)
    form = ServiceForm(request.POST or None, service=service)
    if request.method == "POST" and form.is_valid():
        form.save()
        return _finished(request, f"{service.name} was updated.")
    return _form_dialog(request, form, f"Edit {service.name}", "Save changes")


@admin_only
def building_add(request):
    form = BuildingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        building = form.save()
        return _finished(request, f"{building.name} was added.")
    return _form_dialog(request, form, "Add a building", "Add building")


@admin_only
def building_edit(request, pk):
    building = get_object_or_404(Building, pk=pk, is_active=True)
    form = BuildingForm(request.POST or None, building=building)
    if request.method == "POST" and form.is_valid():
        form.save()
        return _finished(request, f"{building.name} was updated.")
    return _form_dialog(request, form, f"Edit {building.name}", "Save changes")


def _confirm_removal(request, title, consequences, rule, submit, needs_reason=False):
    """A dialog that says what removing this thing means, and removes it when the administrator confirms."""
    refusals = []
    if request.method == "POST":
        outcome = rule(request.POST.get("reason", "")) if needs_reason else rule()
        if outcome.ok:
            return _finished(request, *outcome.messages)
        refusals = outcome.messages
    return render(request, "console/_confirm.html", {
        "title": title, "consequences": consequences, "refusals": refusals, "submit": submit,
        "needs_reason": needs_reason, "reason": request.POST.get("reason", ""), "action": request.path})


@admin_only
def service_remove(request, pk):
    service = get_object_or_404(Service, pk=pk, is_active=True)
    unfinished = Incident.objects.filter(service=service, is_deleted=False, status__in=UNFINISHED).count()
    consequences = ["Nobody can file a new ticket for it."]
    if unfinished:
        consequences.append("Its 1 unfinished ticket carries on as it is." if unfinished == 1
                            else f"Its {unfinished} unfinished tickets carry on as they are.")
    consequences.append("It stays in the history and can be restored from the Removed tab.")
    return _confirm_removal(request, f"Remove {service.name}", consequences,
                            lambda: remove_service(service, request.user), "Remove service")


@admin_only
def building_remove(request, pk):
    building = get_object_or_404(Building, pk=pk, is_active=True)
    return _confirm_removal(
        request, f"Remove {building.name}",
        ["It leaves the ticket form.", "Tickets that already name it keep it.",
         "It can be restored from the Removed tab."],
        lambda: remove_building(building, request.user), "Remove building")


# ── Tickets ───────────────────────────────────────────────────────────


@admin_only
def ticket_remove(request, pk):
    incident = get_object_or_404(Incident.objects.select_related("assigned_to", "reported_by"), pk=pk, is_deleted=False)
    told = "Its reporter is told."
    if incident.assigned_to is not None and incident.status in HELD:
        told = f"Its reporter and {full_name(incident.assigned_to)}, who holds it, are told."
    return _confirm_removal(
        request, f"Remove ticket {incident.pk}",
        [f"It leaves every list. {told}", "The reason goes on its timeline.",
         "It can be restored from the Removed tab."],
        lambda reason: remove_ticket(incident, request.user, reason), "Remove ticket", needs_reason=True)


@login_required
@never_cache
def ticket_override(request, pk):
    """
    The override dialog, for an administrator on any ticket and for a
    lead on the tickets of their own teams. Choices that step over a
    rule are shown as warnings first and happen only once confirmed.
    """
    incident = get_object_or_404(Incident.objects.select_related("service", "assigned_to", "assigned_team"), pk=pk)
    if not can_override(request.user, incident):
        raise Http404
    solvers = possible_solvers(incident)
    refusals, warnings = [], []
    chosen = {"status": request.POST.get("new_status", ""), "solver": request.POST.get("new_solver", ""),
              "reason": request.POST.get("reason", "")}
    # A confirmation counts only for the choices it was given for, not for ones changed afterwards
    signature = f"{chosen['status']}|{chosen['solver']}"
    if request.method == "POST":
        new_status = chosen["status"] or None
        new_solver = next((person for person in solvers if str(person.pk) == chosen["solver"]), None)
        # With no reason, or one too short, the override is refused outright, so there is nothing to warn about yet
        if len(clean_reason(chosen["reason"])) >= MIN_REASON and request.POST.get("confirmed") != signature:
            warnings = override_warnings(incident, new_status=new_status, new_solver=new_solver)
        if not warnings:
            outcome = override(incident, request.user, chosen["reason"], new_status=new_status, new_solver=new_solver)
            if outcome.ok:
                return _finished(request, *outcome.messages)
            refusals = outcome.messages
    return render(request, "console/_override.html", {
        "incident": incident, "action": request.path, "chosen": chosen, "refusals": refusals, "warnings": warnings,
        "signature": signature,
        "statuses": [(status, label) for status, label in STATUS_LABELS.items() if status != incident.status],
        "status_label": STATUS_LABELS.get(incident.status, incident.status),
        "solvers": [{"person": person, "held": active_ticket_count(person), "selected": str(person.pk) == chosen["solver"]}
                    for person in solvers if person.pk != incident.assigned_to_id],
    })


# ── Restore ───────────────────────────────────────────────────────────

RESTORE = {
    "user": (User, restore_user), "team": (Team, restore_team), "service": (Service, restore_service),
    "building": (Building, restore_building), "ticket": (Incident, restore_ticket),
}


@admin_only
@require_POST
def restore(request, kind, pk):
    if kind not in RESTORE:
        raise Http404
    model, rule = RESTORE[kind]
    outcome = rule(get_object_or_404(model, pk=pk), request.user)
    for sentence in outcome.messages:
        (messages.success if outcome.ok else messages.error)(request, sentence)
    return redirect(reverse("console") + "?tab=removed")
