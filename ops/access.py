"""Who may do what."""


def is_admin(user):
    """An administrator: an active account with the superuser flag."""
    return bool(user is not None and user.is_authenticated and user.is_active and user.is_superuser)
