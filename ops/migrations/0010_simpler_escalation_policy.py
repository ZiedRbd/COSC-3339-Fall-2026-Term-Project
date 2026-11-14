from django.db import migrations, models


def simplify_policies(apps, schema_editor):
    """
    Bring every team's policy to the simpler shape. Tier 1 is always the
    on-call solver, so every team gets one. Administration tiers go: the
    policy now ends by itself after its last tier. An on-call tier further
    down goes too, because the on-call solver already had the ticket. The
    tiers that stay keep their order and are renumbered 1, 2, 3.
    """
    Team = apps.get_model("ops", "Team")
    EscalationTier = apps.get_model("ops", "EscalationTier")
    for team in Team.objects.all():
        kept = []
        for tier in EscalationTier.objects.filter(team=team).order_by("tier_number"):
            if tier.escalate_to == "administration" or (kept and tier.escalate_to == "on_call"):
                tier.delete()
            else:
                kept.append(tier)
        if not kept:
            EscalationTier.objects.create(team=team, tier_number=1, escalate_to="on_call", wait_minutes=5)
            continue
        kept[0].escalate_to = "on_call"
        kept[0].escalate_to_user = None
        # Numbers only move down, lowest first, so no two tiers ever share one
        for number, tier in enumerate(kept, start=1):
            tier.tier_number = number
            tier.wait_minutes = tier.wait_minutes or 5
            tier.save()


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0009_tier_choice_wording"),
    ]

    operations = [
        migrations.RunPython(simplify_policies, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="escalationtier",
            name="escalate_to",
            field=models.CharField(
                choices=[
                    ("on_call", "The on-call solver"),
                    ("lead", "The team lead"),
                    ("user", "A specific person on the team"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="escalationtier",
            name="wait_minutes",
            field=models.PositiveIntegerField(),
        ),
    ]
