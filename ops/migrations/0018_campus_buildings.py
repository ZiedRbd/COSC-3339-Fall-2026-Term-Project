from django.db import migrations

from ops.buildings import best_match

# The buildings of St. Edward's University, with the names the university
# uses for them in its style guide and on its housing pages. The second
# value is the short names people type, which the search also matches.
CAMPUS = [
    ("Main Building", "Main"),
    ("Holy Cross Hall", "Holy Cross"),
    ("Trustee Hall", "Trustee"),
    ("Fleck Hall", "Fleck"),
    ("Moody Hall", "Moody"),
    ("Sorin Hall", "Sorin"),
    ("Premont Hall", "Premont"),
    ("Fondren Hall", "Fondren"),
    ("Equity Hall", "Equity"),
    ("Fine Arts Center", "Fine Arts"),
    ("John Brooks Williams Natural Sciences Center–North", "Natural Sciences North, Science North, JBWN"),
    ("John Brooks Williams Natural Sciences Center–South", "Natural Sciences South, Science South, JBWS"),
    ("Munday Library", "Library"),
    ("Carriage House", ""),
    ("Operations Building", "Operations"),
    ("Physical Plant", ""),
    ("Robert and Pearle Ragsdale Center", "Ragsdale Center, Ragsdale"),
    ("Health and Counseling Center", "Health Center"),
    ("Campus Ministry Building", "Campus Ministry"),
    ("Our Lady Queen of Peace Chapel", "Chapel"),
    ("Mary Moody Northen Theatre", "Theatre, Theater"),
    ("Wild Basin Creative Research Center", "Wild Basin"),
    ("Recreation and Athletic Center", "RAC, Rec Center"),
    ("UFCU Alumni Gym", "Alumni Gym"),
]
RESIDENCES = [
    ("Basil Moreau Hall", "Moreau"),
    ("Jacques Dujarié Hall", "Dujarie"),
    ("Casa", "The Casa"),
    ("Casitas", "Moreau Casitas, Dujarie Casitas"),
    ("Edmund Hunt Hall", "Hunt Hall, Hunt"),
    ("Le Mans Hall", "Le Mans"),
    ("Lady Bird Johnson Hall", "Johnson Hall, Johnson, LBJ"),
    ("East Hall", ""),
    ("Teresa Hall", "Teresa"),
    ("Maryhill Apartments", "Maryhill"),
    ("Hilltopper Heights Apartments", "Hilltopper Heights"),
    ("St. André Apartments", "St. Andre, Saint Andre"),
]


def load(apps, schema_editor):
    """
    Fill the campus list, then point every ticket written before it
    existed at its building. A ticket is only pointed at a building when
    what was typed clearly names one. Either way the typed text stays in
    building_typed, so nothing a reporter wrote is lost.
    """
    Building = apps.get_model("ops", "Building")
    Incident = apps.get_model("ops", "Incident")
    for kind, rows in (("campus", CAMPUS), ("residence", RESIDENCES)):
        for name, aliases in rows:
            Building.objects.get_or_create(name=name, defaults={"aliases": aliases, "kind": kind})

    buildings = list(Building.objects.all())
    for ticket in Incident.objects.filter(building__isnull=True).exclude(building_typed=""):
        building = best_match(ticket.building_typed, buildings)
        if building is not None:
            # update() leaves updated_at as it was
            Incident.objects.filter(pk=ticket.pk).update(building=building)


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0017_buildings_and_rating"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
