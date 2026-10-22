from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0005_sprint3_schedule_schema"),
    ]

    operations = [
        migrations.RenameField(
            model_name="shift",
            old_name="responder",
            new_name="solver",
        ),
    ]
