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
        self.assertIn("Escalated to administration", last.body)
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
        self.assertContains(resp, "Unassigned: escalated to administration")
        resp = self.client.get(f"/incidents/{old.pk}/")
        self.assertContains(resp, "it was escalated to administration")

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

    def test_a_team_without_a_policy_gets_the_default_one_and_escalates(self):
        EscalationTier.objects.all().delete()
        inc = self.file()
        self.assertEqual(escalate_due(self.later(5)), 1)
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.lead)
        self.assertEqual([(t.escalate_to, t.wait_minutes) for t in self.team.escalation_tiers.all()],
                         [("on_call", 5), ("lead", 10)])

    def test_the_command_reports_how_many_moved(self):
        self.file()
        out = io.StringIO()
        call_command("escalate", stdout=out)
        self.assertEqual(out.getvalue().strip(), "0 ticket(s) escalated, 0 waiting ticket(s) assigned")


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


class EscalationEdgeTests(TestCase):
    """Tiers with nobody to give the ticket to, policies edited mid-flight, and old tickets."""

    setUp = EscalationTests.setUp
    file = EscalationTests.file
    later = EscalationTests.later

    def add_bob(self):
        bob = User.objects.create_user(username="bob@x.com", email="bob@x.com", password=GOOD_PASSWORD,
                                       first_name="Bob", last_name="Ray", role="solver")
        TeamMember.objects.create(user=bob, team=self.team)
        return bob

    def policy(self, *tiers):
        """Replace the policy: each tier is (escalate_to, wait) or (user, wait)."""
        EscalationTier.objects.all().delete()
        for number, (target, wait) in enumerate(tiers, start=1):
            if isinstance(target, User):
                EscalationTier.objects.create(team=self.team, tier_number=number, escalate_to="user",
                                              escalate_to_user=target, wait_minutes=wait)
            else:
                EscalationTier.objects.create(team=self.team, tier_number=number, escalate_to=target,
                                              wait_minutes=wait)

    def last_entry(self, inc):
        return IncidentUpdate.objects.filter(incident=inc, update_type="escalation").latest("id").body

    def test_the_example_policy_from_the_spec_runs_tier_by_tier(self):
        """On call 5, Bob 5, the lead 10: Bob at 5 minutes, the lead at 10, unassigned at 20."""
        bob = self.add_bob()
        self.policy(("on_call", 5), (bob, 5), ("lead", 10))
        inc = self.file()
        escalate_due(self.later(5))
        inc.refresh_from_db()
        self.assertEqual((inc.assigned_to, inc.escalation_level), (bob, 1))
        escalate_due(self.later(10))
        inc.refresh_from_db()
        self.assertEqual((inc.assigned_to, inc.escalation_level), (self.lead, 2))
        escalate_due(self.later(20))
        inc.refresh_from_db()
        self.assertTrue(inc.is_unassigned_after_escalation)
        self.assertEqual(Notification.objects.filter(user=bob, event="escalated").count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.lead, event="escalated").count(), 1)

    def test_a_tier_with_a_deactivated_person_is_passed_over(self):
        bob = self.add_bob()
        bob.is_active = False
        bob.save()
        self.policy(("on_call", 5), (bob, 5), ("lead", 10))
        inc = self.file()
        escalate_due(self.later(5))
        inc.refresh_from_db()
        self.assertEqual((inc.assigned_to, inc.escalation_level), (self.lead, 2))
        self.assertIn("Tier 2 had nobody available. Escalated to tier 3: Pat Lee", self.last_entry(inc))

    def test_a_named_person_who_left_the_team_is_passed_over(self):
        bob = self.add_bob()
        self.policy(("on_call", 5), (bob, 5), ("lead", 10))
        TeamMember.objects.filter(user=bob).delete()
        inc = self.file()
        escalate_due(self.later(5))
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.lead)

    def test_a_person_who_already_holds_three_tickets_is_passed_over(self):
        bob = self.add_bob()
        self.policy(("on_call", 5), (bob, 5), ("lead", 10))
        for n in range(3):
            Incident.objects.create(title=f"Busy {n}", description="d", service=self.svc, reported_by=self.reporter,
                                    assigned_team=self.team, assigned_to=bob, status="in_progress")
        inc = self.file()
        escalate_due(self.later(5))
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.lead)

    def test_a_ticket_is_never_escalated_to_the_person_who_already_holds_it(self):
        """The lead is the one on call. Tier 2 is the lead too, so the policy has nobody else and runs out."""
        Shift.objects.all().delete()
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.lead, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        inc = self.file()
        self.assertEqual(inc.assigned_to, self.lead)
        escalate_due(self.later(5))
        inc.refresh_from_db()
        self.assertTrue(inc.is_unassigned_after_escalation)
        self.assertFalse(Notification.objects.filter(user=self.lead, event="escalated").exists())
        self.assertTrue(Notification.objects.filter(user=self.lead, event="final_escalation").exists())

    def test_shortening_the_policy_does_not_strand_a_ticket_further_along(self):
        """The ticket is with the lead at tier 2 when the lead removes tier 2. It still runs out."""
        inc = self.file()
        escalate_due(self.later(5))
        EscalationTier.objects.filter(tier_number__gte=2).delete()
        self.assertEqual(escalate_due(self.later(600)), 1)
        inc.refresh_from_db()
        self.assertTrue(inc.is_unassigned_after_escalation)

    def test_running_out_names_the_tiers_that_had_nobody(self):
        bob = self.add_bob()
        bob.is_active = False
        bob.save()
        self.lead.is_active = False
        self.lead.save()
        self.policy(("on_call", 5), (bob, 5), ("lead", 10))
        inc = self.file()
        escalate_due(self.later(5))
        self.assertIn("Tiers 2 and 3 had nobody available. Escalated to administration", self.last_entry(inc))

    def test_an_administrator_is_not_told_to_reassign_a_ticket_they_cannot_reassign(self):
        admin = User.objects.create_superuser(username="admin@x.com", email="admin@x.com", password=GOOD_PASSWORD)
        inc = self.file()
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        self.assertIn("reassign it to a solver on call",
                      Notification.objects.get(user=self.lead, event="final_escalation").message)
        told = Notification.objects.get(user=admin, event="final_escalation").message
        self.assertIn("escalated to administration and is unassigned", told)
        self.assertIn("Nobody on Plumbing started work on it in time", told)
        self.assertNotIn("Open it and reassign", told)
        self.assertNotIn("no active lead", told)
        Notification.objects.all().delete()
        self.team.lead = None
        self.team.save()
        other = self.file()
        escalate_due(self.later(5))
        message = Notification.objects.get(user=admin, event="final_escalation").message
        self.assertIn("Plumbing has no active lead to reassign it", message)
        self.assertNotIn("Open it and reassign", message)

    def test_administration_is_the_last_tier_and_tells_the_administrator_and_the_lead(self):
        admin = User.objects.create_superuser(username="admin@x.com", email="admin@x.com", password=GOOD_PASSWORD)
        inc = self.file("high")
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        inc.refresh_from_db()
        self.assertEqual((inc.status, inc.assigned_to, inc.is_unassigned_after_escalation), ("open", None, True))
        self.assertIn("Escalated to administration: this ticket is unassigned and needs attention",
                      self.last_entry(inc))
        for person in (admin, self.lead):
            note = Notification.objects.get(user=person, event="final_escalation")
            self.assertIn(f"Ticket #{inc.pk} (Pipes, high) escalated to administration", note.message)
            self.assertEqual(note.get_event_display(), "Escalated to administration")

    def test_a_lead_who_is_also_an_administrator_is_told_once(self):
        self.lead.is_superuser = True
        self.lead.save()
        self.file()
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        self.assertEqual(Notification.objects.filter(user=self.lead, event="final_escalation").count(), 1)

    def test_an_edit_made_while_the_timer_runs_does_not_undo_the_escalation(self):
        """The reporter saves an edit after the ticket moved to the lead. The lead still has it."""
        inc = self.file()
        escalate_due(self.later(5))
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/edit/", {
            "title": "Leak, worse", "description": "d", "service": self.svc.pk, "priority": "medium"})
        inc.refresh_from_db()
        self.assertEqual((inc.title, inc.assigned_to, inc.escalation_level), ("Leak, worse", self.lead, 1))

    def test_the_timeline_states_the_wait_the_severity_really_gave(self):
        inc = self.file("high")
        escalate_due(self.later(3.75))
        self.assertIn("Tim Diaz did not start work within 3.75 minutes for a high ticket", self.last_entry(inc))
        low = self.file("low")
        escalate_due(self.later(10))
        self.assertIn("within 10 minutes for a low ticket", self.last_entry(low))

    def test_a_ticket_assigned_before_the_clock_existed_starts_waiting_now(self):
        inc = Incident.objects.create(title="Old", description="d", service=self.svc, reported_by=self.reporter,
                                      assigned_team=self.team, assigned_to=self.tim, status="assigned")
        self.assertEqual(escalate_due(), 0)
        inc.refresh_from_db()
        self.assertIsNotNone(inc.escalation_timer_started_at)
        self.assertEqual(escalate_due(self.later(5)), 1)

    def test_running_out_with_no_lead_tells_the_administrator(self):
        admin = User.objects.create_superuser(username="admin@x.com", email="admin@x.com", password=GOOD_PASSWORD)
        self.team.lead = None
        self.team.save()
        inc = self.file()
        escalate_due(self.later(5))
        inc.refresh_from_db()
        self.assertTrue(inc.is_unassigned_after_escalation)
        self.assertTrue(Notification.objects.filter(user=admin, event="final_escalation").exists())

    def test_the_escalation_notice_has_the_ticket_the_service_the_severity_and_what_to_do(self):
        inc = self.file("critical")
        escalate_due(self.later(2.5))
        message = Notification.objects.get(user=self.lead, event="escalated").message
        for part in (f"#{inc.pk}", "Pipes", "critical", "escalated to you at tier 2", "move it to In Progress"):
            self.assertIn(part, message)

    def test_a_ticket_started_between_two_runs_is_left_alone(self):
        inc = self.file()
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "in_progress"})
        self.assertEqual(escalate_due(self.later(600)), 0)
        inc.refresh_from_db()
        self.assertEqual((inc.assigned_to, inc.status), (self.tim, "in_progress"))

    def test_a_ran_out_ticket_can_go_to_the_secondary_when_the_primary_is_full(self):
        bob = self.add_bob()
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=bob, created_by=self.lead, on_call_role="secondary",
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        inc = self.file()
        escalate_due(self.later(5))
        escalate_due(self.later(15))
        for n in range(3):
            Incident.objects.create(title=f"Busy {n}", description="d", service=self.svc, reported_by=self.reporter,
                                    assigned_team=self.team, assigned_to=self.tim, status="assigned")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/reassign/", {"solver": bob.pk})
        inc.refresh_from_db()
        self.assertEqual((inc.assigned_to, inc.is_unassigned_after_escalation), (bob, False))
