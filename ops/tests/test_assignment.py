"""Handing a new ticket to the on-call solver."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Incident, Service, Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class AutoAssignmentTests(TestCase):
    """A new ticket goes to whoever is on call for the team that owns its service."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.tim = User.objects.create_user(
            username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
            first_name="Tim", last_name="Diaz", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)

    def file_ticket(self, service=None):
        resp = self.client.post("/incidents/form", {
            "title": "Leak", "description": "d", "service": (service or self.svc).pk,
            "priority": "low", "building": "", "room": ""})
        self.assertEqual(resp.status_code, 302)
        return Incident.objects.get(title="Leak")

    def put_tim_on_call(self):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.tim,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))

    def test_ticket_goes_to_the_on_call_solver(self):
        """Tim is on call, so the new ticket is his and is marked assigned."""
        self.put_tim_on_call()
        inc = self.file_ticket()
        self.assertEqual(inc.assigned_to, self.tim)
        self.assertEqual(inc.assigned_team, self.team)
        self.assertEqual(inc.status, "assigned")

    def test_assignment_is_on_the_timeline_right_after_creation(self):
        """The timeline names who got the ticket, stamped moments after it was filed."""
        self.put_tim_on_call()
        inc = self.file_ticket()
        row = inc.incidentupdate_set.get(update_type="assignment")
        self.assertEqual(row.new_assignee, self.tim)
        self.assertIn("Tim Diaz", row.body)
        self.assertLess(row.created_at - inc.created_at, timedelta(seconds=5))

    def test_nobody_on_call_leaves_the_ticket_open(self):
        """No shifts at all: the ticket is created, stays open, and says why."""
        inc = self.file_ticket()
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")
        row = inc.incidentupdate_set.get(update_type="assignment_failed")
        self.assertIn("No solver on call", row.body)

    def test_service_without_a_team_does_not_crash(self):
        """A ticket against a team-less service is created and left unassigned."""
        loose = Service.objects.create(name="Lost and Found", owning_team=None)
        inc = self.file_ticket(service=loose)
        self.assertIsNone(inc.assigned_team)
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")
        row = inc.incidentupdate_set.get(update_type="assignment_failed")
        self.assertIn("no owning team", row.body)

    def test_deactivated_on_call_solver_is_not_assigned(self):
        """Tim is on the rota but deactivated, so the ticket stays open."""
        self.put_tim_on_call()
        self.tim.is_active = False
        self.tim.save()
        inc = self.file_ticket()
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")

    def test_assigned_ticket_can_only_move_to_in_progress(self):
        """From assigned, a solver can start work but cannot jump to resolved."""
        self.put_tim_on_call()
        inc = self.file_ticket()
        self.client.logout()
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "resolved"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, "assigned")
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "in_progress"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, "in_progress")
