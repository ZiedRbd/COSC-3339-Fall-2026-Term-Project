"""Telling a person something happened to a ticket."""
from .models import Notification


def notify(user, incident, event, message):
    """One row in the Notification table. The bell counts the unread ones."""
    if user is None or not user.is_active:
        return None
    return Notification.objects.create(user=user, incident=incident, event=event, message=message)
