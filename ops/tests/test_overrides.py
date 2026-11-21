"""Overriding a ticket: who may, what it can force, what it writes, and that the normal rules still hold."""
from datetime import timedelta

from django.core import mail
from django.utils import timezone

from ops.access import can_override
from ops.lifecycle import ALLOWED_TRANSITIONS, STATUS_LABELS
from ops.models import EscalationTier, Incident, IncidentUpdate, Notification, Service, Shift, Team, TeamMember
from ops.overrides import HELD, override, override_warnings, possible_solvers
from ops.removal import move_services, remove_team, remove_ticket, remove_user
from ops.scheduling import active_ticket_count, assign_now, assign_on_creation, escalate_due, reassign, team_for
from ops.tests.helpers import GOOD_PASSWORD, Campus
from ops.timeline import MAX_REASON

STATUSES = list(STATUS_LABELS)


class OverrideCase(Campus):
    """The Plumbing team of Ann, Bob and Cy, led by Lena who is not on it, with tickets in any state."""

    def on_call(self, solver=None, role="primary"):
        now = timezone.now()
        return Shift.objects.create(team=self.team, solver=solver or self.bob, created_by=self.lead, on_call_role=role,
                                    starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def ticket_in(self, status, holder="ann", title=None):
        """A ticket in this status. Everything but Open is held by Ann unless told otherwise."""
        holder = None if status == "open" else getattr(self, holder) if isinstance(holder, str) else holder
        ticket = self.ticket(title or f"Leak, {status}", status=status, assigned_to=holder)
        if status == "assigned":
            ticket.escalation_timer_started_at = timezone.now() - timedelta(minutes=2)
            ticket.save()
        return ticket

    def override_entries(self, ticket):
        return list(IncidentUpdate.objects.filter(incident=ticket, update_type="override").order_by("id"))

    def told(self, user):
        return list(Notification.objects.filter(user=user, event="override").order_by("id")
                    .values_list("message", flat=True))


class WhoMayOverrideTests(OverrideCase):
    def test_an_administrator_may_override_any_ticket(self):
        for status in STATUSES:
            self.assertTrue(can_override(self.admin, self.ticket_in(status)))
        no_team = Incident.objects.create(title="Wallet", description="d", reported_by=self.reporter,
                                          service=Service.objects.create(name="Lost and Found"))
        self.assertTrue(can_override(self.admin, no_team))

    def test_a_lead_may_override_the_tickets_of_the_team_they_lead_and_no_others(self):
        mine = self.ticket_in("assigned")
        other_team = Team.objects.create(name="Electrical", lead=self.ann)
        theirs = Incident.objects.create(title="Lights", description="d", reported_by=self.reporter,
                                         service=Service.objects.create(name="Lights", owning_team=other_team),
                                         assigned_team=other_team)
        # Lena leads Plumbing without being on it; Ann leads Electrical
        self.assertTrue(can_override(self.lead, mine))
        self.assertFalse(can_override(self.lead, theirs))
        self.assertTrue(can_override(self.ann, theirs))
        self.assertFalse(can_override(self.ann, mine))
        outcome = override(theirs, self.lead, "not mine", new_status="closed")
        self.assertEqual(outcome.messages, ["Only an administrator, or the lead of the ticket's team, can override a ticket"])

    def test_nobody_else_may(self):
        ticket = self.ticket_in("assigned")
        # The solver who holds it, a solver on the team, the reporter who filed it
        for person in (self.ann, self.bob, self.reporter):
            self.assertFalse(can_override(person, ticket))
            outcome = override(ticket, person, "I want to", new_status="closed")
            self.assertFalse(outcome.ok)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "assigned")
        self.assertEqual(self.override_entries(ticket), [])

    def test_a_removed_administrator_or_lead_may_not(self):
        ticket = self.ticket_in("assigned")
        self.admin.is_active = False
        self.admin.save()
        self.lead.is_active = False
        self.lead.save()
        self.assertFalse(can_override(self.admin, ticket))
        self.assertFalse(can_override(self.lead, ticket))

    def test_a_ticket_with_no_team_has_no_lead_to_override_it(self):
        no_team = Incident.objects.create(title="Wallet", description="d", reported_by=self.reporter,
                                          service=Service.objects.create(name="Lost and Found"))
        self.assertFalse(can_override(self.lead, no_team))

    def test_the_lead_of_the_team_that_took_over_a_removed_teams_tickets_may(self):
        other = Team.objects.create(name="Electrical", lead=self.bob)
        old = self.ticket_in("closed")
        move_services(self.team, other, self.admin)
        remove_team(self.team, self.admin)
        old.refresh_from_db()
        # The closed ticket stayed with Plumbing, which is gone: it answers to the team that owns its service now
        self.assertEqual(old.assigned_team, self.team)
        self.assertEqual(team_for(old), other)
        self.assertTrue(can_override(self.bob, old))
        self.assertFalse(can_override(self.lead, old))


