"""Who may do what."""
from .scheduling import team_for


def is_admin(user):
    """An administrator: an active account with the superuser flag."""
    return bool(user is not None and user.is_authenticated and user.is_active and user.is_superuser)


def can_override(user, incident):
    """
    An administrator may override any ticket. The lead of the team a
    ticket goes to may override that team's tickets and no others.
    Nobody else may override anything.
    """
    if is_admin(user):
        return True
    if user is None or not user.is_authenticated or not user.is_active or user.role != "solver":
        return False
    team = team_for(incident)
    return team is not None and team.lead_id == user.pk
