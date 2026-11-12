"""Telling a person something happened to a ticket."""
import os
from .models import Notification
from django.core.mail import send_mail


def notify(user, incident, event, message):
    """One row in the Notification table. The bell counts the unread ones."""
    if user is None or not user.is_active:
        return None
    send_mail(
        subject=f"Incident {incident} has been updated",
        message=f"Hello {user},\n{message}",
        from_email=os.getenv("EMAIL_HOST_USER"),  # Sent via your Gmail account
        recipient_list=[user.email],
        using="notifications",  # Targets MAILERS['notifications'] (Gmail SMTP)
    )
    return Notification.objects.create(user=user, incident=incident, event=event, message=message)