class ReasonTests(OverrideCase):
    def test_an_empty_reason_is_refused_and_nothing_changes(self):
        ticket = self.ticket_in("assigned")
        for reason in ("", "    ", "\n\t ", None):
            outcome = override(ticket, self.admin, reason, new_status="closed")
            self.assertEqual(outcome.messages, ["An override needs a reason"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "assigned")
        self.assertEqual(self.override_entries(ticket), [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_a_reason_has_a_limit(self):
        ticket = self.ticket_in("assigned")
        outcome = override(ticket, self.admin, "x" * (MAX_REASON + 1), new_status="closed")
        self.assertEqual(outcome.messages, [f"The reason can be at most {MAX_REASON} characters"])
        self.assertTrue(override(ticket, self.admin, "x" * MAX_REASON, new_status="closed").ok)

    def test_the_reason_is_written_on_one_line(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.admin, "  duplicate\n of   ticket 41  ", new_status="closed")
        self.assertEqual(self.override_entries(ticket)[0].body,
                         "Status changed from Assigned to Closed. Reason: duplicate of ticket 41")


class ForcedStatusTests(OverrideCase):
    def test_every_status_can_be_forced_from_every_other(self):
        """All twenty moves, with nobody on call so a ticket sent to Open stays there."""
        for old in STATUSES:
            for new in STATUSES:
                if old == new:
                    continue
                with self.subTest(old=old, new=new):
                    ticket = self.ticket_in(old)
                    # Only a ticket nobody holds needs a solver named to become Assigned or In Progress
                    solver = self.cy if new in HELD and old == "open" else None
                    outcome = override(ticket, self.admin, "needed", new_status=new, new_solver=solver)
                    self.assertTrue(outcome.ok, outcome.messages)
                    ticket.refresh_from_db()
                    self.assertEqual(ticket.status, new)
                    self.assertFalse(ticket.is_unassigned_after_escalation)
                    if new == "open":
                        self.assertIsNone(ticket.assigned_to)
                    elif new in HELD:
                        self.assertEqual(ticket.assigned_to, self.cy if old == "open" else self.ann)
                        self.assertEqual(ticket.assigned_team, self.team)
                    else:
                        self.assertEqual(ticket.assigned_to, None if old == "open" else self.ann)
                    entry, = self.override_entries(ticket)
                    self.assertEqual((entry.old_status, entry.new_status, entry.author), (old, new, self.admin))
                    self.assertIn(f"Status changed from {STATUS_LABELS[old]} to {STATUS_LABELS[new]}", entry.body)
                    self.assertTrue(entry.body.endswith(". Reason: needed"))
                    # An override is never recorded as a normal status change, so analytics never count it as one
                    self.assertFalse(IncidentUpdate.objects.filter(incident=ticket, update_type="status_change").exists())

    def test_a_ticket_is_closed_from_any_state(self):
        tickets = [self.ticket_in(status) for status in ("open", "assigned", "in_progress", "resolved")]
        ran_out = self.ticket_in("open", title="Ran out")
        ran_out.is_unassigned_after_escalation = True
        ran_out.save()
        for ticket in tickets + [ran_out]:
            outcome = override(ticket, self.admin, "no longer needed", new_status="closed")
            self.assertEqual(outcome.messages[0][:len(f"Ticket #{ticket.pk} was overridden.")],
                             f"Ticket #{ticket.pk} was overridden.")
            ticket.refresh_from_db()
            self.assertEqual(ticket.status, "closed")
            self.assertFalse(ticket.is_unassigned_after_escalation)

    def test_a_ticket_sent_to_open_goes_to_whoever_on_call_has_room(self):
        self.on_call(self.bob)
        ticket = self.ticket_in("in_progress")
        outcome = override(ticket, self.admin, "wrong fix", new_status="open")
        self.assertTrue(outcome.ok)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.bob))
        kinds = list(IncidentUpdate.objects.filter(incident=ticket).order_by("id").values_list("update_type", flat=True))
        self.assertEqual(kinds, ["override", "assignment"])
        self.assertEqual(self.override_entries(ticket)[0].body,
                         "Status changed from In Progress to Open and taken from Ann Ames. Reason: wrong fix")

    def test_a_ticket_sent_to_open_waits_when_everyone_on_call_is_full(self):
        self.on_call(self.bob)
        for n in range(3):
            self.ticket(f"Held {n}", status="in_progress", assigned_to=self.bob)
        ticket = self.ticket_in("resolved")
        override(ticket, self.admin, "came back", new_status="open")
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("open", None))
        self.assertEqual(self.entries(ticket, "assignment_failed"),
                         ["Everyone on call for Plumbing is full, so this ticket is waiting in the queue"])

    def test_assigned_and_in_progress_need_a_solver(self):
        for status in HELD:
            ticket = self.ticket_in("open")
            outcome = override(ticket, self.admin, "urgent", new_status=status)
            self.assertEqual(outcome.messages, [f"A ticket that is {STATUS_LABELS[status]} needs a solver. Choose who takes it."])
            self.assertTrue(override(ticket, self.admin, "urgent", new_status=status, new_solver=self.cy).ok)
            ticket.refresh_from_db()
            self.assertEqual((ticket.status, ticket.assigned_to), (status, self.cy))

    def test_an_assigned_ticket_starts_tier_one_again(self):
        ticket = self.ticket_in("in_progress")
        ticket.escalation_level = 1
        ticket.save()
        before = timezone.now()
        override(ticket, self.admin, "not started after all", new_status="assigned")
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to, ticket.escalation_level), ("assigned", self.ann, 0))
        self.assertGreaterEqual(ticket.escalation_timer_started_at, before)
        # The timer treats it like any other Assigned ticket: nothing happens before the wait is up
        self.assertEqual(escalate_due(timezone.now() + timedelta(minutes=4)), 0)
        self.assertEqual(escalate_due(timezone.now() + timedelta(minutes=6)), 1)

    def test_choices_that_cannot_be_combined_are_refused(self):
        ticket = self.ticket_in("assigned")
        cases = [
            ({"new_status": "open", "new_solver": self.cy},
             "An Open ticket has no solver. Choose Assigned to give it to someone."),
            ({"new_status": "closed", "new_solver": self.cy},
             "Moving a ticket to Closed does not give it to anyone. Leave the solver out."),
            ({"new_status": "resolved", "new_solver": self.cy},
             "Moving a ticket to Resolved does not give it to anyone. Leave the solver out."),
            ({"new_status": "finished"}, "Choose one of the five statuses"),
            ({}, "Nothing would change. Choose a different status or a different solver."),
            ({"new_status": "assigned"}, "Nothing would change. Choose a different status or a different solver."),
            ({"new_solver": self.ann}, "Nothing would change. Choose a different status or a different solver."),
            ({"new_status": "assigned", "new_solver": self.ann},
             "Nothing would change. Choose a different status or a different solver."),
        ]
        for choices, message in cases:
            with self.subTest(choices=choices):
                self.assertEqual(override(ticket, self.admin, "why not", **choices).messages, [message])
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.ann))
        self.assertEqual(self.override_entries(ticket), [])

    def test_the_same_override_twice_only_happens_once(self):
        ticket = self.ticket_in("assigned")
        self.assertTrue(override(ticket, self.admin, "duplicate", new_status="closed").ok)
        again = override(ticket, self.admin, "duplicate", new_status="closed")
        self.assertEqual(again.messages, ["Nothing would change. Choose a different status or a different solver."])
        self.assertEqual(len(self.override_entries(ticket)), 1)

    def test_a_stale_copy_of_the_ticket_is_read_again_first(self):
        ticket = self.ticket_in("assigned")
        stale = Incident.objects.get(pk=ticket.pk)
        override(ticket, self.admin, "duplicate", new_status="closed")
        # The page still showed Assigned, but the ticket is already Closed
        outcome = override(stale, self.admin, "start it", new_status="in_progress")
        self.assertTrue(outcome.ok, outcome.messages)
        self.assertEqual(self.override_entries(stale)[-1].body,
                         "Status changed from Closed to In Progress. Reason: start it")

    def test_a_removed_ticket_cannot_be_overridden(self):
        ticket = self.ticket_in("assigned")
        remove_ticket(ticket, self.admin, "it is spam")
        outcome = override(ticket, self.admin, "close it", new_status="closed")
        self.assertEqual(outcome.messages, [f"Ticket #{ticket.pk} was removed. Restore it first."])

    def test_a_ticket_with_no_team_can_be_closed_but_not_given_to_anyone(self):
        ticket = Incident.objects.create(title="Wallet", description="d", reported_by=self.reporter,
                                         service=Service.objects.create(name="Lost and Found"))
        for choices in ({"new_solver": self.cy}, {"new_status": "assigned", "new_solver": self.cy}):
            self.assertEqual(override(ticket, self.admin, "why not", **choices).messages,
                             ["No team handles this ticket's service, so nobody can be given it"])
        self.assertTrue(override(ticket, self.admin, "found", new_status="resolved").ok)
        self.assertTrue(override(ticket, self.admin, "lost again", new_status="open").ok)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("open", None))
        self.assertEqual(self.entries(ticket, "assignment_failed"),
                         ["Nobody is on call for Lost and Found right now, so this ticket is waiting to be assigned"])


