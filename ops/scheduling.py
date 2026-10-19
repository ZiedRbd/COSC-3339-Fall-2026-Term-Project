"""Who is on call. Read-only lookups over the Shift table."""
from django.utils import timezone

from .models import Shift


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
