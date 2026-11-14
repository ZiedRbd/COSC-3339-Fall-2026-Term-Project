"""Telling a person something happened to a ticket: in the bell and by email."""
import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)

# After a send fails, email is skipped for this long. A mail server that is
# down then costs one wait, not one wait for every notification after it.
MAIL_PAUSE = timedelta(minutes=5)
_mail_paused_until = None


def notify(user, incident, event, message):
    """
    One row in the Notification table, which the bell counts, and the same
    words by email. The row is written first. A mail server that is down
    or refuses the message is logged and nothing else: filing, assigning
    and escalating a ticket must never fail because an email did. Email
    then pauses for a few minutes, so the requests that follow are not
    slowed down too. Nobody inactive is told anything.
    """
    global _mail_paused_until
    if user is None or not user.is_active:
        return None
    note = Notification.objects.create(user=user, incident=incident, event=event, message=message)
    now = timezone.now()
    if not user.email or (_mail_paused_until and now < _mail_paused_until):
        return note
    # The subject is built from the ticket number and a fixed label, never
    # from text a user typed, and differs per event so mail clients do not
    # fold the messages about one ticket into each other.
    subject = f"CampusDesk ticket #{incident.pk}: {note.get_event_display()}" if incident else "CampusDesk"
    try:
        send_mail(
            subject=subject,
            message=f"Hello {user.get_full_name() or user.email},\n\n{message}\n\nCampusDesk",
            from_email=None,
            recipient_list=[user.email],
            using="notifications",
        )
    except Exception:
        _mail_paused_until = now + MAIL_PAUSE
        logger.exception("Email to %s about %s failed. Email is paused for %s minutes.",
                         user.email, subject, MAIL_PAUSE.seconds // 60)
        return note
    note.emailed_at = timezone.now()
    note.save(update_fields=["emailed_at"])
    return note
