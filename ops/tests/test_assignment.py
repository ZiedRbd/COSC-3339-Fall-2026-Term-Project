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


class ReassignmentTests(TestCase):
    """A lead moves an active ticket to whoever is on call now, and the timeline records it."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.team.lead = self.lead
        self.team.save()
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             first_name="Jane", last_name="Okoro", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        TeamMember.objects.create(user=self.jane, team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 role="reporter")
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc,
                                           reported_by=self.reporter, assigned_team=self.team,
                                           assigned_to=self.tim, status="assigned", priority="low")
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))

    def post_as(self, email):
        self.client.login(username=email, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/reassign/")
        self.inc.refresh_from_db()

    def test_lead_reassigns_to_the_solver_on_call(self):
        """Jane is on call, so the lead can hand her the ticket."""
        self.post_as("lead@x.com")
        self.assertEqual(self.inc.assigned_to, self.jane)
        row = self.inc.incidentupdate_set.get(update_type="reassignment")
        self.assertEqual((row.author, row.old_assignee, row.new_assignee), (self.lead, self.tim, self.jane))
        self.assertIn("Tim Diaz", row.body)
        self.assertIn("Jane Okoro", row.body)

    def test_someone_who_is_not_the_lead_is_refused(self):
        """Tim cannot hand his own ticket away."""
        self.post_as("tim@x.com")
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_nobody_on_call_is_refused(self):
        """With no shift running there is nobody to give it to."""
        Shift.objects.all().delete()
        self.post_as("lead@x.com")
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_closed_ticket_is_refused(self):
        """Only active tickets move."""
        self.inc.status = "closed"
        self.inc.save()
        self.post_as("lead@x.com")
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_open_unassigned_ticket_becomes_assigned(self):
        """A ticket nobody holds gets a holder and the assigned status."""
        self.inc.assigned_to = None
        self.inc.status = "open"
        self.inc.save()
        self.post_as("lead@x.com")
        self.assertEqual((self.inc.assigned_to, self.inc.status), (self.jane, "assigned"))

    def test_only_the_lead_sees_the_reassign_button(self):
        """The button names the on-call solver and shows for the lead alone."""
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.assertIn("Reassign to Jane Okoro", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertNotIn("Reassign to", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())


class AssigneeEditsTests(TestCase):
    """Once a ticket is assigned, the assigned solver is the only one who can edit it."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 role="reporter")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             role="solver")
        for u in (self.tim, self.jane):
            TeamMember.objects.create(user=u, team=self.team)
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc,
                                           reported_by=self.reporter, assigned_team=self.team,
                                           assigned_to=self.tim, status="assigned", priority="low")

    def edit_as(self, email, title):
        self.client.login(username=email, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/edit/", {
            "title": title, "description": "d", "service": self.svc.pk,
            "priority": "low", "building": "", "room": ""})
        self.inc.refresh_from_db()
        return self.inc.title

    def test_assigned_solver_can_edit(self):
        self.assertEqual(self.edit_as("tim@x.com", "Fixed title"), "Fixed title")

    def test_reporter_cannot_edit_once_assigned(self):
        self.assertEqual(self.edit_as("r@x.com", "Nope"), "Leak")

    def test_another_solver_cannot_edit(self):
        self.assertEqual(self.edit_as("jane@x.com", "Nope"), "Leak")

    def test_reporter_edits_again_once_unassigned(self):
        self.inc.assigned_to = None
        self.inc.status = "open"
        self.inc.save()
        self.assertEqual(self.edit_as("r@x.com", "Reporter edit"), "Reporter edit")

    def test_assigned_solver_sees_edit_button_and_reporter_does_not(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertIn("Edit details", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.assertNotIn("Edit details", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
