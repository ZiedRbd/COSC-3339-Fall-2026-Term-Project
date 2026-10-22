"""What gets written to a ticket's timeline."""
from django.test import TestCase

from ops.models import Incident, Service, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class TimelineEventTests(TestCase):
    """Creating and editing a ticket records events on its timeline."""

    def setUp(self):
        self.team_a = Team.objects.create(name="Plumbing")
        self.team_b = Team.objects.create(name="Electrical")
        self.svc_a = Service.objects.create(name="Pipes", owning_team=self.team_a)
        self.svc_b = Service.objects.create(name="Wiring", owning_team=self.team_b)
        self.user = User.objects.create_user(
            username="tl@x.com", email="tl@x.com", password=GOOD_PASSWORD, role="reporter")
        self.client.login(username="tl@x.com", password=GOOD_PASSWORD)

    def test_creation_is_logged(self):
        """Filing a ticket records a 'created' timeline entry."""
        self.client.post("/incidents/form", {
            "title": "T", "description": "d", "service": self.svc_a.pk, "priority": "low"})
        inc = Incident.objects.get(title="T")
        self.assertTrue(inc.incidentupdate_set.filter(update_type="created").exists())

    def test_edit_logs_severity_and_detail_changes(self):
        """Changing severity and details records severity and edit entries."""
        self.client.post("/incidents/form", {
            "title": "T", "description": "d", "service": self.svc_a.pk, "priority": "low"})
        inc = Incident.objects.get(title="T")
        self.client.post(f"/incidents/{inc.pk}/edit/", {
            "title": "T", "description": "d2", "service": self.svc_b.pk,
            "priority": "high", "building": "", "room": ""})
        types = set(inc.incidentupdate_set.values_list("update_type", flat=True))
        self.assertIn("severity", types)
        self.assertIn("edit", types)


class EditTimelineDetailTests(TestCase):
    """Editing a ticket logs the old and new value of each changed field."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.incident = Incident.objects.create(
            title="Old title", description="old desc", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open",
            priority="low", building="A", room="1")
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)

    def test_edit_logs_old_and_new_values(self):
        """Changing the title records an entry naming both the old and new value."""
        self.client.post(f"/incidents/{self.incident.pk}/edit/", {
            "title": "New title", "description": "old desc", "service": self.svc.pk,
            "priority": "low", "building": "A", "room": "1"})
        bodies = list(self.incident.incidentupdate_set.filter(update_type="edit")
                      .values_list("body", flat=True))
        self.assertTrue(any("Old title" in b and "New title" in b for b in bodies))


class CommentEdgeTests(TestCase):
    """Comment and note rules: length, type by role, empty handling."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.inc = Incident.objects.create(
            title="T", description="d", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open")

    def post_comment(self, user, body):
        self.client.login(username=user, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/comment/", {"body": body})

    def test_reporter_comment_is_type_comment(self):
        """A reporter's post is stored as a comment."""
        self.post_comment("r@x.com", "please hurry")
        self.assertTrue(self.inc.incidentupdate_set.filter(update_type="comment").exists())

    def test_solver_comment_is_type_note(self):
        """A solver's post is stored as a solver note."""
        self.post_comment("s@x.com", "looking into it")
        self.assertTrue(self.inc.incidentupdate_set.filter(update_type="solver_note").exists())

    def test_empty_comment_is_ignored(self):
        """A blank comment creates no timeline row."""
        self.post_comment("r@x.com", "   ")
        self.assertEqual(self.inc.incidentupdate_set.count(), 0)

    def test_comment_at_limit_is_accepted(self):
        """A 1000-character comment is accepted."""
        self.post_comment("r@x.com", "x" * 1000)
        self.assertEqual(self.inc.incidentupdate_set.filter(update_type="comment").count(), 1)

    def test_comment_over_limit_is_rejected(self):
        """A comment longer than 1000 characters is rejected."""
        self.post_comment("r@x.com", "x" * 1001)
        self.assertEqual(self.inc.incidentupdate_set.count(), 0)
