"""Who is on call for a team."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from ops.models import Shift, Team, TeamMember, User
from ops.scheduling import on_call_roster, who_is_on_call
from ops.tests.helpers import GOOD_PASSWORD


class WhoIsOnCallTests(TestCase):
    """who_is_on_call and on_call_roster, read straight off the Shift table."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.other = Team.objects.create(name="HVAC")
        self.tim = User.objects.create_user(
            username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD, role="solver")
        self.jane = User.objects.create_user(
            username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        TeamMember.objects.create(user=self.jane, team=self.team)
        # Tim 08:00 to 16:00, then Jane 16:00 to 22:00, Chicago time
        self.at_8 = timezone.make_aware(datetime(2026, 10, 19, 8, 0))
        self.at_16 = timezone.make_aware(datetime(2026, 10, 19, 16, 0))
        self.at_22 = timezone.make_aware(datetime(2026, 10, 19, 22, 0))
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.tim,
                             starts_at=self.at_8, ends_at=self.at_16)
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.tim,
                             starts_at=self.at_16, ends_at=self.at_22)

    def test_solver_during_their_shift(self):
        """09:00 falls inside Tim's shift."""
        self.assertEqual(who_is_on_call(self.team, self.at_8 + timedelta(hours=1)), self.tim)

    def test_end_instant_belongs_to_the_next_shift(self):
        """Exactly 16:00 is Jane's, because the interval is half open."""
        self.assertEqual(who_is_on_call(self.team, self.at_16), self.jane)

    def test_one_second_before_the_end_is_still_the_first_shift(self):
        """15:59:59 is still Tim's."""
        self.assertEqual(who_is_on_call(self.team, self.at_16 - timedelta(seconds=1)), self.tim)

    def test_nobody_after_the_schedule_ends(self):
        """23:00 is past the last shift, so nobody is on call."""
        self.assertIsNone(who_is_on_call(self.team, self.at_22 + timedelta(hours=1)))

    def test_nobody_for_a_team_with_no_shifts(self):
        """HVAC has no schedule at all."""
        self.assertIsNone(who_is_on_call(self.other, self.at_8 + timedelta(hours=1)))

    def test_deactivated_solver_is_skipped(self):
        """A deactivated user is not on call even though a shift names them."""
        self.tim.is_active = False
        self.tim.save()
        self.assertIsNone(who_is_on_call(self.team, self.at_8 + timedelta(hours=1)))

    def test_solver_removed_from_the_team_is_skipped(self):
        """Taking Tim off the team takes him off call even though his shift row remains."""
        TeamMember.objects.filter(user=self.tim, team=self.team).delete()
        self.assertIsNone(who_is_on_call(self.team, self.at_8 + timedelta(hours=1)))

    def test_non_solver_is_skipped(self):
        """A shift that somehow names a reporter does not put them on call."""
        self.tim.role = "reporter"
        self.tim.save()
        self.assertIsNone(who_is_on_call(self.team, self.at_8 + timedelta(hours=1)))

    def test_at_defaults_to_now(self):
        """Calling without an instant uses the current time."""
        now = timezone.now()
        TeamMember.objects.create(user=self.jane, team=self.other)
        Shift.objects.create(team=self.other, solver=self.jane, created_by=self.jane,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))
        self.assertEqual(who_is_on_call(self.other), self.jane)

    def test_roster_returns_shifts_by_start_time_not_creation_order(self):
        """A shift created last but starting earliest comes back first."""
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.tim,
                             starts_at=self.at_8 - timedelta(hours=2), ends_at=self.at_8)
        roster = list(on_call_roster(self.team, self.at_8 - timedelta(hours=2), self.at_22))
        self.assertEqual([s.solver for s in roster], [self.jane, self.tim, self.jane])

    def test_roster_window_ending_at_a_shift_start_excludes_that_shift(self):
        """A window ending at 16:00 does not include the shift that starts at 16:00."""
        roster = list(on_call_roster(self.team, self.at_8, self.at_16))
        self.assertEqual([s.solver for s in roster], [self.tim])

    def test_roster_leaves_out_other_teams(self):
        """A HVAC shift in the same window stays out of the Plumbing roster."""
        TeamMember.objects.create(user=self.jane, team=self.other)
        Shift.objects.create(team=self.other, solver=self.jane, created_by=self.jane,
                             starts_at=self.at_8, ends_at=self.at_16)
        roster = list(on_call_roster(self.team, self.at_8, self.at_22))
        self.assertEqual([s.team for s in roster], [self.team, self.team])

    def test_roster_window_starting_at_a_shift_end_excludes_that_shift(self):
        """A window starting at 16:00 does not include the shift that ends at 16:00."""
        roster = list(on_call_roster(self.team, self.at_16, self.at_22))
        self.assertEqual([s.solver for s in roster], [self.jane])

    def test_roster_is_empty_outside_the_schedule(self):
        """A window after the last shift has nobody in it."""
        start = self.at_22 + timedelta(hours=1)
        self.assertEqual(list(on_call_roster(self.team, start, start + timedelta(hours=2))), [])
    def test_nobody_before_the_first_shift(self):
        """07:00 is before Tim starts, so nobody is on call yet."""
        self.assertIsNone(who_is_on_call(self.team, self.at_8 - timedelta(hours=1)))

    def test_overlapping_shifts_resolve_to_the_earlier_start(self):
        """If two shifts somehow overlap, the one that started first is on call."""
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.tim,
                             starts_at=self.at_8 + timedelta(hours=1), ends_at=self.at_16)
        self.assertEqual(who_is_on_call(self.team, self.at_8 + timedelta(hours=2)), self.tim)

    def test_same_instant_in_another_timezone_gives_the_same_answer(self):
        """09:00 Chicago written as 14:00 UTC is the same instant, so the same person."""
        at_utc = (self.at_8 + timedelta(hours=1)).astimezone(ZoneInfo("UTC"))
        self.assertEqual(who_is_on_call(self.team, at_utc), self.tim)
