"""Secondary on-call shifts: optional, added from the schedule page, with their own limits."""
import io
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from ops.models import Shift, Team, TeamMember, User
from ops.scheduling import pick_solver, validate_secondary, who_is_on_call, who_is_secondary_on_call
from ops.tests.helpers import GOOD_PASSWORD
from ops.tests.test_schedule_page import parts


def solver(email, first, last):
    return User.objects.create_user(username=email, email=email, password=GOOD_PASSWORD,
                                    first_name=first, last_name=last, role="solver")


class SecondaryShiftTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.other = Team.objects.create(name="HVAC")
        self.lead = solver("lead@x.com", "Pat", "Lee")
        self.tim = solver("tim@x.com", "Tim", "Diaz")
        self.jane = solver("jane@x.com", "Jane", "Okoro")
        self.team.lead = self.lead
        self.team.save()
        self.other.lead = self.lead
        self.other.save()
        for person in (self.lead, self.tim, self.jane):
            TeamMember.objects.create(user=person, team=self.team)
        TeamMember.objects.create(user=self.jane, team=self.other)
        # Tim is the primary for the next seven hours, so the team is covered
        self.base = timezone.localtime(timezone.now()).replace(minute=0, second=0, microsecond=0)
        self.primary = Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                                            starts_at=self.base - timedelta(hours=1),
                                            ends_at=self.base + timedelta(hours=7))
        self.url = f"/schedule/{self.team.pk}/"
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)

    def add(self, person, start_hours, end_hours, role="secondary", team=None):
        team = team or self.team
        data = {"solver": person.pk, **parts("starts_at", self.base + timedelta(hours=start_hours)),
                **parts("ends_at", self.base + timedelta(hours=end_hours))}
        if role:
            data["on_call_role"] = role
        return self.client.post(f"/schedule/{team.pk}/", data, follow=True).content.decode()

    def secondaries(self):
        return list(Shift.objects.filter(team=self.team, on_call_role="secondary").order_by("starts_at"))

    # ---- adding

    def test_lead_adds_a_secondary_shift_from_the_schedule_page(self):
        html = self.add(self.jane, 0, 8)
        self.assertIn("Secondary shift added", html)
        self.assertEqual([s.solver for s in self.secondaries()], [self.jane])
        self.assertEqual(who_is_secondary_on_call(self.team), self.jane)
        self.assertEqual(who_is_on_call(self.team), self.tim)

    def test_the_form_offers_the_role_and_a_shift_is_primary_when_none_is_sent(self):
        self.assertIn('name="on_call_role"', self.client.get(self.url).content.decode())
        self.add(self.jane, 7, 15, role=None)
        self.assertEqual(Shift.objects.get(solver=self.jane).on_call_role, "primary")

    def test_a_secondary_is_optional_and_may_leave_hours_empty(self):
        """Starting a secondary shift two days out is fine: only the primary must cover every hour."""
        self.add(self.jane, 48, 56)
        self.assertEqual(len(self.secondaries()), 1)

    def test_a_secondary_does_not_count_as_cover_for_the_primary(self):
        """A primary shift that leaves a gap is still refused although a secondary covers those hours."""
        self.add(self.jane, 0, 24)
        html = self.add(self.lead, 9, 17, role="primary")
        self.assertIn("missing coverage", html.lower())
        self.assertEqual(Shift.objects.filter(on_call_role="primary").count(), 1)

    # ---- length

    def test_a_secondary_shift_may_run_24_hours(self):
        self.add(self.jane, 0, 24)
        self.assertEqual(len(self.secondaries()), 1)

    def test_a_secondary_shift_longer_than_24_hours_is_refused(self):
        html = self.add(self.jane, 0, 25)
        self.assertIn("secondary shift on", html)
        self.assertIn("is longer than 24 hours", html)
        self.assertEqual(self.secondaries(), [])

    def test_a_primary_shift_is_still_capped_at_12_hours(self):
        html = self.add(self.jane, 7, 20, role="primary")
        self.assertIn("longer than 12 hours", html)

    # ---- one person, one place at a time

    def test_nobody_is_primary_and_secondary_at_once_on_one_team(self):
        html = self.add(self.tim, 2, 6)
        self.assertIn("Tim Diaz is already on call for Plumbing", html)
        self.assertEqual(self.secondaries(), [])

    def test_a_primary_shift_cannot_land_on_the_persons_own_secondary_shift(self):
        self.add(self.jane, 7, 15)
        html = self.add(self.jane, 7, 15, role="primary")
        self.assertIn("Jane Okoro is already secondary on call for Plumbing", html)
        self.assertEqual(Shift.objects.filter(on_call_role="primary").count(), 1)

    def test_nobody_is_secondary_here_while_on_call_for_another_team(self):
        Shift.objects.create(team=self.other, solver=self.jane, created_by=self.lead,
                             starts_at=self.base, ends_at=self.base + timedelta(hours=8))
        html = self.add(self.jane, 4, 12)
        self.assertIn("Jane Okoro is already on call for HVAC", html)
        self.assertEqual(self.secondaries(), [])

    def test_a_team_has_one_secondary_at_a_time(self):
        self.add(self.jane, 0, 8)
        html = self.add(self.lead, 4, 12)
        self.assertIn("double booked for the secondary", html.lower())
        self.assertEqual(len(self.secondaries()), 1)

    # ---- the 24 hour break

    def test_a_person_rests_24_hours_between_secondary_shifts(self):
        self.add(self.jane, 0, 8)
        html = self.add(self.jane, 20, 28)
        self.assertIn("Jane Okoro needs a 24 hour break between secondary shifts", html)
        self.assertEqual(len(self.secondaries()), 1)

    def test_exactly_24_hours_of_rest_is_enough(self):
        self.add(self.jane, 0, 8)
        self.add(self.jane, 32, 40)
        self.assertEqual(len(self.secondaries()), 2)

    def test_the_break_counts_a_secondary_shift_on_another_team(self):
        Shift.objects.create(team=self.other, solver=self.jane, created_by=self.lead, on_call_role="secondary",
                             starts_at=self.base, ends_at=self.base + timedelta(hours=8))
        html = self.add(self.jane, 12, 20)
        self.assertIn("needs a 24 hour break", html)

    def test_the_break_counts_a_secondary_shift_that_just_ended(self):
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.lead, on_call_role="secondary",
                             starts_at=self.base - timedelta(hours=10), ends_at=self.base - timedelta(hours=2))
        html = self.add(self.jane, 1, 9)
        self.assertIn("needs a 24 hour break", html)

    def test_a_different_person_may_follow_straight_after(self):
        self.add(self.jane, 0, 8)
        self.add(self.lead, 8, 16)
        self.assertEqual([s.solver for s in self.secondaries()], [self.jane, self.lead])

    def test_a_primary_shift_does_not_need_the_break(self):
        """The break is between secondary shifts only: Jane may be primary right after being secondary."""
        self.add(self.jane, 0, 7)
        self.add(self.jane, 7, 15, role="primary")
        self.assertEqual(Shift.objects.filter(solver=self.jane).count(), 2)

    # ---- the usual shift rules still apply

    def test_a_secondary_shift_cannot_start_in_the_past_or_end_before_it_starts(self):
        self.assertIn("cannot start in the past", self.add(self.jane, -3, 5))
        self.assertIn("ends before it starts", self.add(self.jane, 8, 4))
        self.assertEqual(self.secondaries(), [])

    def test_only_team_solvers_are_offered(self):
        outsider = solver("o@x.com", "Out", "Sider")
        self.add(outsider, 0, 8)
        self.assertEqual(self.secondaries(), [])

    def test_only_the_lead_adds_one(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.add(self.jane, 0, 8)
        self.assertEqual(self.secondaries(), [])

    # ---- the page, editing and deleting

    def test_the_page_lists_secondary_shifts_under_their_own_heading(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Secondary on call, optional", html)
        self.assertIn("No secondary shifts", html)
        self.add(self.jane, 0, 8)
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("No secondary shifts", html)
        self.assertIn('data-role="secondary"', html)

    def test_deleting_a_secondary_shift_never_needs_cover(self):
        self.add(self.jane, 0, 8)
        shift = self.secondaries()[0]
        self.client.post(f"{self.url}{shift.pk}/delete/")
        self.assertEqual(self.secondaries(), [])

    def test_editing_a_secondary_shift_leaves_the_primary_shifts_alone(self):
        """A secondary that starts where a primary ends must not drag that primary's boundary."""
        self.add(self.jane, 7, 15)
        shift = self.secondaries()[0]
        self.client.post(f"{self.url}{shift.pk}/edit/", {
            "solver": self.jane.pk, **parts("starts_at", self.base + timedelta(hours=9)),
            **parts("ends_at", self.base + timedelta(hours=15))})
        shift.refresh_from_db()
        self.primary.refresh_from_db()
        self.assertEqual(shift.starts_at, self.base + timedelta(hours=9))
        self.assertEqual(self.primary.ends_at, self.base + timedelta(hours=7))

    def test_editing_keeps_the_role_and_rechecks_the_limits(self):
        self.add(self.jane, 0, 8)
        shift = self.secondaries()[0]
        html = self.client.post(f"{self.url}{shift.pk}/edit/", {
            "on_call_role": "primary", "solver": self.lead.pk, **parts("starts_at", shift.starts_at),
            **parts("ends_at", shift.starts_at + timedelta(hours=30))}, follow=True).content.decode()
        self.assertIn("longer than 24 hours", html)
        self.client.post(f"{self.url}{shift.pk}/edit/", {
            "on_call_role": "primary", "solver": self.lead.pk, **parts("starts_at", shift.starts_at),
            **parts("ends_at", shift.ends_at)})
        shift.refresh_from_db()
        self.assertEqual((shift.solver, shift.on_call_role), (self.lead, "secondary"))

    def test_the_calendar_marks_the_secondary(self):
        self.add(self.jane, 0, 8)
        html = self.client.get("/calendar/").content.decode()
        self.assertIn('<span class="slot-role">secondary</span>', html)

    # ---- assignment uses it

    def test_tickets_go_to_the_secondary_once_it_exists(self):
        self.assertEqual(pick_solver(self.team), self.tim)
        self.add(self.jane, 0, 8)
        self.assertEqual(validate_secondary(self.team, self.secondaries()), [])
        self.assertEqual(who_is_secondary_on_call(self.team), self.jane)


class SeededSecondaryTests(TestCase):
    """seed_shifts adds a daily secondary shift wherever the rules allow one."""

    def setUp(self):
        call_command("seed", stdout=io.StringIO())
        call_command("seed_shifts", stdout=io.StringIO())

    def test_every_team_gets_secondary_shifts_that_pass_the_rules(self):
        for team in Team.objects.all():
            shifts = list(Shift.objects.filter(team=team, on_call_role="secondary", ends_at__gt=timezone.now()))
            self.assertTrue(shifts, team.name)
            self.assertEqual(validate_secondary(team, shifts), [], team.name)

    def test_nobody_is_seeded_as_primary_and_secondary_at_once(self):
        for shift in Shift.objects.filter(on_call_role="secondary"):
            clash = Shift.objects.filter(solver=shift.solver, starts_at__lt=shift.ends_at,
                                         ends_at__gt=shift.starts_at).exclude(pk=shift.pk)
            self.assertFalse(clash.exists(), shift)

    def test_a_rerun_does_not_pile_up_secondary_shifts(self):
        before = Shift.objects.filter(on_call_role="secondary").count()
        call_command("seed_shifts", stdout=io.StringIO())
        self.assertEqual(Shift.objects.filter(on_call_role="secondary").count(), before)
