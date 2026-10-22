"""Creating, editing, and soft deleting tickets."""
from django.test import TestCase

from ops.models import Incident, TeamMember
from ops.tests.helpers import GOOD_PASSWORD, make_user, make_service


class IncidentTests(TestCase):
    """Logged in users can create, edit, and soft delete tickets."""

    def setUp(self):
        self.user = make_user()
        self.service = make_service()
        self.client.login(username="user@example.com", password=GOOD_PASSWORD)

    def ticket_data(self, **overrides):
        data = {
            "title": "Sink leaking",
            "description": "Steady drip under the sink",
            "service": self.service.pk,
            "priority": "high",
            "building": "Moody",
            "room": "214",
        }
        data.update(overrides)
        return data

    def test_create_ticket(self):
        """A submitted ticket is saved with the signed in user as the reporter."""
        response = self.client.post("/incidents/form", self.ticket_data())
        self.assertRedirects(response, "/incidents/list", target_status_code=302)
        ticket = Incident.objects.get(title="Sink leaking")
        self.assertEqual(ticket.reported_by, self.user)
        self.assertEqual(ticket.priority, "high")
        self.assertEqual(ticket.building, "Moody")

    def test_create_ticket_without_location(self):
        """Building and room are optional."""
        self.client.post("/incidents/form", self.ticket_data(building="", room=""))
        self.assertTrue(Incident.objects.filter(title="Sink leaking").exists())

    def test_ticket_appears_in_list_newest_first(self):
        """The most recently created ticket is at the top of the solver's list."""
        self.user.role = "solver"; self.user.save()
        TeamMember.objects.create(user=self.user, team=self.service.owning_team)
        Incident.objects.create(title="First", description="d", service=self.service,
            reported_by=self.user, assigned_team=self.service.owning_team)
        Incident.objects.create(title="Second", description="d", service=self.service,
            reported_by=self.user, assigned_team=self.service.owning_team)
        html = self.client.get("/incidents/list").content.decode()
        self.assertLess(html.index("Second"), html.index("First"))

    def test_edit_ticket(self):
        """Editing saves the new values on the same row."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(
            f"/incidents/{ticket.pk}/edit/",
            self.ticket_data(title="Sink fixed", priority="low"),
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "Sink fixed")
        self.assertEqual(ticket.priority, "low")

    def test_edit_form_is_prefilled(self):
        """The edit page opens with the current values already filled in."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        html = self.client.get(f"/incidents/{ticket.pk}/edit/").content.decode()
        self.assertIn("Sink leaking", html)
        self.assertIn("Moody", html)

    def test_delete_is_soft(self):
        """Deleting sets is_deleted and keeps the row in the database."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_deleted)
        self.assertTrue(Incident.objects.filter(pk=ticket.pk).exists())

    def test_deleted_ticket_is_hidden_from_list(self):
        """A deleted ticket no longer appears in the list."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        html = self.client.get("/incidents/list").content.decode()
        self.assertNotIn("Sink leaking", html)

    def test_delete_persists_across_sessions(self):
        """A deletion is visible from a second, separate login."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        other = self.client_class()
        other.login(username="user@example.com", password=GOOD_PASSWORD)
        html = other.get("/incidents/list").content.decode()
        self.assertNotIn("Sink leaking", html)

    def test_delete_ignores_get(self):
        """Opening the delete URL in the browser does nothing; only POST deletes."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.get(f"/incidents/{ticket.pk}/delete/")
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_deleted)

    def test_editing_deleted_ticket_returns_404(self):
        """A deleted ticket cannot be reopened through its edit URL."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        response = self.client.get(f"/incidents/{ticket.pk}/edit/")
        self.assertEqual(response.status_code, 404)
