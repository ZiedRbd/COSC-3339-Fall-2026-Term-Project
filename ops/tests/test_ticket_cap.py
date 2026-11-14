"""Nobody holds more than three unfinished tickets: primary fills first, then secondary, then the queue."""
import io
from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from ops.models import Incident, IncidentUpdate, Notification, Service, Shift, Team, TeamMember, User
from ops.scheduling import (
    MAX_ACTIVE_TICKETS, active_ticket_count, assign_on_creation, assign_waiting, pick_solver, reassign,
)
from ops.tests.helpers import GOOD_PASSWORD


class CapSetup:
    """A team with a primary, a secondary, a lead and an administrator, and a way to file tickets."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Lee", role="reporter")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             first_name="Jane", last_name="Okoro", role="solver")
        self.admin = User.objects.create_superuser(username="admin@x.com", email="admin@x.com",
                                                   password=GOOD_PASSWORD, role="solver")
        for u in (self.tim, self.jane, self.lead):
            TeamMember.objects.create(user=u, team=self.team)
        self.team.lead = self.lead
        self.team.save()
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.lead, on_call_role="secondary",
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=23))

    def file(self, n=1):
        """File n tickets through assign_on_creation and return them, oldest first."""
        made = []
        for i in range(n):
            inc = Incident.objects.create(title=f"Leak {Incident.objects.count() + 1}", description="d",
                                          service=self.svc, reported_by=self.reporter, priority="low")
            assign_on_creation(inc)
            inc.refresh_from_db()
            made.append(inc)
        return made

    def holders(self, tickets):
        return [t.assigned_to for t in tickets]


class TicketCapTests(CapSetup, TestCase):
    def test_primary_takes_three_then_secondary_takes_three(self):
        tickets = self.file(6)
        self.assertEqual(self.holders(tickets), [self.tim] * 3 + [self.jane] * 3)
        self.assertEqual(active_ticket_count(self.tim), MAX_ACTIVE_TICKETS)
        self.assertEqual(active_ticket_count(self.jane), MAX_ACTIVE_TICKETS)

    def test_seventh_waits_and_the_lead_is_told(self):
        seventh = self.file(7)[-1]
        self.assertIsNone(seventh.assigned_to)
        self.assertEqual(seventh.status, "open")
        note = IncidentUpdate.objects.filter(incident=seventh, update_type="assignment_failed").get()
        self.assertIn("Everyone on call for Plumbing is full", note.body)
        self.assertEqual(
            [(n.user, n.event) for n in Notification.objects.filter(event="queued")], [(self.lead, "queued")],
        )

    def test_eighth_tells_the_superusers_not_the_lead_again(self):
        self.file(8)
        self.assertEqual(Notification.objects.filter(user=self.lead).count(), 1)
        admin_note = Notification.objects.get(user=self.admin)
        self.assertEqual(admin_note.event, "queued")
        self.assertIn("2 tickets are waiting", admin_note.message)

    def test_nobody_on_call_is_a_different_message_and_no_notification(self):
        Shift.objects.all().delete()
        ticket = self.file(1)[0]
        note = IncidentUpdate.objects.filter(incident=ticket, update_type="assignment_failed").get()
        self.assertIn("Nobody is on call for Plumbing", note.body)
        self.assertFalse(Notification.objects.exists())

    def test_resolving_one_frees_a_slot_for_the_queue(self):
        tickets = self.file(7)
        done = tickets[0]
        done.status = "resolved"
        done.save()
        self.assertEqual(assign_waiting(self.team), 1)
        tickets[-1].refresh_from_db()
        self.assertEqual(tickets[-1].assigned_to, self.tim)
        self.assertEqual(tickets[-1].status, "assigned")

    def test_queue_is_served_oldest_first_and_stops_when_full(self):
        Shift.objects.all().delete()
        waiting = self.file(5)
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        self.assertEqual(assign_waiting(self.team), 3)
        for t in waiting:
            t.refresh_from_db()
        self.assertEqual(self.holders(waiting), [self.tim] * 3 + [None, None])

    def test_pick_solver_skips_a_full_primary(self):
        self.file(3)
        self.assertEqual(pick_solver(self.team), self.jane)

    def test_reassign_to_a_full_solver_is_refused(self):
        self.file(3)
        ticket = self.file(1)[0]
        self.assertEqual(ticket.assigned_to, self.jane)
        self.assertEqual(reassign(ticket, self.tim, self.lead), "Tim Diaz already holds 3 tickets")
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.jane)

    def test_reassign_to_the_secondary_is_allowed(self):
        ticket = self.file(1)[0]
        self.assertEqual(ticket.assigned_to, self.tim)
        self.assertIsNone(reassign(ticket, self.jane, self.lead))
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.jane)

    def test_reassign_to_someone_not_on_call_is_still_refused(self):
        ticket = self.file(1)[0]
        self.assertEqual(reassign(ticket, self.lead, self.lead), "Pat Lee is not on call for Plumbing right now")

    def test_resolved_and_closed_do_not_count(self):
        tickets = self.file(3)
        for t, status in zip(tickets, ("resolved", "closed", "in_progress")):
            t.status = status
            t.save()
        self.assertEqual(active_ticket_count(self.tim), 1)


class QueueHandOutTests(CapSetup, TestCase):
    """A waiting ticket is handed out the moment a slot opens, with nobody loading a page."""

    def test_resolving_through_the_page_hands_out_the_waiting_ticket(self):
        tickets = self.file(7)
        held = tickets[0]
        held.status = "in_progress"
        held.save()
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{held.pk}/transition/", {"new_status": "resolved"})
        tickets[-1].refresh_from_db()
        self.assertEqual((tickets[-1].assigned_to, tickets[-1].status), (self.tim, "assigned"))

    def test_deleting_a_ticket_hands_out_the_waiting_ticket(self):
        tickets = self.file(7)
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{tickets[0].pk}/delete/")
        tickets[-1].refresh_from_db()
        self.assertEqual(tickets[-1].assigned_to, self.tim)

    def test_the_minute_command_hands_out_waiting_tickets(self):
        Shift.objects.all().delete()
        ticket = self.file(1)[0]
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        out = io.StringIO()
        call_command("escalate", stdout=out)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.tim)
        self.assertIn("1 waiting ticket(s) assigned", out.getvalue())

    def test_reassigning_a_ticket_away_hands_the_freed_slot_to_the_queue(self):
        """Jane hands nothing back: Tim gives one of his three to nobody new, so only a resolve frees him."""
        tickets = self.file(7)
        tickets[3].status = "resolved"
        tickets[3].save()
        self.assertIsNone(reassign(tickets[0], self.jane, self.lead))
        tickets[-1].refresh_from_db()
        self.assertEqual(tickets[-1].assigned_to, self.tim)

    def test_an_automatic_hand_out_says_so_and_credits_nobody_else(self):
        tickets = self.file(7)
        tickets[0].status = "resolved"
        tickets[0].save()
        self.client.login(username="jane@x.com", password=GOOD_PASSWORD)
        self.client.get("/incidents/list")
        entry = IncidentUpdate.objects.filter(incident=tickets[-1], update_type="assignment").get()
        self.assertEqual(entry.body, "Assigned automatically to Tim Diaz, on call for Plumbing")
        self.assertEqual(entry.author, self.tim)


class QueueNotificationTests(CapSetup, TestCase):
    """Who hears about a waiting ticket, and what the message says."""

    def test_the_lead_is_told_which_ticket_is_waiting_and_is_emailed(self):
        seventh = self.file(7)[-1]
        note = Notification.objects.get(user=self.lead, event="queued")
        self.assertEqual(note.incident, seventh)
        self.assertIn(f"Ticket #{seventh.pk} (Pipes, low) is waiting", note.message)
        self.assertIn("everyone on call for Plumbing holds 3 tickets", note.message)
        self.assertIn(self.lead.email, [m.to[0] for m in mail.outbox])

    def test_a_ticket_whose_escalation_ran_out_is_not_counted_as_waiting(self):
        """With a flagged ticket on the team, the first waiting ticket still goes to the lead."""
        Incident.objects.create(title="Old", description="d", service=self.svc, reported_by=self.reporter,
                                assigned_team=self.team, status="open", is_unassigned_after_escalation=True)
        self.file(7)
        self.assertEqual(Notification.objects.filter(user=self.lead, event="queued").count(), 1)
        self.assertFalse(Notification.objects.filter(user=self.admin).exists())

    def test_with_no_administrator_the_lead_hears_about_every_waiting_ticket(self):
        self.admin.delete()
        self.file(8)
        self.assertEqual(Notification.objects.filter(user=self.lead, event="queued").count(), 2)

    def test_with_no_lead_the_administrator_hears_about_the_first_one(self):
        self.team.lead = None
        self.team.save()
        self.file(7)
        self.assertEqual(Notification.objects.filter(user=self.admin, event="queued").count(), 1)

    def test_an_inactive_lead_is_not_told(self):
        self.lead.is_active = False
        self.lead.save()
        self.file(7)
        self.assertFalse(Notification.objects.filter(user=self.lead).exists())
        self.assertEqual(Notification.objects.filter(user=self.admin, event="queued").count(), 1)

    def test_the_administrator_can_open_the_ticket_the_notification_links_to(self):
        eighth = self.file(8)[-1]
        self.client.login(username="admin@x.com", password=GOOD_PASSWORD)
        note = Notification.objects.get(user=self.admin)
        resp = self.client.get(f"/notifications/{note.pk}/open/", follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], f"/incidents/{eighth.pk}/")
        self.assertNotContains(resp, "You do not have access")


class SolverMessageTests(CapSetup, TestCase):
    """Every message to a solver has the ticket number, the service, the severity and what to do."""

    def assert_complete(self, message, ticket):
        for part in (f"#{ticket.pk}", "Pipes", "low", "move it to In Progress"):
            self.assertIn(part, message)

    def test_automatic_assignment(self):
        ticket = self.file(1)[0]
        self.assert_complete(Notification.objects.get(user=self.tim).message, ticket)

    def test_reassignment_by_the_lead(self):
        ticket = self.file(1)[0]
        reassign(ticket, self.jane, self.lead)
        note = Notification.objects.get(user=self.jane)
        self.assert_complete(note.message, ticket)
        self.assertIn("was reassigned to you", note.message)

    def test_reassigning_a_ticket_already_in_progress_says_to_carry_on(self):
        ticket = self.file(1)[0]
        ticket.status = "in_progress"
        ticket.save()
        reassign(ticket, self.jane, self.lead)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertIn("already In Progress", Notification.objects.get(user=self.jane).message)


class BellHygieneTests(CapSetup, TestCase):
    def test_a_deleted_tickets_notifications_leave_the_bell(self):
        ticket = self.file(1)[0]
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertContains(self.client.get("/profile/"), f"Ticket #{ticket.pk}")
        ticket.is_deleted = True
        ticket.save()
        resp = self.client.get("/profile/")
        self.assertNotContains(resp, "notification-badge")
        self.assertContains(resp, "No new notifications")

    def test_mark_all_read_never_sends_the_browser_to_another_site(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        resp = self.client.post("/notifications/read-all/", HTTP_REFERER="https://evil.example/steal")
        self.assertEqual(resp.url, "/")
        resp = self.client.post("/notifications/read-all/", HTTP_REFERER="http://testserver/profile/")
        self.assertEqual(resp.url, "http://testserver/profile/")
