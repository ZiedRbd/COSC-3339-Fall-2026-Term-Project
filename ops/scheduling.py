"""Who is on call, checking a schedule, and handing tickets to people."""
from django.utils import timezone

from .models import Incident, Shift, TeamMember
from .timeline import log_event


def who_is_on_call(team, at=None):
    """
    The person on call for a team at a given moment, or None if nobody is.
    A shift runs from starts_at up to ends_at, and the ends_at moment
    itself already belongs to the next shift, so a ticket filed at
    exactly 16:00 goes to whoever starts at 16:00. Anyone who is
    deactivated, is not a solver, or is no longer on the team is skipped
    even if a shift names them.
    """
    if at is None:
        at = timezone.now()
    shift = (
        Shift.objects.filter(
            team=team,
            starts_at__lte=at,
            ends_at__gt=at,
            solver__is_active=True,
            solver__role="solver",
            solver__teammember__team=team,
        )
        .select_related("solver")
        .order_by("starts_at", "id")
        .first()
    )
    if shift is None:
        return None
    return shift.solver


def on_call_roster(team, window_start, window_end):
    """
    All shifts for a team that fall inside a time window, for example one
    week of the calendar. A shift counts if any part of it is inside the
    window, so a shift that starts before the window but ends inside it
    is included. The list is sorted by start time, so the first item is
    the shift that starts soonest.
    """
    return (
        Shift.objects.filter(
            team=team,
            starts_at__lt=window_end,
            ends_at__gt=window_start,
        )
        .select_related("solver")
        .order_by("starts_at", "id")
    )


def assign_now(incident, by, at=None):
    """
    Hand an unassigned ticket to whoever is on call for the team that owns
    its service, and write what happened to the timeline either way. Used
    when a ticket is filed and when one is reopened. The ticket stays Open
    and unassigned when the service has no team or nobody is on call.
    Returns the solver it went to, or None.
    """
    team = incident.service.owning_team
    if team is None:
        log_event(incident, by, "assignment_failed",
                  f"Nobody is on call for {incident.service.name} right now, so this ticket is waiting to be assigned")
        return None
    incident.assigned_team = team
    solver = who_is_on_call(team, at)
    if solver is None:
        incident.save()
        log_event(incident, by, "assignment_failed",
                  f"Nobody is on call for {team.name} right now, so this ticket is waiting to be assigned")
        return None
    incident.assigned_to = solver
    incident.status = "assigned"
    incident.save()
    log_event(incident, by, "assignment",
              f"Assigned to {_full_name(solver)}, on call for {team.name}",
              new_assignee=solver)
    return solver


def assign_on_creation(incident):
    """A brand new ticket. The reporter filing it is recorded as the author."""
    return assign_now(incident, incident.reported_by, incident.created_at)


def assign_waiting(team, by=None):
    """
    Every Open, unassigned ticket of this team gets another chance at the
    solver on call right now. Runs when a schedule changes, when a solver
    opens the list, when a ticket is opened, and when shifts are seeded, so
    a ticket filed while nobody was on call is picked up as soon as someone
    is. Quiet when nobody is on call: the ticket already says it is waiting.
    Returns how many tickets were assigned.
    """
    solver = who_is_on_call(team)
    if solver is None:
        return 0
    waiting = Incident.objects.filter(assigned_team=team, status="open", assigned_to__isnull=True, is_deleted=False)
    count = 0
    for incident in waiting:
        incident.assigned_to = solver
        incident.status = "assigned"
        incident.save()
        log_event(incident, by or solver, "assignment",
                  f"Assigned to {_full_name(solver)}, on call for {team.name}",
                  new_assignee=solver)
        count += 1
    return count


def is_lead(user, team):
    """True when this user leads this team. One comparison, no query."""
    return team.lead_id == user.id


def _full_name(user):
    return f"{user.first_name} {user.last_name}".strip() or user.email


def _clock(t):
    t = timezone.localtime(t)
    return f"{t.hour}:{t.minute:02d}"


def _window(a, b):
    """A stretch of time in words, Chicago time: "Monday from 9:00 to 10:30"."""
    a_local, b_local = timezone.localtime(a), timezone.localtime(b)
    if a_local.date() == b_local.date():
        return f"{a_local:%A} from {_clock(a)} to {_clock(b)}"
    return f"{a_local:%A} {_clock(a)} to {b_local:%A} {_clock(b)}"


