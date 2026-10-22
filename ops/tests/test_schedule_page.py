"""The lead's scheduling page: adding, editing, and removing shifts."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


def local(dt):
    """The value a datetime-local input would send for this instant."""
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


class SchedulePageTests(TestCase):
    """Only the lead edits a schedule, and every change is checked as a whole."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.team.lead = self.lead
        self.team.save()
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             first_name="Jane", last_name="Okoro", role="solver")
        for u in (self.lead, self.tim, self.jane):
            TeamMember.objects.create(user=u, team=self.team)
        # A shift running right now, on the hour, so the schedule starts covered
        self.base = timezone.localtime(timezone.now()).replace(minute=0, second=0, microsecond=0)
        self.running = Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                                            starts_at=self.base - timedelta(hours=1),
                                            ends_at=self.base + timedelta(hours=7))
        self.url = f"/schedule/{self.team.pk}/"

    def add_as(self, email, solver, start, end):
        self.client.login(username=email, password=GOOD_PASSWORD)
        return self.client.post(self.url, {"solver": solver.pk, "starts_at": local(start), "ends_at": local(end)},
                                follow=True)

    def test_non_lead_is_sent_away(self):
        """A plain member cannot open the page."""
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lead_sees_the_upcoming_shifts(self):
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Upcoming shifts", html)
        self.assertIn("Tim Diaz", html)

    def test_lead_adds_a_shift_that_starts_where_the_last_one_ends(self):
        resp = self.add_as("lead@x.com", self.jane, self.base + timedelta(hours=7), self.base + timedelta(hours=15))
        self.assertEqual(Shift.objects.count(), 2)
        self.assertIn("Shift added", resp.content.decode())

    def test_a_gap_is_refused_and_named(self):
        """Leaving two hours uncovered is refused with the window in the message."""
        resp = self.add_as("lead@x.com", self.jane, self.base + timedelta(hours=9), self.base + timedelta(hours=17))
        self.assertEqual(Shift.objects.count(), 1)
        self.assertIn("missing coverage", resp.content.decode().lower())

    def test_an_overlap_is_refused(self):
        resp = self.add_as("lead@x.com", self.jane, self.base + timedelta(hours=5), self.base + timedelta(hours=13))
        self.assertEqual(Shift.objects.count(), 1)
        self.assertIn("double booked", resp.content.decode().lower())

    def test_deleting_a_shift_that_would_leave_a_hole_is_refused(self):
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.lead,
                             starts_at=self.base + timedelta(hours=7), ends_at=self.base + timedelta(hours=15))
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        resp = self.client.post(f"/schedule/{self.team.pk}/{self.running.pk}/delete/", follow=True)
        self.assertTrue(Shift.objects.filter(pk=self.running.pk).exists())
        self.assertIn("missing coverage", resp.content.decode().lower())

    def test_deleting_the_last_shift_is_allowed(self):
        last = Shift.objects.create(team=self.team, solver=self.jane, created_by=self.lead,
                                    starts_at=self.base + timedelta(hours=7), ends_at=self.base + timedelta(hours=15))
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/schedule/{self.team.pk}/{last.pk}/delete/")
        self.assertFalse(Shift.objects.filter(pk=last.pk).exists())

    def test_editing_swaps_the_solver(self):
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/schedule/{self.team.pk}/{self.running.pk}/edit/", {
            "solver": self.jane.pk, "starts_at": local(self.running.starts_at), "ends_at": local(self.running.ends_at)})
        self.running.refresh_from_db()
        self.assertEqual(self.running.solver, self.jane)

    def test_solver_dropdown_only_offers_team_members(self):
        outsider = User.objects.create_user(username="o@x.com", email="o@x.com", password=GOOD_PASSWORD,
                                            first_name="Out", last_name="Sider", role="solver")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Jane Okoro", html)
        self.assertNotIn("Out Sider", html)