class ForcedSolverTests(OverrideCase):
    def test_only_the_solver_changes_when_no_status_is_given(self):
        expected = {"open": "assigned", "assigned": "assigned", "in_progress": "in_progress",
                    "resolved": "resolved", "closed": "closed"}
        for old, new in expected.items():
            with self.subTest(old=old):
                ticket = self.ticket_in(old)
                outcome = override(ticket, self.admin, "Ann is out", new_solver=self.cy)
                self.assertTrue(outcome.ok, outcome.messages)
                ticket.refresh_from_db()
                self.assertEqual((ticket.status, ticket.assigned_to), (new, self.cy))
                entry, = self.override_entries(ticket)
                self.assertEqual(entry.new_assignee, self.cy)
                self.assertEqual(entry.old_assignee, None if old == "open" else self.ann)
                if old == "open":
                    self.assertEqual(entry.body, "Status changed from Open to Assigned and assigned to Cy Cole. "
                                                 "Reason: Ann is out")
                    self.assertEqual((entry.old_status, entry.new_status), ("open", "assigned"))
                else:
                    self.assertEqual(entry.body, "Reassigned from Ann Ames to Cy Cole. Reason: Ann is out")
                    self.assertEqual((entry.old_status, entry.new_status), ("", ""))

    def test_a_status_and_a_solver_together(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.admin, "Cy is already there", new_status="in_progress", new_solver=self.cy)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("in_progress", self.cy))
        self.assertEqual(self.override_entries(ticket)[0].body,
                         "Status changed from Assigned to In Progress and reassigned from Ann Ames to Cy Cole. "
                         "Reason: Cy is already there")

    def test_a_solver_who_is_off_call_or_already_holds_three_can_be_given_the_ticket(self):
        self.on_call(self.bob)
        for n in range(3):
            self.ticket(f"Held {n}", status="in_progress", assigned_to=self.cy)
        ticket = self.ticket_in("assigned")
        self.assertEqual(override_warnings(ticket, new_solver=self.cy), [
            "Ann Ames holds this ticket and will lose it.",
            "Cy Cole is not on call for Plumbing right now.",
            "Cy Cole already holds 3 tickets. This will be number 4.",
        ])
        self.assertTrue(override(ticket, self.admin, "only Cy knows this pipe", new_solver=self.cy).ok)
        self.assertEqual(active_ticket_count(self.cy), 4)

    def test_the_lead_can_be_given_a_ticket_without_being_on_the_team(self):
        ticket = self.ticket_in("assigned")
        self.assertEqual([p.first_name for p in possible_solvers(ticket)], ["Ann", "Bob", "Cy", "Lena"])
        self.assertTrue(override(ticket, self.admin, "Lena takes it", new_solver=self.lead).ok)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.lead)

    def test_only_an_active_solver_of_the_team_can_be_given_a_ticket(self):
        ticket = self.ticket_in("assigned")
        outsider = self.person("out@x.com", "Olga", "Outside", "solver")
        self.cy.is_active = False
        self.cy.save()
        for person, name in ((outsider, "Olga Outside"), (self.reporter, "Rae Port"), (self.cy, "Cy Cole")):
            outcome = override(ticket, self.admin, "why not", new_solver=person)
            self.assertEqual(outcome.messages, [f"{name} is not an active solver on Plumbing"])
        self.assertEqual([p.first_name for p in possible_solvers(ticket)], ["Ann", "Bob", "Lena"])

    def test_a_ticket_cannot_go_back_to_a_holder_who_was_removed(self):
        ticket = self.ticket_in("closed")
        remove_user(self.ann, self.admin)
        outcome = override(ticket, self.admin, "came back", new_status="in_progress")
        self.assertEqual(outcome.messages, ["Ann Ames can no longer hold a ticket for Plumbing. Choose who takes it."])
        self.assertTrue(override(ticket, self.admin, "came back", new_status="in_progress", new_solver=self.bob).ok)

    def test_a_ticket_nobody_took_in_time_is_handed_over_and_no_longer_flagged(self):
        self.on_call(self.bob)
        ticket = self.ticket()
        assign_on_creation(ticket)
        escalate_due(timezone.now() + timedelta(minutes=5))
        escalate_due(timezone.now() + timedelta(minutes=15))
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_unassigned_after_escalation)
        self.assertTrue(override(ticket, self.lead, "Cy is free", new_solver=self.cy).ok)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to, ticket.escalation_level), ("assigned", self.cy, 0))
        self.assertFalse(ticket.is_unassigned_after_escalation)

    def test_the_slot_a_solver_loses_goes_to_a_ticket_that_was_waiting(self):
        self.on_call(self.bob)
        held = [self.ticket(f"Held {n}") for n in range(3)]
        for ticket in held:
            assign_on_creation(ticket)
        waiting = self.ticket("Waiting")
        assign_on_creation(waiting)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, "open")
        for choices in ({"new_status": "closed"}, {"new_solver": self.cy}):
            with self.subTest(choices=choices):
                another = self.ticket("Also waiting")
                assign_on_creation(another)
                override(held.pop(), self.admin, "make room", **choices)
                self.assertEqual(active_ticket_count(self.bob), 3)
        waiting.refresh_from_db()
        self.assertEqual((waiting.status, waiting.assigned_to), ("assigned", self.bob))


