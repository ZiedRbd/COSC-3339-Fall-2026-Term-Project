from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0011_tier_fields_for_simpler_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(blank=True, upload_to="avatars/"),
        ),
    ]
