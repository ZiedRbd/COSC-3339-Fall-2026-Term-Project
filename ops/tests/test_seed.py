"""The demo data the seed command loads."""
import io

from django.core.management import call_command
from datetime import timedelta
from django.utils import timezone
from django.test import TestCase

from ops.models import Incident, Service, Shift, Team, TeamMember, User
from ops.scheduling import assign_on_creation, who_is_on_call


class SeedLeadsTests(TestCase):
    """The seed sets up the leads and solvers the sprint roster asks for."""

    def test_seed_assigns_leads_and_three_solvers_per_team(self):
        """Pat leads two teams and is a Plumbing member. Maya leads one and is on no team."""
        call_command("seed", stdout=io.StringIO())
        pat = User.objects.get(email="pat.diaz@campusdesk.edu")
        maya = User.objects.get(email="maya.ortiz@campusdesk.edu")
        self.assertEqual(Team.objects.get(name="Plumbing").lead, pat)
        self.assertEqual(Team.objects.get(name="Electrical").lead, pat)
        self.assertEqual(Team.objects.get(name="IT Support").lead, maya)
        self.assertTrue(TeamMember.objects.filter(user=pat, team__name="Plumbing").exists())
        self.assertFalse(TeamMember.objects.filter(user=maya).exists())
        self.assertEqual(User.objects.filter(role="solver").count(), 10)
        for team in Team.objects.all():
            self.assertEqual(TeamMember.objects.filter(team=team, user__role="solver").count(), 3, team)
        self.assertFalse(Team.objects.filter(lead__isnull=True).exists())
        self.assertEqual({pat.role, maya.role}, {"solver"})


class ShiftSeederTests(TestCase):
    """seed_shifts fills a week of 24/7 cover without touching ticket ownership."""

    def setUp(self):
        call_command("seed", stdout=io.StringIO())
        call_command("seed_shifts", stdout=io.StringIO())
        self.now = timezone.now()

    def shifts_for(self, name):
        return list(Shift.objects.filter(team__name=name).order_by("starts_at"))

    def test_every_team_is_covered_with_no_gaps(self):
        """Each shift starts exactly where the previous one ended, starting before now."""
        for name in ["Plumbing", "Electrical", "IT Support"]:
            shifts = self.shifts_for(name)
            self.assertTrue(shifts, name)
            self.assertLessEqual(shifts[0].starts_at, self.now, name)
            for prev, nxt in zip(shifts, shifts[1:]):
                self.assertEqual(prev.ends_at, nxt.starts_at, name)

    def test_long_teams_reach_a_week_ahead(self):
        """Plumbing and IT Support are covered for at least six more days."""
        for name in ["Plumbing", "IT Support"]:
            self.assertGreaterEqual(self.shifts_for(name)[-1].ends_at, self.now + timedelta(days=6), name)

    def test_short_team_runs_out_tonight(self):
        """Electrical stops at midnight tonight, so tomorrow nobody is on call for it."""
        last = self.shifts_for("Electrical")[-1]
        self.assertLessEqual(last.ends_at, self.now + timedelta(days=1))
        self.assertIsNone(who_is_on_call(Team.objects.get(name="Electrical"), self.now + timedelta(days=2)))

    def test_lead_who_is_not_a_member_gets_no_shifts(self):
        """Maya leads IT Support but is on no team, so she is never on call."""
        self.assertFalse(Shift.objects.filter(solver__email="maya.ortiz@campusdesk.edu").exists())

    def test_rerun_replaces_shifts_without_duplicates(self):
        """Running it twice leaves the same number of shifts, not double."""
        before = Shift.objects.count()
        call_command("seed_shifts", stdout=io.StringIO())
        self.assertEqual(Shift.objects.count(), before)

    def test_rerun_does_not_change_who_owns_an_existing_ticket(self):
        """A ticket assigned before the rerun stays with its solver after it."""
        it = Team.objects.get(name="IT Support")
        wifi = Service.objects.get(name="Campus Wi-Fi")
        reporter = User.objects.get(email="demo@campusdesk.edu")
        incident = Incident.objects.create(
            title="Wi-Fi down", description="d", service=wifi, reported_by=reporter,
            assigned_team=it, priority="high")
        assign_on_creation(incident)
        incident.refresh_from_db()
        owner = incident.assigned_to
        self.assertIsNotNone(owner)
        call_command("seed_shifts", "--offset", "1", stdout=io.StringIO())
        self.assertNotEqual(who_is_on_call(it), owner)
        incident.refresh_from_db()
        self.assertEqual(incident.assigned_to, owner)


class ShiftSeederRotationTests(TestCase):
    """Blocks sit on the clock, every rota has more than one name, nobody covers two teams at once."""

    def setUp(self):
        call_command("seed", stdout=io.StringIO())
        call_command("seed_shifts", stdout=io.StringIO())

    def test_blocks_start_at_midnight_eight_or_sixteen(self):
        for shift in Shift.objects.all():
            local = timezone.localtime(shift.starts_at)
            self.assertEqual((local.hour % 8, local.minute), (0, 0), shift)

    def test_no_shift_crosses_midnight(self):
        for shift in Shift.objects.all():
            start, end = timezone.localtime(shift.starts_at), timezone.localtime(shift.ends_at)
            self.assertLessEqual(end, start.replace(hour=0, minute=0) + timedelta(days=1), shift)

    def test_every_full_week_rota_rotates_at_least_two_people(self):
        for name in ["Plumbing", "IT Support"]:
            people = set(Shift.objects.filter(team__name=name).values_list("solver_id", flat=True))
            self.assertGreaterEqual(len(people), 2, name)

    def test_nobody_is_on_call_for_two_teams_at_once(self):
        for shift in Shift.objects.all():
            clash = Shift.objects.filter(solver=shift.solver, starts_at__lt=shift.ends_at,
                                         ends_at__gt=shift.starts_at).exclude(team=shift.team)
            self.assertFalse(clash.exists(), f"{shift} clashes with {clash.first()}")
