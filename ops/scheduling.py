"""Who is on call. Read-only lookups over the Shift table."""
from django.utils import timezone

from .models import Shift


def who_is_on_call(team, at=None):
    """
    The responder covering team at the instant at, or None when nobody is.
    A shift covers starts_at up to but not including ends_at, so the end
    instant belongs to the next shift. Deactivated users, anyone who is
    not a solver, and anyone no longer on the team are skipped even if a
    shift names them.
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
    """Every shift for team that overlaps the window, earliest first."""
    return (
        Shift.objects.filter(
            team=team,
            starts_at__lt=window_end,
            ends_at__gt=window_start,
        )
        .select_related("responder")
        .order_by("starts_at", "id")
    )
