from django import template

from ops.models import Incident

register = template.Library()
LABELS = dict(Incident.STATUS_CHOICES)


# Turns a status code into the label people see, so the badge, the buttons
# and the timeline all say "In Progress" for "in_progress".
@register.filter
def status_label(code):
    return LABELS.get(code, code)
