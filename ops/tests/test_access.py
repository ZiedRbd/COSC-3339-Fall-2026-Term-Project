"""Who may see and act on which tickets."""
from django.test import TestCase

from ops.models import Incident, Service, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class IncidentAccessTests(TestCase):
    """Only the reporter or a solver on the assigned team may open a ticket."""

    def setUp(self):
        self.team_a = Team.objects.create(name="Team A")
        self.team_b = Team.objects.create(name="Team B")
        self.service = Service.objects.create(name="Svc A", owning_team=self.team_a)
        self.reporter = User.objects.create_user(
            username="rep@x.com", email="rep@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver_a = User.objects.create_user(
            username="sa@x.com", email="sa@x.com", password=GOOD_PASSWORD, role="solver")
        self.solver_b = User.objects.create_user(
            username="sb@x.com", email="sb@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver_a, team=self.team_a)
        TeamMember.objects.create(user=self.solver_b, team=self.team_b)
        self.incident = Incident.objects.create(
            title="Guarded", description="d", service=self.service,
            reported_by=self.reporter, assigned_team=self.team_a, status="open")

    def view_as(self, email):
        self.client.login(username=email, password=GOOD_PASSWORD)
        return self.client.get(f"/incidents/{self.incident.pk}/")

    def test_reporter_can_view_own_ticket(self):
        """The person who filed the ticket can open it."""
        self.assertEqual(self.view_as("rep@x.com").status_code, 200)

    def test_solver_on_team_can_view(self):
        """A solver on the assigned team can open the ticket."""
        self.assertEqual(self.view_as("sa@x.com").status_code, 200)

    def test_solver_on_other_team_is_blocked(self):
        """A solver not on the assigned team is redirected away."""
        self.assertEqual(self.view_as("sb@x.com").status_code, 302)

    def test_other_team_solver_cannot_transition(self):
        """A solver off the team cannot change the ticket's status."""
        self.incident.status = "assigned"
        self.incident.save()
        self.client.login(username="sb@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.incident.pk}/transition/", {"new_status": "in_progress"})
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "assigned")


class RoleUIRulesTests(TestCase):
    """Reporters use their profile; solvers use the list; service is locked on edit."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.svc2 = Service.objects.create(name="Drains", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.incident = Incident.objects.create(
            title="X", description="d", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open")

    def test_reporter_redirected_from_list(self):
        """A reporter hitting the incident list is sent to their profile."""
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        r = self.client.get("/incidents/list")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith("/profile/"))

    def test_solver_list_has_no_edit_button(self):
        """The solver's incident list shows no Edit link."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        html = self.client.get("/incidents/list").content.decode()
        self.assertNotIn("incident_edit", html)
        self.assertNotIn(">Edit<", html)

    def test_reporter_cannot_change_service_on_edit(self):
        """Even if a reporter submits a different service, it is ignored."""
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.incident.pk}/edit/", {
            "title": "X2", "description": "d", "service": self.svc2.pk,
            "priority": "high", "building": "", "room": ""})
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.title, "X2")
        self.assertEqual(self.incident.service, self.svc)  # unchanged


class SolverCannotCreateTests(TestCase):
    """Solvers may not file tickets; only reporters can."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)

    def test_solver_get_create_form_is_blocked(self):
        """A solver opening the ticket form is redirected, not shown the form."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.client.get("/incidents/form").status_code, 302)

    def test_solver_post_create_is_blocked(self):
        """A solver POSTing a new ticket creates nothing."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        self.client.post("/incidents/form", {
            "title": "X", "description": "d", "service": self.svc.pk, "priority": "low"})
        self.assertEqual(Incident.objects.filter(title="X").count(), 0)

    def test_solver_cannot_delete_ticket(self):
        """A solver POSTing a delete leaves the ticket in place."""
        reporter = User.objects.create_user(
            username="r3@x.com", email="r3@x.com", password=GOOD_PASSWORD, role="reporter")
        incident = Incident.objects.create(
            title="Keep this too", description="d", service=self.svc,
            reported_by=reporter, assigned_team=self.team, status="open", priority="low")
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        resp = self.client.post(f"/incidents/{incident.pk}/delete/")
        self.assertEqual(resp.status_code, 302)
        incident.refresh_from_db()
        self.assertFalse(incident.is_deleted)

    def test_solver_cannot_edit_ticket(self):
        """A solver hitting the edit URL is redirected and cannot change details."""
        reporter = User.objects.create_user(
            username="r2@x.com", email="r2@x.com", password=GOOD_PASSWORD, role="reporter")
        incident = Incident.objects.create(
            title="Keep me", description="d", service=self.svc,
            reported_by=reporter, assigned_team=self.team, status="open", priority="low")
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        resp = self.client.post(f"/incidents/{incident.pk}/edit/", {
            "title": "Hacked", "description": "d", "service": self.svc.pk,
            "priority": "low", "building": "", "room": ""})
        self.assertEqual(resp.status_code, 302)
        incident.refresh_from_db()
        self.assertEqual(incident.title, "Keep me")


class LeadAccessTests(TestCase):
    """A team lead who is not a member can still open and list the team's tickets."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.team.lead = self.lead
        self.team.save()
        reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                            role="reporter")
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc,
                                           reported_by=reporter, assigned_team=self.team, priority="low")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)

    def test_lead_can_open_the_ticket(self):
        self.assertEqual(self.client.get(f"/incidents/{self.inc.pk}/").status_code, 200)

    def test_lead_sees_the_ticket_in_the_list(self):
        self.assertIn("Leak", self.client.get("/incidents/list").content.decode())
