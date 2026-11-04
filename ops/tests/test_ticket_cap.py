"""Nobody holds more than three unfinished tickets: primary fills first, then secondary, then the queue."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Incident, IncidentUpdate, Notification, Service, Shift, Team, TeamMember, User
from ops.scheduling import (
    MAX_ACTIVE_TICKETS, active_ticket_count, assign_on_creation, assign_waiting, pick_solver, reassign,
)
from ops.tests.helpers import GOOD_PASSWORD


class TicketCapTests(TestCase):
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
            [(n.user, n.event) for n in Notification.objects.all()], [(self.lead, "queued")],
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