class NotificationTests(OverrideCase):
    def test_the_new_holder_the_old_holder_the_reporter_and_the_lead_are_each_told_once(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.admin, "Ann is out", new_status="in_progress", new_solver=self.cy)
        label = f"Ticket #{ticket.pk} for Pipes, medium severity,"
        self.assertEqual(self.told(self.cy), [f"{label} was given to you by an override. It is In Progress, "
                                              f"so carry on with the work. Reason: Ann is out"])
        self.assertEqual(self.told(self.ann), [f"{label} was taken from you by an override. You no longer hold it. "
                                               f"Reason: Ann is out"])
        self.assertEqual(self.told(self.reporter), [f"Your ticket #{ticket.pk}, {ticket.title}, was moved from Assigned "
                                                    f"to In Progress by an administrator. Reason: Ann is out"])
        self.assertEqual(self.told(self.lead), [f"{label} was overridden by an administrator: status changed from "
                                                f"Assigned to In Progress and reassigned from Ann Ames to Cy Cole. "
                                                f"Reason: Ann is out"])
        self.assertEqual(self.told(self.admin), [])
        self.assertEqual(Notification.objects.count(), 4)
        self.assertEqual(len(mail.outbox), 4)

    def test_a_solver_given_an_assigned_ticket_is_told_to_take_it(self):
        ticket = self.ticket_in("open")
        override(ticket, self.lead, "nobody on call", new_solver=self.cy)
        self.assertEqual(self.told(self.cy), [
            f"Ticket #{ticket.pk} for Pipes, medium severity, was given to you by an override. Open it and move it to "
            f"In Progress to take responsibility, or it escalates. Reason: nobody on call"])

    def test_the_holder_is_told_when_only_the_status_changes(self):
        ticket = self.ticket_in("in_progress")
        override(ticket, self.admin, "duplicate", new_status="closed")
        self.assertEqual(self.told(self.ann), [f"Ticket #{ticket.pk} for Pipes, medium severity, was moved from "
                                               f"In Progress to Closed by an override. Reason: duplicate"])
        back = self.ticket_in("in_progress", title="Back to assigned")
        override(back, self.admin, "not started", new_status="assigned")
        self.assertIn("was moved from In Progress to Assigned by an override. Open it and move it to In Progress "
                      "to take responsibility, or it escalates. Reason: not started", self.told(self.ann)[-1])

    def test_a_lead_who_overrides_is_named_as_the_team_lead_and_is_not_told(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.lead, "duplicate", new_status="closed")
        self.assertEqual(self.told(self.reporter), [f"Your ticket #{ticket.pk}, {ticket.title}, was moved from Assigned "
                                                    f"to Closed by the team lead. Reason: duplicate"])
        self.assertEqual(self.told(self.lead), [])
        self.assertEqual(Notification.objects.filter(event="override").count(), 2)

    def test_the_reporter_is_not_told_about_a_change_of_solver_alone(self):
        ticket = self.ticket_in("in_progress")
        override(ticket, self.admin, "Ann is out", new_solver=self.cy)
        self.assertEqual(self.told(self.reporter), [])

    def test_nobody_is_told_twice_and_nobody_removed_is_told(self):
        # Lena leads the team and is also given the ticket: one message, about getting it
        ticket = self.ticket_in("assigned")
        self.ann.is_active = False
        self.ann.save()
        override(ticket, self.admin, "Ann left", new_solver=self.lead)
        self.assertEqual(len(self.told(self.lead)), 1)
        self.assertIn("was given to you by an override", self.told(self.lead)[0])
        self.assertEqual(self.told(self.ann), [])

    def test_a_solver_finds_out_a_finished_ticket_is_under_their_name(self):
        ticket = self.ticket_in("resolved")
        override(ticket, self.admin, "Cy did the work", new_solver=self.cy)
        self.assertEqual(self.told(self.cy), [f"Ticket #{ticket.pk} for Pipes, medium severity, is now under your name "
                                              f"by an override. It is Resolved, so there is nothing to do. "
                                              f"Reason: Cy did the work"])


