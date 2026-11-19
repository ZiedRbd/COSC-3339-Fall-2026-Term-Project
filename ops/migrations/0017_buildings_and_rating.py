import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0016_fill_sprint5_columns"),
    ]

    operations = [
        migrations.CreateModel(
            name="Building",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("aliases", models.CharField(blank=True, max_length=200)),
                (
                    "kind",
                    models.CharField(
                        choices=[("campus", "Campus building"), ("residence", "Residence hall or apartments")],
                        default="campus",
                        max_length=20,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "removed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        # What reporters typed stays, under a new name. The old name goes to the link below.
        migrations.RenameField(
            model_name="incident",
            old_name="building",
            new_name="building_typed",
        ),
        migrations.AddField(
            model_name="incident",
            name="building",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="ops.building"
            ),
        ),
        migrations.AddField(
            model_name="incident",
            name="rating",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="incident",
            constraint=models.CheckConstraint(
                condition=models.Q(("rating__isnull", True), models.Q(("rating__gte", 1), ("rating__lte", 5)), _connector="OR"),
                name="rating_is_one_to_five",
            ),
        ),
    ]
