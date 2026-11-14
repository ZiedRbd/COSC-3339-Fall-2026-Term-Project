from django.db import migrations


def simplify_policies(apps, schema_editor):
    """
    Bring every team's policy to the simpler shape. Tier 1 is always the
    on-call solver. Administration tiers go: the policy now ends by itself
    after its last tier. An on-call tier further down goes too, because
    the on-call solver already had the ticket. The tiers that stay keep
    their order and are renumbered 1, 2, 3. A team with no policy gets the
    default one: the on-call solver has 5 minutes, then the lead has 10.
    The columns themselves change in the next migration, because
    PostgreSQL does not alter a table in the transaction that edited its rows.
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
            EscalationTier.objects.create(team=team, tier_number=2, escalate_to="lead", wait_minutes=10)
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
    ]
