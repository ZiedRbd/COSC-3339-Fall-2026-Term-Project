from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ops.models import Shift, Team, TeamMember
from ops.scheduling import assign_waiting, validate_secondary


# Fills every team's on-call schedule from now until a week ahead, or to the
# end of the day given with --until, 24 hours a day in three blocks (00:00,
# 08:00, 16:00), rotating through the team's solvers so each day shows a
# different name per block. A solver who is on two teams is never put on
# call for both in the same hours, and nobody takes two blocks in a row.
# Each day also gets one secondary shift, 08:00 to 16:00, for the first
# solver the secondary rules allow; a day where they allow nobody has no
# secondary. Pass --short-team to stop one team at the end of today, to show
# the "schedule ran out" case.
# Safe to run again: it replaces current and future shifts only, never past
# ones. It never takes a ticket from the solver who holds it, and it hands
# the tickets that were waiting to whoever on call has room.
# Run with: python manage.py seed_shifts
#           python manage.py seed_shifts --until 2026-11-30
class Command(BaseCommand):
    help = "Seed 24/7 on-call shifts for every team: one week, or to the end of the day given with --until"

    def add_arguments(self, parser):
        parser.add_argument("--short-team", default="",
                            help="Optional team whose schedule ends at midnight tonight")
        parser.add_argument("--offset", type=int, default=0,
                            help="Start the rotation this many people in, to change who owns a slot on a rerun")
        parser.add_argument("--until", default="",
                            help="Cover every team to the end of this day, written YYYY-MM-DD, instead of one week")

    def next_free(self, solvers, i, team, starts_at, ends_at, previous):
        """
        The position in the rotation of the next person who can take this
        block: not the one who just finished the block before it, and not
        someone already on call for another team in the same hours. When
        nobody is free the rotation's own choice takes it, so cover never
        has a hole, and the block is named in the output.
        """
        for step in range(len(solvers)):
            solver = solvers[(i + step) % len(solvers)]
            elsewhere = Shift.objects.filter(solver=solver, starts_at__lt=ends_at, ends_at__gt=starts_at)
            if solver != previous and not elsewhere.exclude(team=team).exists():
                return i + step
        if len(solvers) > 1:
            self.stdout.write(self.style.WARNING(
                f"{team.name}: nobody was free on {timezone.localtime(starts_at):%a %b %d %H:%M}, "
                f"so the rotation's choice takes it"))
        return i

    def handle(self, *args, **options):
        now = timezone.now()
        local_now = timezone.localtime(now)
        # The first block is the one running right now, so coverage starts
        # before now and no shift ever crosses midnight.
        start = local_now.replace(hour=(local_now.hour // 8) * 8, minute=0, second=0, microsecond=0)
        block = timedelta(hours=8)
        cover_end = start + timedelta(days=7)
        if options["until"]:
            try:
                last_day = date.fromisoformat(options["until"])
            except ValueError:
                raise CommandError("--until takes a date written YYYY-MM-DD, for example 2026-11-30")
            if last_day < local_now.date():
                raise CommandError("--until is a day that has already passed")
            # Cover runs to the midnight that ends that day
            cover_end = timezone.make_aware(datetime.combine(last_day + timedelta(days=1), time.min))
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
            end = tonight if team.name == options["short_team"] else cover_end

            cursor = start
            i = options["offset"]
            previous = None
            while cursor < end:
                block_end = min(cursor + block, end)
                i = self.next_free(solvers, i, team, cursor, block_end, previous)
                previous = solvers[i % len(solvers)]
                Shift.objects.create(team=team, solver=previous, created_by=scheduler,
                                     starts_at=cursor, ends_at=block_end)
                cursor = block_end
                i += 1
                total += 1
            self.stdout.write(f"{team.name}: covered until {timezone.localtime(end):%a %b %d %H:%M}")

        # Secondaries go in after every team's primaries, so a solver who is
        # primary on another team at that hour is never picked.
        for team in Team.objects.order_by("name"):
            solvers = [
                m.user for m in TeamMember.objects.filter(team=team, user__role="solver", user__is_active=True)
                .select_related("user").order_by("user__id")
            ]
            if not solvers:
                continue
            end = tonight if team.name == options["short_team"] else cover_end
            day_start = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
            added = []
            while day_start < end:
                day_end = day_start + block
                if day_end > now:
                    for solver in solvers:
                        shift = Shift(team=team, solver=solver, on_call_role="secondary",
                                      created_by=team.lead or solvers[0], starts_at=day_start, ends_at=day_end)
                        # Shifts saved earlier in this run are read from the table by the check itself,
                        # so only the last few days need to be handed over with the new one
                        if not validate_secondary(team, added[-3:] + [shift], now):
                            shift.save()
                            added.append(shift)
                            total += 1
                            break
                day_start += timedelta(days=1)

        picked = sum(assign_waiting(team) for team in Team.objects.all())
        self.stdout.write(self.style.SUCCESS(f"Seeded {total} shifts, {picked} waiting tickets assigned"))
