import re

from django.db import migrations

TIER = re.compile(r"Escalated to tier (\d+):")


def fill(apps, schema_editor):
    """
    Rows written before these columns existed get their values.

    An escalation entry says which tier it moved the ticket to in its
    text, so the number is read from there. An entry that escalated to
    administration takes the number of the team's administration tier.
    An entry where the policy ran out stays empty.

    A ticket that was already deleted was deleted by its reporter, the
    only person who could, at the moment the row last changed.
    """
    IncidentUpdate = apps.get_model("ops", "IncidentUpdate")
    EscalationTier = apps.get_model("ops", "EscalationTier")
    Incident = apps.get_model("ops", "Incident")

    administration = dict(
        EscalationTier.objects.filter(escalate_to="administration").values_list("team_id", "tier_number")
    )
    entries = IncidentUpdate.objects.filter(update_type="escalation", escalated_to_tier__isnull=True)
    for entry in entries.select_related("incident"):
        match = TIER.search(entry.body)
        if match:
            entry.escalated_to_tier = int(match.group(1))
        elif "Escalated to administration" in entry.body:
            entry.escalated_to_tier = administration.get(entry.incident.assigned_team_id)
        if entry.escalated_to_tier is not None:
            entry.save(update_fields=["escalated_to_tier"])

    for ticket in Incident.objects.filter(is_deleted=True, removed_at__isnull=True):
        ticket.removed_by_id = ticket.reported_by_id
        ticket.removed_at = ticket.updated_at
        # update() leaves updated_at as it was
        Incident.objects.filter(pk=ticket.pk).update(removed_by_id=ticket.removed_by_id, removed_at=ticket.removed_at)


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0015_sprint5_schema"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
