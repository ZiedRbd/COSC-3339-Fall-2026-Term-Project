"""Writing entries to a ticket's timeline."""
from .models import IncidentUpdate


def log_event(incident, author, update_type, body, old_status="", new_status="",
              old_assignee=None, new_assignee=None):
    """Record one event on an incident's timeline."""
    IncidentUpdate.objects.create(
        incident=incident, author=author, update_type=update_type, body=body,
        old_status=old_status, new_status=new_status,
        old_assignee=old_assignee, new_assignee=new_assignee,
    )
