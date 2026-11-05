"""Tickets nobody starts on move up the team's escalation policy, one tier at a time."""
import io
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from ops.models import EscalationTier, Incident, IncidentUpdate, Notification, Service, Shift, Team, TeamMember, User
from ops.scheduling import assign_on_creation, assign_waiting, escalate_due, reassign
from ops.tests.helpers import GOOD_PASSWORD


class EscalationTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Lee", role="reporter")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        for u in (self.tim, self.lead):
            TeamMember.objects.create(user=u, team=self.team)
        self.team.lead = self.lead
        self.team.save()
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="lead", wait_minutes=10)
        EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="administration")

    def file(self, priority="medium"):
        inc = Incident.objects.create(title="Leak", description="d", service=self.svc,
                                      reported_by=self.reporter, priority=priority)
        assign_on_creation(inc)
        inc.refresh_from_db()
        return inc

    def later(self, minutes):
        return timezone.now() + timedelta(minutes=minutes)

    def test_assignment_starts_the_clock_at_tier_one(self):
        inc = self.file()
        self.assertEqual(inc.assigned_to, self.tim)
        self.assertIsNotNone(inc.escalation_timer_started_at)
        self.assertEqual(inc.escalation_level, 0)

    def test_nothing_moves_before_the_wait_is_up(self):
        inc = self.file()
        self.assertEqual(escalate_due(self.later(4)), 0)
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.tim)

    def test_medium_ticket_moves_to_the_lead_after_five_minutes(self):
        inc = self.file()
        self.assertEqual(escalate_due(self.later(5)), 1)
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.lead)
        self.assertEqual(inc.status, "assigned")
        self.assertEqual(inc.escalation_level, 1)
        entry = IncidentUpdate.objects.get(incident=inc, update_type="escalation")
        self.assertIn("Tim Diaz did not start work within 5 minutes", entry.body)
        self.assertIn("Escalated to tier 2: Pat Lee", entry.body)
        self.assertEqual(entry.old_assignee, self.tim)
        self.assertEqual(entry.new_assignee, self.lead)
        note = Notification.objects.get(user=self.lead, event="escalated")
        self.assertIn(f"#{inc.pk}", note.message)

    def test_critical_ticket_waits_half_as_long(self):
        inc = self.file("critical")
        self.assertEqual(escalate_due(self.later(2)), 0)
        self.assertEqual(escalate_due(self.later(2.5)), 1)

    def test_low_ticket_waits_twice_as_long(self):
        inc = self.file("low")
        self.assertEqual(escalate_due(self.later(9)), 0)
        self.assertEqual(escalate_due(self.later(10)), 1)

    def test_in_progress_stops_the_clock(self):
        inc = self.file()
        inc.status = "in_progress"
        inc.save()
        self.assertEqual(escalate_due(self.later(60)), 0)

    def test_the_lead_waiting_too_long_runs_the_policy_out(self):
        inc = self.file()
        escalate_due(self.later(5))
        self.assertEqual(escalate_due(self.later(14)), 0, "the lead still has a minute")
        self.assertEqual(escalate_due(self.later(15)), 1)
        inc.refresh_from_db()
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")
        self.assertTrue(inc.is_unassigned_after_escalation)
        self.assertEqual(inc.escalation_level, 2)
        last = IncidentUpdate.objects.filter(incident=inc, update_type="escalation").latest("id")
        self.assertIn("Escalation ran out", last.body)
        self.assertTrue(Notification.objects.filter(user=self.lead, event="final_escalation").exists())
        self.assertEqual(escalate_due(self.later(600)), 0, "a ticket that ran out stays put")

    def test_a_ticket_that_ran_out_is_not_handed_back_out_automatically(self):
        inc = self.file()
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        self.assertEqual(assign_waiting(self.team), 0)

    def test_the_lead_reassigning_it_clears_the_flag_and_restarts(self):
        inc = self.file()
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        inc.refresh_from_db()
        self.assertIsNone(reassign(inc, self.tim, self.lead))
        inc.refresh_from_db()
        self.assertFalse(inc.is_unassigned_after_escalation)
        self.assertEqual(inc.escalation_level, 0)
        self.assertEqual(inc.status, "assigned")

    def test_a_ticket_that_ran_out_sits_on_top_of_the_list_with_a_banner(self):
        old = self.file()
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        newer = self.file()
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        resp = self.client.get("/incidents/list")
        self.assertEqual([i.pk for i in resp.context["incidents"]], [old.pk, newer.pk])
        self.assertContains(resp, "Unassigned: escalation ran out")
        resp = self.client.get(f"/incidents/{old.pk}/")
        self.assertContains(resp, "escalation policy ran out")

    def test_reopen_restarts_from_tier_one(self):
        inc = self.file()
        escalate_due(self.later(5))
        inc.refresh_from_db()
        inc.status = "resolved"
        inc.save()
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "open"})
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.tim)
        self.assertEqual(inc.escalation_level, 0)

    def test_a_team_without_a_policy_never_escalates(self):
        EscalationTier.objects.all().delete()
        self.file()
        self.assertEqual(escalate_due(self.later(600)), 0)

    def test_the_command_reports_how_many_moved(self):
        self.file()
        out = io.StringIO()
        call_command("escalate", stdout=out)
        self.assertEqual(out.getvalue().strip(), "0 ticket(s) escalated")


class ReporterNotificationTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc, reported_by=self.reporter,
                                           assigned_team=self.team, assigned_to=self.tim, status="assigned")
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)

    def test_reporter_hears_when_work_starts_and_when_it_is_resolved(self):
        self.client.post(f"/incidents/{self.inc.pk}/transition/", {"new_status": "in_progress"})
        self.client.post(f"/incidents/{self.inc.pk}/transition/", {"new_status": "resolved"})
        self.assertEqual(
            list(self.reporter.notifications.order_by("id").values_list("event", flat=True)),
            ["work_started", "resolved"],
        )

    def test_the_solver_hears_when_a_ticket_lands_on_them(self):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.tim,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))
        inc = Incident.objects.create(title="Drip", description="d", service=self.svc, reported_by=self.reporter)
        assign_on_creation(inc)
        note = Notification.objects.get(user=self.tim, event="assigned")
        self.assertIn(f"#{inc.pk}", note.message)
        self.assertIsNone(note.read_at)
