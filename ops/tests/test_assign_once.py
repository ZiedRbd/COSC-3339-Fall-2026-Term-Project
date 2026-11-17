"""A ticket another request already handed out is not handed out a second time."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Incident, IncidentUpdate, Notification, Service, Shift, Team, TeamMember, User
from ops.scheduling import assign_on_creation, assign_waiting
from ops.tests.helpers import GOOD_PASSWORD


class AssignOnceTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Port")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.tim,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def ticket(self, title="Leak"):
        return Incident.objects.create(title=title, description="d", service=self.service,
                                       reported_by=self.reporter, assigned_team=self.team)

    def entries(self, ticket, kind):
        return IncidentUpdate.objects.filter(incident=ticket, update_type=kind).count()

    def test_a_ticket_handed_out_by_another_request_is_not_assigned_again(self):
        # This request holds the ticket as it was when it was filed
        mine = self.ticket()
        # Another request files its own ticket and, on the way, hands out the one waiting
        self.assertEqual(assign_waiting(self.team), 1)
        self.assertEqual(assign_on_creation(mine), self.tim)
        mine.refresh_from_db()
        self.assertEqual(mine.status, "assigned")
        self.assertEqual(mine.assigned_to, self.tim)
        self.assertEqual(self.entries(mine, "assignment"), 1)
        self.assertEqual(Notification.objects.filter(incident=mine, event="assigned").count(), 1)

    def test_it_is_not_put_back_in_the_queue_when_the_solver_filled_up_meanwhile(self):
        for n in range(2):
            assign_on_creation(self.ticket(f"Earlier {n}"))
        mine = self.ticket()
        # The other request gives this ticket the solver's third and last slot
        self.assertEqual(assign_waiting(self.team), 1)
        assign_on_creation(mine)
        mine.refresh_from_db()
        self.assertEqual(mine.status, "assigned")
        self.assertEqual(mine.assigned_to, self.tim)
        self.assertEqual(self.entries(mine, "assignment_failed"), 0)
        self.assertEqual(Notification.objects.filter(event="queued").count(), 0)

    def test_a_ticket_still_waits_when_everyone_is_full(self):
        for n in range(3):
            assign_on_creation(self.ticket(f"Earlier {n}"))
        fourth = self.ticket()
        self.assertIsNone(assign_on_creation(fourth))
        fourth.refresh_from_db()
        self.assertEqual(fourth.status, "open")
        self.assertEqual(self.entries(fourth, "assignment_failed"), 1)

