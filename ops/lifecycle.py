"""The statuses a ticket moves through, and the moves the normal buttons allow."""
from .models import Incident

STATUS_LABELS = dict(Incident.STATUS_CHOICES)

# A ticket leaves Open only by being assigned, automatically on creation or
# by a team lead. Solvers move it along from there. An override, in
# ops/overrides.py, is the only way round this table.
ALLOWED_TRANSITIONS = {
    "open": [],
    "assigned": ["in_progress"],
    "in_progress": ["resolved"],
    "resolved": ["closed", "open"],
    "closed": ["open"],
}
