from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0010_simpler_escalation_policy"),
    ]

    operations = [
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
