"""The Sprint 5 columns: who removed a row and when, the ticket photo, and the tier an escalation moved to."""
from datetime import timedelta
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from ops.models import EscalationTier, Incident, IncidentUpdate, Notification, Service, Shift, Team, TeamMember, User
from ops.scheduling import assign_on_creation, escalate_due
from ops.tests.helpers import GOOD_PASSWORD
from ops.timeline import log_event

fill = import_module("ops.migrations.0016_fill_sprint5_columns").fill


class Sprint5SchemaTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = self.person("r@x.com", "Rae", "Port", "reporter")
        self.lead = self.person("lead@x.com", "Pat", "Lee", "solver")
        self.tim = self.person("tim@x.com", "Tim", "Diaz", "solver")
        for user in (self.tim, self.lead):
            TeamMember.objects.create(user=user, team=self.team)
        self.team.lead = self.lead
        self.team.save()
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="lead", wait_minutes=10)
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def person(self, email, first, last, role):
        return User.objects.create_user(username=email, email=email, password=GOOD_PASSWORD,
                                        first_name=first, last_name=last, role=role)

    def ticket(self):
        return Incident.objects.create(title="Leak", description="d", service=self.service,
                                       reported_by=self.reporter, assigned_team=self.team)

    def escalations(self, ticket):
        return list(IncidentUpdate.objects.filter(incident=ticket, update_type="escalation")
                    .order_by("id").values_list("escalated_to_tier", flat=True))

    def test_nothing_starts_out_removed(self):
        ticket = self.ticket()
        self.assertTrue(self.team.is_active)
        for row in (self.reporter, self.team, self.service, ticket):
            self.assertIsNone(row.removed_at)
            self.assertIsNone(row.removed_by)

    def test_a_row_records_who_removed_it_and_when(self):
        admin = User.objects.create_superuser(username="a@x.com", email="a@x.com", password=GOOD_PASSWORD)
        when = timezone.now()
        for row in (self.tim, self.team, self.service, self.ticket()):
            row.removed_by = admin
            row.removed_at = when
            row.save()
            row.refresh_from_db()
            self.assertEqual((row.removed_by, row.removed_at), (admin, when))

    def test_a_ticket_has_no_photo_unless_one_is_added(self):
        self.assertFalse(self.ticket().photo)

    def test_an_escalation_records_the_tier_it_moved_to(self):
        ticket = self.ticket()
        assign_on_creation(ticket)
        escalate_due(timezone.now() + timedelta(minutes=5))
        self.assertEqual(self.escalations(ticket), [2])

    def test_an_escalation_that_ran_out_records_no_tier(self):
        ticket = self.ticket()
        assign_on_creation(ticket)
        escalate_due(timezone.now() + timedelta(minutes=5))
        escalate_due(timezone.now() + timedelta(minutes=15))
        self.assertEqual(self.escalations(ticket), [2, None])

    def test_an_escalation_to_administration_records_its_tier(self):
        EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="administration", wait_minutes=1)
        ticket = self.ticket()
        assign_on_creation(ticket)
        escalate_due(timezone.now() + timedelta(minutes=5))
        escalate_due(timezone.now() + timedelta(minutes=15))
        self.assertEqual(self.escalations(ticket), [2, 3])

    def test_other_timeline_entries_have_no_tier(self):
        ticket = self.ticket()
        assign_on_creation(ticket)
        entry = IncidentUpdate.objects.get(incident=ticket, update_type="assignment")
        self.assertIsNone(entry.escalated_to_tier)

    def test_a_reporter_deleting_their_ticket_is_recorded(self):
        ticket = self.ticket()
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_deleted)
        self.assertEqual(ticket.removed_by, self.reporter)
        self.assertIsNotNone(ticket.removed_at)

    def test_the_new_notification_kinds_have_a_heading(self):
        for event, heading in (("override", "Override on a ticket"), ("handover", "Handed over to you")):
            note = Notification.objects.create(user=self.tim, event=event, message="m")
            self.assertEqual(note.get_event_display(), heading)


class FillOldRowsTests(TestCase):
    """The migration step that gives rows written before Sprint 5 their values."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD)
        self.ticket = Incident.objects.create(title="Leak", description="d", service=self.service,
                                              reported_by=self.reporter, assigned_team=self.team)

    def old_entry(self, body):
        log_event(self.ticket, self.reporter, "escalation", body)
        return IncidentUpdate.objects.order_by("-id").first()

    def test_the_tier_is_read_from_the_text_of_an_old_escalation(self):
        second = self.old_entry("Tim Diaz did not start work within 5 minutes. Escalated to tier 2: Pat Lee")
        third = self.old_entry("Pat Lee did not start work within 10 minutes. Tier 3 had nobody available. "
                               "Escalated to tier 4: Ada Min")
        ran_out = self.old_entry("Pat Lee did not start work within 10 minutes. Escalation ran out: "
                                 "this ticket is unassigned and needs attention")
        fill(apps, None)
        for entry, tier in ((second, 2), (third, 4), (ran_out, None)):
            entry.refresh_from_db()
            self.assertEqual(entry.escalated_to_tier, tier)

    def test_an_old_escalation_to_administration_takes_that_tiers_number(self):
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="administration", wait_minutes=1)
        entry = self.old_entry("Tim Diaz did not start work within 5 minutes. Escalated to administration: "
                               "this ticket is unassigned and needs attention")
        fill(apps, None)
        entry.refresh_from_db()
        self.assertEqual(entry.escalated_to_tier, 2)

    def test_a_ticket_deleted_earlier_is_recorded_as_deleted_by_its_reporter(self):
        Incident.objects.filter(pk=self.ticket.pk).update(is_deleted=True)
        self.ticket.refresh_from_db()
        changed = self.ticket.updated_at
        fill(apps, None)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.removed_by, self.reporter)
        self.assertEqual(self.ticket.removed_at, changed)
        self.assertEqual(self.ticket.updated_at, changed)

    def test_a_ticket_that_was_never_deleted_is_left_alone(self):
        fill(apps, None)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.removed_at)
        self.assertIsNone(self.ticket.removed_by)
