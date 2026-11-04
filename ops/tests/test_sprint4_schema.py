"""The Sprint 4 tables and columns: escalation tiers, notifications, shift roles."""
import io
from datetime import timedelta

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from ops.models import EscalationTier, Incident, Notification, Shift, Team, TeamMember, User
from ops.scheduling import on_call_roster, who_is_on_call
from ops.tests.helpers import make_service, make_user


class EscalationTierTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")

    def test_a_policy_is_a_sequence_of_tiers(self):
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="lead", wait_minutes=10)
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="administration")
        self.assertEqual(
            [t.tier_number for t in self.team.escalation_tiers.all()], [1, 2, 3],
            "tiers come back in order no matter how they were saved",
        )

    def test_two_tiers_cannot_share_a_number(self):
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="lead", wait_minutes=5)

    def test_wait_must_be_positive_when_set(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=0)

    def test_seed_gives_every_team_a_default_policy(self):
        call_command("seed", stdout=io.StringIO())
        for team in Team.objects.all():
            self.assertEqual(
                [(t.escalate_to, t.wait_minutes) for t in team.escalation_tiers.all()],
                [("on_call", 5), ("lead", 10), ("administration", None)], team,
            )


class NotificationTests(TestCase):
    def test_unread_count_is_rows_without_read_at(self):
        user = make_user()
        Notification.objects.create(user=user, event="assigned", message="Ticket #1 is yours")
        Notification.objects.create(user=user, event="escalated", message="Ticket #2 came to you")
        seen = Notification.objects.create(user=user, event="resolved", message="Ticket #3 is done")
        seen.read_at = timezone.now()
        seen.save()
        self.assertEqual(user.notifications.filter(read_at__isnull=True).count(), 2)

    def test_newest_first(self):
        user = make_user()
        first = Notification.objects.create(user=user, event="assigned", message="first")
        second = Notification.objects.create(user=user, event="assigned", message="second")
        self.assertEqual(list(user.notifications.all()), [second, first])


class IncidentEscalationColumnsTests(TestCase):
    def test_new_tickets_start_with_no_timer_and_not_flagged(self):
        reporter = make_user("r@example.com")
        incident = Incident.objects.create(
            title="Leak", description="x", service=make_service(), reported_by=reporter,
        )
        self.assertIsNone(incident.escalation_timer_started_at)
        self.assertFalse(incident.is_unassigned_after_escalation)


class ShiftRoleTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.lead = make_user("lead@example.com")
        self.primary = make_user("primary@example.com")
        self.backup = make_user("backup@example.com")
        for solver in (self.primary, self.backup):
            solver.role = "solver"
            solver.save()
            TeamMember.objects.create(user=solver, team=self.team)
        self.now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.primary, created_by=self.lead,
                             starts_at=self.now - timedelta(hours=1), ends_at=self.now + timedelta(hours=7))
        Shift.objects.create(team=self.team, solver=self.backup, created_by=self.lead, on_call_role="secondary",
                             starts_at=self.now - timedelta(hours=1), ends_at=self.now + timedelta(hours=23))

    def test_a_shift_is_primary_unless_said_otherwise(self):
        self.assertEqual(Shift.objects.get(solver=self.primary).on_call_role, "primary")

    def test_the_secondary_is_not_the_person_on_call(self):
        self.assertEqual(who_is_on_call(self.team), self.primary)

    def test_the_roster_lists_primaries_only(self):
        roster = on_call_roster(self.team, self.now - timedelta(days=1), self.now + timedelta(days=1))
        self.assertEqual([s.solver for s in roster], [self.primary])
