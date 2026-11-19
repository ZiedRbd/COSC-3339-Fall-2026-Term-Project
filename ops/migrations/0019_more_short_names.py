from django.db import migrations

from ops.buildings import best_match

# Short names people really use, added after the campus list was first
# loaded. Each value replaces the building's whole list of short names.
SHORT_NAMES = {
    "Main Building": "Main, Old Main",
    "John Brooks Williams Natural Sciences Center–North":
        "Natural Sciences North, Science North, JBWN, JBW North",
    "John Brooks Williams Natural Sciences Center–South":
        "Natural Sciences South, Science South, JBWS, JBW South",
    "Health and Counseling Center": "Health Center, Counseling Center",
    "Our Lady Queen of Peace Chapel": "Chapel, Queen of Peace Chapel, Queen of Peace",
    "Mary Moody Northen Theatre": "Theatre, Theater, Moody Theatre, Moody Theater",
    "Recreation and Athletic Center": "RAC, Rec Center, Recreation Center",
    "Le Mans Hall": "Le Mans, LeMans",
    "Basil Moreau Hall": "Moreau, Moreau Hall",
}


def add_short_names(apps, schema_editor):
    """
    Give the buildings their extra short names, then point the tickets
    that are still without a building at one, now that more of what was
    typed can be recognised. A ticket that already has a building is left
    alone, and what was typed is never changed.
    """
    Building = apps.get_model("ops", "Building")
    Incident = apps.get_model("ops", "Incident")
    for name, aliases in SHORT_NAMES.items():
        Building.objects.filter(name=name).update(aliases=aliases)

    buildings = list(Building.objects.all())
    for ticket in Incident.objects.filter(building__isnull=True).exclude(building_typed=""):
        building = best_match(ticket.building_typed, buildings)
        if building is not None:
            # update() leaves updated_at as it was
            Incident.objects.filter(pk=ticket.pk).update(building=building)


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0018_campus_buildings"),
    ]

    operations = [
        migrations.RunPython(add_short_names, migrations.RunPython.noop),
    ]