class WarningTests(OverrideCase):
    def test_a_move_the_normal_buttons_allow_has_no_warning_about_skipping(self):
        for old, allowed in ALLOWED_TRANSITIONS.items():
            for new in allowed:
                if new in ("open", "in_progress", "resolved"):
                    continue
                sentences = override_warnings(self.ticket_in(old), new_status=new)
                self.assertEqual(sentences, [], (old, new))

    def test_giving_an_open_ticket_to_a_solver_on_call_with_room_skips_nothing(self):
        self.on_call(self.ann)
        ticket = self.ticket_in("open")
        self.assertEqual(override_warnings(ticket, new_status="assigned", new_solver=self.ann), [])

    def test_skipping_the_usual_steps(self):
        ticket = self.ticket_in("in_progress")
        self.assertEqual(override_warnings(ticket, new_status="closed"),
                         ["A ticket does not normally go from In Progress to Closed. This skips the usual steps."])

    def test_sending_a_ticket_back_to_the_queue(self):
        ticket = self.ticket_in("in_progress")
        self.assertEqual(override_warnings(ticket, new_status="open"), [
            "A ticket does not normally go from In Progress to Open. This skips the usual steps.",
            "Ann Ames holds this ticket and will lose it.",
            "Nobody is on call for Plumbing right now, so the ticket will wait.",
        ])
        self.on_call(self.bob)
        self.assertEqual(override_warnings(ticket, new_status="open")[-1],
                         "The ticket goes back to the queue, and whoever on call has room gets it.")

    def test_work_that_had_started_counts_as_not_started_again(self):
        self.on_call(self.ann)
        ticket = self.ticket_in("in_progress")
        self.assertEqual(override_warnings(ticket, new_status="assigned"), [
            "A ticket does not normally go from In Progress to Assigned. This skips the usual steps.",
            "Ann Ames had started work. The ticket will count as not started again and can escalate.",
        ])

    def test_reopening_straight_to_a_solver_counts_against_them_again(self):
        for n in range(3):
            self.ticket(f"Held {n}", status="assigned", assigned_to=self.ann)
        ticket = self.ticket_in("resolved")
        self.assertEqual(override_warnings(ticket, new_status="in_progress"), [
            "A ticket does not normally go from Resolved to In Progress. This skips the usual steps.",
            "Ann Ames is not on call for Plumbing right now.",
            "Ann Ames already holds 3 tickets. This will be number 4.",
            "An override is not counted as a solver's work in the analytics.",
        ])

    def test_a_finished_ticket_only_changes_its_solvers_name(self):
        ticket = self.ticket_in("closed")
        # Nobody holds a finished ticket, so nobody is said to lose it
        self.assertEqual(override_warnings(ticket, new_solver=self.cy),
                         ["This ticket is Closed. Only the name of its solver changes."])
        override(ticket, self.admin, "Cy did the work", new_solver=self.cy)
        self.assertEqual(self.told(self.ann), [f"Ticket #{ticket.pk} for Pipes, medium severity, is no longer under "
                                               f"your name by an override. Reason: Cy did the work"])

    def test_reopening_a_finished_ticket_says_nothing_about_losing_it(self):
        self.on_call(self.bob)
        for status in ("resolved", "closed"):
            self.assertEqual(override_warnings(self.ticket_in(status), new_status="open"),
                             ["The ticket goes back to the queue, and whoever on call has room gets it."])

    def test_the_queue_sentence_says_when_everyone_on_call_is_full(self):
        self.on_call(self.bob)
        for n in range(3):
            self.ticket(f"Held {n}", status="assigned", assigned_to=self.bob)
        ticket = self.ticket_in("in_progress")
        self.assertEqual(override_warnings(ticket, new_status="open")[-1],
                         "Everyone on call for Plumbing holds 3 tickets, so the ticket will wait in the queue.")

    def test_the_queue_sentence_says_when_the_ticket_can_come_straight_back(self):
        self.on_call(self.ann)
        for n in range(2):
            self.ticket(f"Held {n}", status="assigned", assigned_to=self.ann)
        ticket = self.ticket_in("assigned")
        self.assertEqual(override_warnings(ticket, new_status="open")[-1],
                         "The ticket goes back to the queue. Ann Ames is on call with room, so it can come straight "
                         "back to them. Choose a solver to give it to someone else.")
        override(ticket, self.admin, "back to the queue", new_status="open")
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.ann))

    def test_resolving_by_override_does_not_count_as_the_solvers_work(self):
        ticket = self.ticket_in("in_progress")
        self.assertEqual(override_warnings(ticket, new_status="resolved"),
                         ["An override is not counted as a solver's work in the analytics."])

    def test_no_warnings_for_choices_that_will_be_refused(self):
        ticket = self.ticket_in("assigned")
        for choices in ({}, {"new_status": "assigned"}, {"new_status": "open", "new_solver": self.cy},
                        {"new_status": "nonsense"}, {"new_solver": self.reporter}):
            self.assertEqual(override_warnings(ticket, **choices), [])

    def test_asking_for_the_warnings_changes_nothing(self):
        ticket = self.ticket_in("assigned")
        override_warnings(ticket, new_status="closed", new_solver=None)
        override_warnings(ticket, new_solver=self.cy)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.ann))
        self.assertEqual(IncidentUpdate.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)


