import time
from statistics import mean

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, Max, Q
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from ops.models import Building, Incident, Service, Team, TeamMember, User
from ops.notifications import pause_email

TITLE = "Load test ticket"
VIEWER = "loadtest.solver@campusdesk.invalid"
# Test tickets get numbers this far above the real ones, so the real
# numbering is never used up and carries on where it was
ID_GAP = 1_000_000
STATUSES = ["resolved", "closed", "in_progress", "resolved", "closed"]
PRIORITIES = ["low", "medium", "high", "critical"]
ROOMS = ["210", "B12", "", ""]
# Statements the surrounding transaction adds, which a real request does not run
NOT_A_QUERY = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")


# Times the incident list as the number of tickets grows. A temporary
# solver joins one team and loads that team's list: first as it is today,
# then with test tickets added until the list shows each size. Each load
# goes through the whole application, from the middleware to the rendered
# page, without the network.
#
# Everything happens inside one transaction that is rolled back at the
# end, so the site, the minute timer and every other visitor never see a
# test row, and nothing is left to clean up. Email is paused for the run.
# Safe on the live server.
# Run with: python manage.py loadtest
class Command(BaseCommand):
    help = "Time the incident list at growing numbers of tickets. Saves nothing."

    def add_arguments(self, parser):
        parser.add_argument("--team", help="Name of the team whose list is measured. "
                                           "Default: the team with the most tickets.")
        parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000],
                            help="How many tickets the list shows at each step")
        parser.add_argument("--runs", type=int, default=5, help="How many times each step is loaded")

    def handle(self, *args, **options):
        runs = options["runs"]
        sizes = sorted(set(options["sizes"]))
        if runs < 1:
            raise CommandError("--runs must be at least 1")
        if any(size < 1 for size in sizes):
            raise CommandError("--sizes must be whole numbers above zero")
        team = self.pick_team(options["team"])
        services = list(Service.objects.filter(owning_team=team).order_by("id"))
        if not services:
            raise CommandError(f"{team.name} owns no service, so no ticket can be routed to it")

        pause_email(24 * 60)
        try:
            with transaction.atomic():
                rows = self.measure(team, services, sizes, runs)
                transaction.set_rollback(True)
        finally:
            pause_email(0)

        if Incident.objects.filter(title__startswith=TITLE).exists() or User.objects.filter(email=VIEWER).exists():
            raise CommandError("Test rows were left behind. Check the database before running again.")
        self.report(team, runs, rows)

    def pick_team(self, name):
        if name:
            team = Team.objects.filter(name__iexact=name).first()
            if team is None:
                raise CommandError(f"There is no team named {name}")
            return team
        team = (Team.objects.annotate(tickets=Count("incident", filter=Q(incident__is_deleted=False)))
                .order_by("-tickets", "id").first())
        if team is None:
            raise CommandError("There are no teams. Run the seed command first.")
        return team

    def measure(self, team, services, sizes, runs):
        viewer = User(username=VIEWER, email=VIEWER, first_name="Load", last_name="Test", role="solver")
        viewer.set_unusable_password()
        viewer.save()
        TeamMember.objects.create(user=viewer, team=team)
        client = Client(SERVER_NAME=self.host())
        client.force_login(viewer)
        path = reverse("incidents")
        # The first load of a process also imports and compiles; it is not measured
        self.load(client, path)

        shown = Incident.objects.filter(assigned_team=team, is_deleted=False).count()
        rows = [self.row("Baseline", shown, client, path, runs)]
        holders = list(User.objects.filter(teammember__team=team, is_active=True).order_by("id"))
        reporters = list(User.objects.filter(role="reporter", is_active=True).order_by("id")[:20]) or [viewer]
        next_id = (Incident.objects.aggregate(top=Max("id"))["top"] or 0) + ID_GAP
        for size in sizes:
            if size <= shown:
                self.stdout.write(f"Skipped {size}: the list already shows {shown}")
                continue
            self.add_tickets(team, services, holders, reporters, next_id, size - shown)
            next_id += size - shown
            shown = size
            rows.append(self.row(str(size), shown, client, path, runs))
        return rows

    def host(self):
        """A host name the site answers to, so the request is not refused."""
        for name in settings.ALLOWED_HOSTS:
            if name and "*" not in name and not name.startswith("."):
                return name
        return "localhost"

    def add_tickets(self, team, services, holders, reporters, first_id, count):
        now = timezone.now()
        # Three buildings from the campus list, and one ticket in four with no location
        buildings = list(Building.objects.filter(is_active=True)[:3]) + [None]
        tickets = []
        for n in range(count):
            status = STATUSES[n % len(STATUSES)]
            tickets.append(Incident(
                id=first_id + n,
                title=f"{TITLE} {first_id + n}",
                description="Created by the load test and rolled back when it ends.",
                building=buildings[n % len(buildings)], room=ROOMS[n % len(ROOMS)],
                service=services[n % len(services)],
                reported_by=reporters[n % len(reporters)],
                assigned_team=team,
                assigned_to=holders[n % len(holders)],
                status=status,
                priority=PRIORITIES[n % len(PRIORITIES)],
                resolved_at=None if status == "in_progress" else now,
            ))
        Incident.objects.bulk_create(tickets, batch_size=500)

    def load(self, client, path):
        """One load of the page: milliseconds, queries, bytes."""
        with CaptureQueriesContext(connection) as captured:
            started = time.perf_counter()
            response = client.get(path, secure=settings.SECURE_SSL_REDIRECT)
            elapsed = time.perf_counter() - started
        if response.status_code != 200:
            raise CommandError(f"{path} answered {response.status_code}, not 200")
        queries = [q for q in captured.captured_queries if not q["sql"].startswith(NOT_A_QUERY)]
        return elapsed * 1000, len(queries), len(response.content)

    def row(self, label, shown, client, path, runs):
        loads = [self.load(client, path) for _ in range(runs)]
        times = [load[0] for load in loads]
        return {"label": label, "shown": shown, "fastest": min(times), "average": mean(times),
                "slowest": max(times), "queries": max(load[1] for load in loads), "bytes": loads[-1][2]}

    def report(self, team, runs, rows):
        engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
        self.stdout.write("")
        self.stdout.write(f"Incident list, {reverse('incidents')}, as a solver on {team.name}")
        self.stdout.write(f"Database: {engine}. Debug: {'on' if settings.DEBUG else 'off'}. "
                          f"{runs} loads per row. Times in milliseconds.")
        self.stdout.write("")
        self.stdout.write(f"{'Step':<10}{'Incidents':>10}{'Fastest':>10}{'Average':>10}{'Slowest':>10}"
                          f"{'Queries':>9}{'Page KB':>9}")
        for r in rows:
            self.stdout.write(f"{r['label']:<10}{r['shown']:>10}{r['fastest']:>10.1f}{r['average']:>10.1f}"
                              f"{r['slowest']:>10.1f}{r['queries']:>9}{r['bytes'] / 1024:>9.0f}")
        self.stdout.write("")
        self.stdout.write("Nothing was saved: every test row was rolled back.")
