"""Writing entries to a ticket's timeline."""
from .models import IncidentUpdate

# The reason given for an override or a removal is a sentence or two, not a report
MAX_REASON = 500
# Long enough to be a word, so a stray key press is not a reason
MIN_REASON = 5


def clean_reason(text):
    """A typed reason on one line: no line breaks, single spaces, nothing at either end. Empty when nothing was typed."""
    return " ".join((text or "").split())


def log_event(incident, author, update_type, body, old_status="", new_status="",
              old_assignee=None, new_assignee=None, escalated_to_tier=None):
    """
    Record one event on an incident's timeline. An escalation passes the
    number of the tier the ticket moved to, which the analytics count.
    """
    IncidentUpdate.objects.create(
        incident=incident, author=author, update_type=update_type, body=body,
        old_status=old_status, new_status=new_status,
        old_assignee=old_assignee, new_assignee=new_assignee, escalated_to_tier=escalated_to_tier
    )
