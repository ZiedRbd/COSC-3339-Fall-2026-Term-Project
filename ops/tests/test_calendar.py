"""The weekly on-call calendar and who may see what on it."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class CalendarTests(TestCase):
    """Reporters are kept out, solvers see their teams, leads see theirs plus an edit link."""

    def setUp(self):
        self.plumbing = Team.objects.create(name="Plumbing")
        self.hvac = Team.objects.create(name="HVAC")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.pat = User.objects.create_user(username="pat@x.com", email="pat@x.com", password=GOOD_PASSWORD,
                                            first_name="Pat", last_name="Lee", role="solver")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Maya", last_name="Ortiz", role="solver")
        self.rae = User.objects.create_user(username="rae@x.com", email="rae@x.com", password=GOOD_PASSWORD,
                                            role="reporter")
        TeamMember.objects.create(user=self.tim, team=self.plumbing)
        TeamMember.objects.create(user=self.pat, team=self.hvac)
        self.hvac.lead = self.lead
        self.hvac.save()
        now = timezone.now()
        Shift.objects.create(team=self.plumbing, solver=self.tim, created_by=self.tim,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))
        Shift.objects.create(team=self.hvac, solver=self.pat, created_by=self.pat,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))

    def page_as(self, email):
        self.client.login(username=email, password=GOOD_PASSWORD)
        return self.client.get("/calendar/")

    def test_logged_out_goes_to_login(self):
        resp = self.client.get("/calendar/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/login/"))

    def test_reporter_is_sent_to_profile(self):
        resp = self.page_as("rae@x.com")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/profile/"))

    def test_solver_sees_own_team_only(self):
        html = self.page_as("tim@x.com").content.decode()
        self.assertIn("Plumbing", html)
        self.assertIn("Tim Diaz", html)
        self.assertNotIn("HVAC", html)
        self.assertNotIn("Edit schedule", html)

    def test_lead_sees_the_team_they_lead_with_an_edit_link(self):
        html = self.page_as("lead@x.com").content.decode()
        self.assertIn("HVAC", html)
        self.assertIn("Pat Lee", html)
        self.assertIn("Edit schedule", html)
        self.assertIn(f"/schedule/{self.hvac.pk}/", html)

    def test_week_navigation_is_present(self):
        html = self.page_as("tim@x.com").content.decode()
        self.assertIn("Previous week", html)
        self.assertIn("Next week", html)
        self.assertIn("?start=", html)

    def test_another_week_shows_nobody(self):
        """Two weeks out there are no shifts, so every cell says Nobody."""
        far = (timezone.localdate() + timedelta(days=14)).isoformat()
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        html = self.client.get(f"/calendar/?start={far}").content.decode()
        self.assertNotIn("Tim Diaz", html)
        self.assertIn("Nobody", html)

    def test_nav_bar_shows_calendar_to_solvers_only(self):
        self.assertIn(">Calendar<", self.page_as("tim@x.com").content.decode())
        self.client.login(username="rae@x.com", password=GOOD_PASSWORD)
        self.assertNotIn(">Calendar<", self.client.get("/profile/").content.decode())