def _problem(what, a, b, from_now=False):
    """
    An error naming the day and the window, the way the spec asks:
    "Wednesday is missing coverage from 9:00 to 10:30", or across midnight
    "Missing coverage from Wednesday 22:00 to Thursday 6:00". A window that
    opens at this very moment says "from now (22:11)" so nobody thinks the
    check looked into the past.
    """
    a_local, b_local = timezone.localtime(a), timezone.localtime(b)
    if a_local.date() == b_local.date():
        opens = f"now ({_clock(a)})" if from_now else _clock(a)
        return f"{a_local:%A} is {what} from {opens} to {_clock(b)}"
    opens = f"now ({a_local:%A} {_clock(a)})" if from_now else f"{a_local:%A} {_clock(a)}"
    return f"{what.capitalize()} from {opens} to {b_local:%A} {_clock(b)}"


def validate_schedule(team, proposed, now=None):
    """
    Check a team's whole future schedule and return the list of problems,
    empty when it is fine. Shifts that already ended are ignored. Cover
    must run from now to the last shift with no gap and no overlap, one
    person may not cover two teams at once, and only solvers who are on
    the team may take a shift.
    """
    if now is None:
        now = timezone.now()
    errors = []
    for shift in proposed:
        if shift.ends_at <= shift.starts_at:
            errors.append(f"Shift on {timezone.localtime(shift.starts_at):%A} ends before it starts")
    # Inverted shifts are reported above and kept out of the other checks.
    # Shifts that already ended are history and kept out too.
    shifts = sorted([s for s in proposed if s.ends_at > s.starts_at and s.ends_at > now],
                    key=lambda s: s.starts_at)

    for shift in shifts:
        if shift.solver.role != "solver":
            errors.append(f"{_full_name(shift.solver)} is a reporter and cannot take a shift")
        if not TeamMember.objects.filter(user=shift.solver, team=team).exists():
            errors.append(f"{_full_name(shift.solver)} is not on {team.name}")
        clash = (
            Shift.objects.filter(solver=shift.solver, starts_at__lt=shift.ends_at, ends_at__gt=shift.starts_at)
            .exclude(team=team)
            .exclude(id=shift.id)
            .select_related("team")
            .first()
        )
        if clash:
            errors.append(f"{_full_name(shift.solver)} is already on call for {clash.team.name} "
                          f"{_window(clash.starts_at, clash.ends_at)}")

    # Walk forward from now. Each shift should start exactly where the
    # cursor stands: later is a gap, earlier is a double booking. A shift
    # that is running right now started before now, which is fine.
    cursor = now
    for shift in shifts:
        start = max(shift.starts_at, now)
        if start > cursor:
            errors.append(_problem("missing coverage", cursor, start, from_now=cursor == now))
        elif start < cursor:
            errors.append(_problem("double booked", start, min(cursor, shift.ends_at)))
        cursor = max(cursor, shift.ends_at)
    return errors


def reassign(incident, new_solver, by):
    """
    A team lead hands an active ticket to the solver on call for its team
    right now. Returns the reason it was refused, or None when it worked.
    Writes a reassignment entry naming the old and the new solver.
    """
    team = incident.assigned_team
    if team is None:
        return "No team handles this ticket's service, so nobody can be assigned"
    if not is_lead(by, team):
        return f"Only the lead of {team.name} can reassign its tickets"
    if incident.status in ("resolved", "closed"):
        return "Only active tickets can be reassigned"
    if new_solver is None or who_is_on_call(team) != new_solver:
        who = _full_name(new_solver) if new_solver else "Nobody"
        return f"{who} is not on call for {team.name} right now"
    old = incident.assigned_to
    if old == new_solver:
        return f"{_full_name(new_solver)} already has this ticket"
    incident.assigned_to = new_solver
    if incident.status == "open":
        incident.status = "assigned"
    incident.save()
    log_event(incident, by, "reassignment",
              f"Reassigned from {_full_name(old) if old else 'nobody'} to {_full_name(new_solver)}",
              old_assignee=old, new_assignee=new_solver)
    return None
