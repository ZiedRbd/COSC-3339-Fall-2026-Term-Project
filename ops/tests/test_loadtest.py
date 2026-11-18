"""The load test times the incident list and leaves the database exactly as it found it."""
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from ops.models import Incident, Notification, Service, Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class LoadTestTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Port")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)

    def ticket(self, **fields):
        return Incident.objects.create(title="Leak", description="d", service=self.service,
                                       reported_by=self.reporter, assigned_team=self.team, **fields)

    def run_it(self, *args):
        out = StringIO()
        call_command("loadtest", *args, stdout=out)
        return out.getvalue()

    def rows(self, output):
        """The table as {step: [incidents, fastest, average, slowest, queries, page KB]}."""
        table = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) == 7 and parts[1].isdigit():
                table[parts[0]] = [float(value) for value in parts[1:]]
        return table

    def test_it_reports_the_baseline_and_then_each_size(self):
        self.ticket(status="closed")
        self.ticket(status="closed")
        rows = self.rows(self.run_it("--sizes", "5", "12", "--runs", "2"))
        self.assertEqual(list(rows), ["Baseline", "5", "12"])
        self.assertEqual([rows[step][0] for step in rows], [2, 5, 12])
        for incidents, fastest, average, slowest, queries, size in rows.values():
            self.assertLessEqual(fastest, average)
            self.assertLessEqual(average, slowest)
            self.assertGreater(queries, 0)

    def test_more_tickets_cost_no_more_queries_and_a_bigger_page(self):
        rows = self.rows(self.run_it("--sizes", "5", "40", "--runs", "1"))
        self.assertEqual(rows["5"][4], rows["40"][4])
        self.assertGreater(rows["40"][5], rows["5"][5])

    def test_nothing_is_left_in_the_database(self):
        before = self.ticket(status="closed")
        self.run_it("--sizes", "8", "--runs", "1")
        self.assertEqual(Incident.objects.count(), 1)
        self.assertFalse(User.objects.filter(email__contains="loadtest").exists())
        self.assertEqual(TeamMember.objects.count(), 1)
        # Real ticket numbers carry on from where they were
        self.assertEqual(self.ticket().pk, before.pk + 1)

    def test_a_ticket_that_was_waiting_is_still_waiting_and_nobody_is_told(self):
        waiting = self.ticket()
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.tim,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        self.run_it("--sizes", "5", "--runs", "1")
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, "open")
        self.assertIsNone(waiting.assigned_to)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_a_size_the_list_already_reaches_is_skipped(self):
        for _ in range(3):
            self.ticket(status="closed")
        output = self.run_it("--sizes", "2", "6", "--runs", "1")
        self.assertIn("Skipped 2", output)
        self.assertEqual(list(self.rows(output)), ["Baseline", "6"])

    def test_the_team_can_be_named(self):
        other = Team.objects.create(name="Electrical")
        Service.objects.create(name="Lights", owning_team=other)
        self.ticket(status="closed")
        output = self.run_it("--team", "electrical", "--sizes", "3", "--runs", "1")
        self.assertIn("as a solver on Electrical", output)
        self.assertEqual(self.rows(output)["Baseline"][0], 0)

    def test_a_team_that_does_not_exist_or_owns_no_service_is_refused(self):
        with self.assertRaisesMessage(CommandError, "no team named Nowhere"):
            self.run_it("--team", "Nowhere")
        Team.objects.create(name="Empty")
        with self.assertRaisesMessage(CommandError, "owns no service"):
            self.run_it("--team", "Empty")

    def test_runs_and_sizes_must_be_above_zero(self):
        with self.assertRaisesMessage(CommandError, "--runs must be at least 1"):
            self.run_it("--runs", "0")
        with self.assertRaisesMessage(CommandError, "above zero"):
            self.run_it("--sizes", "0")
