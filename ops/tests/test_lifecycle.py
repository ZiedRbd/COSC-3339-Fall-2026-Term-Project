"""Legal and illegal status transitions."""
from django.test import TestCase

from ops.models import Incident, Service, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class LifecycleEdgeTests(TestCase):
    """Exhaustive legal and illegal transition coverage for the state machine."""

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
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)

    def move(self, to):
        self.client.post(f"/incidents/{self.inc.pk}/transition/", {"new_status": to})
        self.inc.refresh_from_db()
        return self.inc.status

    def set_status(self, status):
        self.inc.status = status
        self.inc.save()

    def test_full_legal_path(self):
        """An assigned ticket walks to closed one step at a time."""
        self.set_status("assigned")
        self.assertEqual(self.move("in_progress"), "in_progress")
        self.assertEqual(self.move("resolved"), "resolved")
        self.assertEqual(self.move("closed"), "closed")

    def test_reopen_from_resolved(self):
        """A resolved ticket can be reopened to open."""
        self.set_status("resolved")
        self.assertEqual(self.move("open"), "open")

    def test_reopen_from_closed(self):
        """A closed ticket can be reopened to open."""
        self.set_status("closed")
        self.assertEqual(self.move("open"), "open")

    def test_illegal_open_to_resolved(self):
        """Open cannot jump straight to resolved."""
        self.assertEqual(self.move("resolved"), "open")

    def test_illegal_open_to_in_progress(self):
        """Open cannot skip to in progress."""
        self.assertEqual(self.move("in_progress"), "open")

    def test_illegal_backward_in_progress_to_open(self):
        """In progress cannot go back to open without reopening."""
        self.set_status("in_progress")
        self.assertEqual(self.move("open"), "in_progress")

    def test_illegal_backward_assigned_to_open(self):
        """Assigned cannot go back to open."""
        self.set_status("assigned")
        self.assertEqual(self.move("open"), "assigned")

    def test_illegal_assigned_to_resolved(self):
        """Assigned cannot skip in progress."""
        self.set_status("assigned")
        self.assertEqual(self.move("resolved"), "assigned")

    def test_open_has_no_manual_move(self):
        """A solver cannot move an unassigned open ticket anywhere by hand."""
        self.assertEqual(self.move("assigned"), "open")

    def test_garbage_status_rejected(self):
        """An unknown status value is rejected."""
        self.assertEqual(self.move("banana"), "open")

    def test_transition_requires_post(self):
        """A GET to the transition URL changes nothing."""
        self.client.get(f"/incidents/{self.inc.pk}/transition/")
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, "open")

    def test_reporter_cannot_transition(self):
        """A reporter cannot change status even with a direct POST."""
        self.client.logout()
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.set_status("assigned")
        self.assertEqual(self.move("in_progress"), "assigned")

    def test_transition_records_author_and_time(self):
        """A successful transition logs who made it and when."""
        self.set_status("assigned")
        self.move("in_progress")
        row = self.inc.incidentupdate_set.get(update_type="status_change")
        self.assertEqual(row.author, self.solver)
        self.assertIsNotNone(row.created_at)
        self.assertEqual(row.old_status, "assigned")
        self.assertEqual(row.new_status, "in_progress")


class StatusLabelTests(TestCase):
    """The list, the buttons and the timeline all show the same label for a status."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.solver = User.objects.create_user(username="s@x.com", email="s@x.com", password=GOOD_PASSWORD,
                                               first_name="Sam", last_name="Okoro", role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Lee", role="reporter")
        service = Service.objects.create(name="Sinks", owning_team=self.team)
        self.incident = Incident.objects.create(title="Leak", description="d", service=service,
                                                reported_by=self.reporter, assigned_team=self.team,
                                                assigned_to=self.solver, status="assigned", priority="low")
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)

    def test_list_button_and_badge_use_the_label(self):
        html = self.client.get("/incidents/list").content.decode()
        self.assertIn('class="btn-small">In Progress</button>', html)
        self.assertIn("<th>Actions</th>", html)
        self.assertNotIn(">in_progress<", html)
        self.assertNotIn("In_Progress", html)

    def test_detail_button_and_timeline_use_the_label(self):
        self.client.post(f"/incidents/{self.incident.pk}/transition/", {"new_status": "in_progress"})
        html = self.client.get(f"/incidents/{self.incident.pk}/").content.decode()
        self.assertIn("Move to Resolved", html)
        self.assertIn(">In Progress</span>", html)
        self.assertNotIn("Inprogress", html)
        self.assertNotIn(">in_progress<", html)