class NormalRulesStillHoldTests(OverrideCase):
    """Everything an override can do is still refused on the normal paths."""

    def test_a_solver_still_cannot_skip_a_state(self):
        ticket = self.ticket_in("assigned")
        self.client.login(username="ann@x.com", password=GOOD_PASSWORD)
        page = self.client.post(f"/incidents/{ticket.pk}/transition/", {"new_status": "closed"}, follow=True)
        self.assertContains(page, "Cannot move from Assigned to Closed")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "assigned")

    def test_a_lead_still_cannot_skip_a_state_or_pick_someone_off_call_the_normal_way(self):
        self.on_call(self.bob)
        ticket = self.ticket_in("assigned")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        page = self.client.post(f"/incidents/{ticket.pk}/transition/", {"new_status": "resolved"}, follow=True)
        self.assertContains(page, "Cannot move from Assigned to Resolved")
        self.assertEqual(reassign(ticket, self.cy, self.lead), "Cy Cole is not on call for Plumbing right now")
        page = self.client.post(f"/incidents/{ticket.pk}/reassign/", {"solver": self.cy.pk}, follow=True)
        self.assertContains(page, "That person is not on call for Plumbing right now")
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.ann))

    def test_the_normal_reassign_still_refuses_a_full_solver_and_says_how_many_they_hold(self):
        self.on_call(self.bob)
        for n in range(3):
            self.ticket(f"Held {n}", status="in_progress", assigned_to=self.bob)
        extra = self.ticket_in("assigned", title="Fourth")
        override(extra, self.admin, "Bob knows it", new_solver=self.bob)
        ticket = self.ticket_in("assigned")
        self.assertEqual(reassign(ticket, self.bob, self.lead), "Bob Bell already holds 4 tickets")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.assertContains(self.client.get(f"/incidents/{ticket.pk}/"), "Bob Bell, primary on call, already holds 4 tickets")

    def test_the_queue_gives_nothing_more_to_a_solver_an_override_put_over_three(self):
        self.on_call(self.bob)
        for n in range(3):
            self.ticket(f"Held {n}", status="in_progress", assigned_to=self.bob)
        override(self.ticket_in("assigned", title="Fourth"), self.admin, "Bob knows it", new_solver=self.bob)
        new = self.ticket("New")
        self.assertIsNone(assign_on_creation(new))
        new.refresh_from_db()
        self.assertEqual(new.status, "open")

    def test_the_administrator_has_no_normal_buttons(self):
        ticket = self.ticket_in("assigned")
        self.client.login(username="admin@x.com", password=GOOD_PASSWORD)
        page = self.client.post(f"/incidents/{ticket.pk}/transition/", {"new_status": "in_progress"}, follow=True)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "assigned")


