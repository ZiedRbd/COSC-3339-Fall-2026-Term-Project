"""The lead's scheduling page: adding, editing, and removing shifts."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


def parts(name, dt):
    """What the date picker and the 24-hour dropdown send for this instant."""
    local = timezone.localtime(dt)
    return {f"{name}_0": local.strftime("%Y-%m-%d"), f"{name}_1": local.strftime("%H:%M")}


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
        return self.client.post(self.url, {"solver": solver.pk, **parts("starts_at", start), **parts("ends_at", end)},
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
            "solver": self.jane.pk, **parts("starts_at", self.running.starts_at), **parts("ends_at", self.running.ends_at)})
        self.running.refresh_from_db()
        self.assertEqual(self.running.solver, self.jane)

    def test_solver_dropdown_only_offers_team_members(self):
        outsider = User.objects.create_user(username="o@x.com", email="o@x.com", password=GOOD_PASSWORD,
                                            first_name="Out", last_name="Sider", role="solver")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Jane Okoro", html)
        self.assertNotIn("Out Sider", html)


class ShiftFormTests(SchedulePageTests):
    """The form uses a 24-hour clock, refuses shifts that are over or inverted, and asks before saving."""

    def test_times_are_picked_from_a_24_hour_dropdown(self):
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn('type="date"', html)
        self.assertIn('<option value="16:00">16:00</option>', html)
        self.assertNotIn("datetime-local", html)

    def test_shift_that_is_already_over_is_refused(self):
        resp = self.add_as("lead@x.com", self.jane, self.base - timedelta(hours=10), self.base - timedelta(hours=2))
        self.assertEqual(Shift.objects.count(), 1)
        self.assertIn("already over", resp.content.decode())

    def test_shift_that_ends_before_it_starts_is_refused(self):
        resp = self.add_as("lead@x.com", self.jane, self.base + timedelta(hours=15), self.base + timedelta(hours=7))
        self.assertEqual(Shift.objects.count(), 1)
        self.assertIn("ends before it starts", resp.content.decode())
        self.assertNotIn("Constraint", resp.content.decode())

    def test_first_shift_that_starts_later_names_the_gap_from_now(self):
        """With nothing scheduled, a shift starting later leaves now uncovered, and the message says now."""
        Shift.objects.all().delete()
        resp = self.add_as("lead@x.com", self.jane, self.base + timedelta(hours=12), self.base + timedelta(hours=20))
        self.assertEqual(Shift.objects.count(), 0)
        self.assertIn("missing coverage from now (", resp.content.decode().lower())

    def test_confirm_modal_is_on_the_page(self):
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn("shift-modal", html)
        self.assertIn("schedule.js", html)


class ShiftPopupTests(SchedulePageTests):
    """The form sits in a popup: Add opens it empty, Edit opens it filled in, a refused save reopens it."""

    def test_page_has_the_add_button_and_a_closed_popup(self):
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn('id="add-shift"', html)
        self.assertIn('id="shift-form-modal" class="modal-overlay" data-add-url="/schedule/%d/" hidden' % self.team.pk, html)

    def test_edit_button_carries_the_shift_values(self):
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-solver="%d"' % self.tim.pk, html)
        self.assertIn('data-start-hour="%s"' % timezone.localtime(self.running.starts_at).strftime("%H:%M"), html)

    def test_refused_save_reopens_the_popup_with_the_problem(self):
        resp = self.add_as("lead@x.com", self.jane, self.base + timedelta(hours=9), self.base + timedelta(hours=17))
        html = resp.content.decode()
        self.assertIn('id="shift-form-modal" class="modal-overlay" data-add-url="/schedule/%d/">' % self.team.pk, html)
        self.assertIn("missing coverage", html.lower())
