from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ops.models import Shift, Team, TeamMember


# Fills every team's on-call schedule from now until a week ahead, 24 hours a
# day in three blocks (00:00, 08:00, 16:00), rotating through the team's
# solvers so each day shows a different name per block. Pass --short-team to
# stop one team at the end of today, to show the "schedule ran out" case.
# Safe to run again: it replaces current and future shifts only, never past
# ones, and never touches which ticket belongs to whom.
# Run with: python manage.py seed_shifts
class Command(BaseCommand):
    help = "Seed a week of 24/7 on-call shifts for every team"

    def add_arguments(self, parser):
        parser.add_argument("--short-team", default="",
                            help="Optional team whose schedule ends at midnight tonight")
        parser.add_argument("--offset", type=int, default=0,
                            help="Start the rotation this many people in, to change who owns a slot on a rerun")

    def handle(self, *args, **options):
        now = timezone.now()
        local_now = timezone.localtime(now)
        # The first block is the one running right now, so coverage starts
        # before now and no shift ever crosses midnight.
        start = local_now.replace(hour=(local_now.hour // 8) * 8, minute=0, second=0, microsecond=0)
        block = timedelta(hours=8)
        week_end = start + timedelta(days=7)
        tonight = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        # Replace everything still running or yet to come
        Shift.objects.filter(ends_at__gt=now).delete()

        total = 0
        for team in Team.objects.order_by("name"):
            solvers = [
                m.user for m in TeamMember.objects.filter(team=team, user__role="solver", user__is_active=True)
                .select_related("user").order_by("user__id")
            ]
            if not solvers:
                self.stdout.write(f"{team.name}: no solvers, skipped")
                continue
            scheduler = team.lead or solvers[0]
            end = tonight if team.name == options["short_team"] else week_end

            cursor = start
            i = options["offset"]
            while cursor < end:
                block_end = min(cursor + block, end)
                Shift.objects.create(team=team, solver=solvers[i % len(solvers)], created_by=scheduler,
                                     starts_at=cursor, ends_at=block_end)
                cursor = block_end
                i += 1
                total += 1
            self.stdout.write(f"{team.name}: covered until {timezone.localtime(end):%a %b %d %H:%M}")

        self.stdout.write(self.style.SUCCESS(f"Seeded {total} shifts"))