class TimelineDisplayTests(OverrideCase):
    def page(self, email, ticket):
        self.client.logout()
        self.client.login(username=email, password=GOOD_PASSWORD)
        return self.client.get(f"/incidents/{ticket.pk}/")

    def test_the_team_sees_the_override_and_who_did_it(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.admin, "duplicate of ticket 41", new_status="closed")
        other = self.ticket_in("assigned", title="By the lead")
        override(other, self.lead, "Cy is free", new_solver=self.cy)
        page = self.page("bob@x.com", ticket)
        self.assertContains(page, 'Override</span> Status changed from Assigned to Closed. Reason: duplicate of ticket 41')
        self.assertContains(page, '<span class="tl-role">administrator</span>')
        self.assertContains(page, 'class="tl-override"')
        page = self.page("bob@x.com", other)
        self.assertContains(page, 'Override</span> Reassigned from Ann Ames to Cy Cole. Reason: Cy is free')
        self.assertContains(page, '<span class="tl-role">team lead</span>')

    def test_a_reporter_sees_a_status_override_with_its_reason(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.admin, "duplicate of ticket 41", new_status="closed")
        page = self.page("r@x.com", ticket)
        self.assertContains(page, 'Override</span> Status changed from Assigned to Closed. Reason: duplicate of ticket 41')

    def test_a_reporter_sees_a_change_of_solver_as_who_has_it_now_and_not_why(self):
        ticket = self.ticket_in("assigned")
        override(ticket, self.admin, "Ann is out sick", new_solver=self.cy)
        page = self.page("r@x.com", ticket)
        self.assertContains(page, "Now with Cy Cole")
        self.assertNotContains(page, "Ann is out sick")
        self.assertNotContains(page, "Override</span>")
        self.assertNotContains(page, "tl-override")
        # The team still sees all of it
        self.assertContains(self.page("bob@x.com", ticket), "Reason: Ann is out sick")


