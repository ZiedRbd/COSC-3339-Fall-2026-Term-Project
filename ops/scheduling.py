"""Who is on call, and handing a new ticket to that person."""
from django.utils import timezone

from .models import Shift
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
            responder__is_active=True,
            responder__role="solver",
            responder__teammember__team=team,
        )
        .select_related("responder")
        .order_by("starts_at", "id")
        .first()
    )
    if shift is None:
        return None
    return shift.responder


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
        .select_related("responder")
        .order_by("starts_at", "id")
    )


def assign_on_creation(incident):
    """
    Hand a brand new ticket to whoever is on call for the team that owns
    its service, and write what happened to the timeline either way. The
    ticket stays Open and unassigned when the service has no team, when
    nobody is on call, or when the person on call cannot take it.
    """
    # The reporter filing the ticket is what set this off, so they are
    # recorded as the author of the entry
    reporter = incident.reported_by
    team = incident.service.owning_team
    if team is None:
        log_event(incident, reporter, "assignment_failed",
                  "Service has no owning team, so nobody can be assigned")
        return
    incident.assigned_team = team
    responder = who_is_on_call(team, incident.created_at)
    if responder is None:
        incident.save()
        log_event(incident, reporter, "assignment_failed",
                  f"No responder on call for {team.name}")
        return
    incident.assigned_to = responder
    incident.status = "assigned"
    incident.save()
    log_event(incident, reporter, "assignment",
              f"Assigned to {responder.first_name} {responder.last_name}, on call for {team.name}",
              new_assignee=responder)