class RoutingTests(OverrideCase):
    """A ticket goes to the team that owns its service, or stays with its own team when that one is gone."""

    def test_a_reopened_ticket_goes_to_the_team_that_took_over_its_service(self):
        other = Team.objects.create(name="Electrical", lead=self.lead)
        dee = self.person("dee@x.com", "Dee", "Dunn", "solver")
        TeamMember.objects.create(user=dee, team=other)
        now = timezone.now()
        Shift.objects.create(team=other, solver=dee, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        old = self.ticket_in("closed")
        move_services(self.team, other, self.admin)
        remove_team(self.team, self.admin)
        self.assertTrue(override(old, self.admin, "it came back", new_status="open").ok)
        old.refresh_from_db()
        self.assertEqual((old.assigned_team, old.assigned_to, old.status), (other, dee, "assigned"))

    def test_a_ticket_stays_with_its_team_when_its_service_has_none_any_more(self):
        self.on_call(self.bob)
        ticket = self.ticket_in("resolved")
        self.service.owning_team = None
        self.service.save()
        self.assertEqual(team_for(ticket), self.team)
        ticket.status = "open"
        ticket.assigned_to = None
        ticket.save()
        self.assertEqual(assign_now(ticket, self.lead), self.bob)

    def test_a_ticket_is_never_routed_to_a_removed_team(self):
        self.rota()
        old = self.ticket_in("resolved")
        # Plumbing is removed without anywhere for the ticket's service to go
        self.service.is_active = False
        self.service.save()
        Incident.objects.filter(pk=old.pk).update(assigned_team=None)
        old.refresh_from_db()
        self.team.is_active = False
        self.team.save()
        self.assertIsNone(team_for(old))
        old.status = "open"
        old.assigned_to = None
        old.save()
        self.assertIsNone(assign_now(old, self.admin))
        old.refresh_from_db()
        self.assertEqual((old.status, old.assigned_to, old.assigned_team), ("open", None, None))


class ShortReasonTests(OverrideCase):
    def test_a_reason_of_fewer_than_five_characters_is_refused(self):
        ticket = self.ticket_in("assigned")
        self.assertEqual(override(ticket, self.admin, " 5 ", new_status="closed").messages,
                         ["The reason needs at least 5 characters"])
        self.assertEqual(remove_ticket(ticket, self.admin, "dup").messages, ["The reason needs at least 5 characters"])
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.is_deleted), ("assigned", False))
        self.assertTrue(override(ticket, self.admin, "wrong", new_status="closed").ok)
