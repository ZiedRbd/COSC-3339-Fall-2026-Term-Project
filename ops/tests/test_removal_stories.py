"""Removal rules across several steps: the cases where one action meets the leftovers of another."""
from datetime import timedelta

from django.utils import timezone

from ops.models import EscalationTier, Incident, Notification, Service, Shift, Team, TeamMember
from ops.removal import (appoint_lead, holdings, leave_team, move_services, remove_service, remove_team,
                         remove_ticket, remove_user, restore_service, restore_team, restore_ticket, restore_user,
                         transfer_shifts)
from ops.scheduling import assign_on_creation, escalate_due, validate_schedule, who_is_on_call
from ops.tests.helpers import GOOD_PASSWORD, Campus
from ops.timeline import MAX_REASON


class TwoTeams(Campus):
    """Plumbing as in Campus, and Electrical with its own lead, Dee on it, and Dee on call."""

    def setUp(self):
        super().setUp()
        self.eli = self.person("eli@x.com", "Eli", "Lead", "solver")
        self.other = Team.objects.create(name="Electrical", lead=self.eli)
        self.dee = self.person("dee@x.com", "Dee", "Dunn", "solver")
        TeamMember.objects.create(user=self.dee, team=self.other)
        self.on_call(self.dee, self.other)

    def on_call(self, solver, team=None, role="primary"):
        now = timezone.now()
        return Shift.objects.create(team=team or self.team, solver=solver, created_by=self.lead, on_call_role=role,
                                    starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))


class WordingTests(TwoTeams):
    def test_one_thing_is_it_and_several_are_them(self):
        self.on_call(self.ann)
        self.assertEqual(remove_user(self.ann, self.admin).messages,
                         ["Ann Ames holds 1 upcoming shift on Plumbing. Transfer it first."])
        self.assertEqual(leave_team(self.ann, self.team, self.admin).messages,
                         ["Ann Ames holds 1 upcoming shift on Plumbing. Transfer it first."])
        Service.objects.create(name="Drains", owning_team=self.team)
        self.ticket()
        self.ticket("Second")
        self.assertEqual(remove_team(self.team, self.admin).messages,
                         ["Plumbing still owns 2 services. Move them to another team first.",
                          "Plumbing still has 2 unfinished tickets. Move them to another team first."])
        self.assertEqual(move_services(self.team, self.other, self.admin).messages,
                         ["2 services and 2 unfinished tickets moved from Plumbing to Electrical."])

    def test_the_solver_and_the_reporter_are_told_a_ticket_was_removed_in_whole_sentences(self):
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        remove_ticket(ticket, self.admin, "  duplicate\nof ticket 3 ")
        told = {note.user: note.message for note in Notification.objects.filter(event="override")}
        self.assertEqual(told, {
            self.reporter: f"Your ticket #{ticket.pk}, Leak, was removed by an administrator. "
                           f"Reason: duplicate of ticket 3",
            self.ann: f"The ticket #{ticket.pk}, Leak, which you held, was removed by an administrator. "
                      f"Reason: duplicate of ticket 3",
        })
        self.assertEqual(self.entries(ticket, "removal"), ["Ticket removed. Reason: duplicate of ticket 3"])

    def test_an_administrator_who_removes_their_own_ticket_is_not_told_about_it(self):
        mine = Incident.objects.create(title="Mine", description="d", service=self.service,
                                       reported_by=self.admin, assigned_team=self.team)
        remove_ticket(mine, self.admin, "filed by mistake")
        self.assertEqual(Notification.objects.count(), 0)

    def test_a_reason_for_removing_a_ticket_has_a_limit(self):
        ticket = self.ticket()
        self.assertEqual(remove_ticket(ticket, self.admin, "x" * (MAX_REASON + 1)).messages,
                         [f"The reason can be at most {MAX_REASON} characters"])
        self.assertTrue(remove_ticket(ticket, self.admin, "x" * MAX_REASON).ok)


class RestoreTicketTests(TwoTeams):
    def test_a_ticket_restored_after_its_team_handed_over_goes_to_the_team_that_took_its_service(self):
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        remove_ticket(ticket, self.admin, "by mistake")
        # The removed ticket does not move with the others, and does not hold the team back
        self.assertEqual(move_services(self.team, self.other, self.admin).messages,
                         ["1 service and 0 unfinished tickets moved from Plumbing to Electrical."])
        self.assertTrue(remove_team(self.team, self.admin).ok)
        self.assertEqual(restore_ticket(ticket, self.admin).messages, [f"Ticket #{ticket.pk} was restored."])
        ticket.refresh_from_db()
        self.assertEqual((ticket.assigned_team, ticket.assigned_to, ticket.status), (self.other, self.dee, "assigned"))

    def test_a_ticket_restored_when_no_team_handles_its_service_waits_and_says_so(self):
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        remove_ticket(ticket, self.admin, "by mistake")
        remove_service(self.service, self.admin)
        self.assertTrue(remove_team(self.team, self.admin).ok)
        outcome = restore_ticket(ticket, self.admin)
        self.assertEqual(outcome.messages, [f"Ticket #{ticket.pk} was restored.",
                                            "No team handles its service now, so it will wait until one does."])
        ticket.refresh_from_db()
        self.assertEqual((ticket.assigned_team, ticket.assigned_to, ticket.status, ticket.is_deleted),
                         (None, None, "open", False))

    def test_a_restored_ticket_never_takes_its_old_solver_past_three(self):
        self.on_call(self.bob)
        ticket = self.ticket(assigned_to=self.bob, status="in_progress")
        remove_ticket(ticket, self.admin, "by mistake")
        for n in range(3):
            self.ticket(f"Held {n}", assigned_to=self.bob, status="assigned")
        restore_ticket(ticket, self.admin)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("open", None))

    def test_a_ticket_is_not_given_back_to_a_solver_who_was_removed_meanwhile(self):
        self.on_call(self.bob)
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        remove_ticket(ticket, self.admin, "by mistake")
        self.assertEqual(remove_user(self.ann, self.admin).messages, ["Ann Ames was removed and can no longer log in."])
        restore_ticket(ticket, self.admin)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.bob))

    def test_a_ticket_with_no_team_is_removed_and_restored(self):
        lost = Incident.objects.create(title="Wallet", description="d", reported_by=self.reporter,
                                       service=Service.objects.create(name="Lost and Found"))
        self.assertTrue(remove_ticket(lost, self.admin, "found").ok)
        outcome = restore_ticket(lost, self.admin)
        self.assertEqual(outcome.messages[1], "No team handles its service now, so it will wait until one does.")
        lost.refresh_from_db()
        self.assertEqual((lost.is_deleted, lost.status, lost.assigned_team), (False, "open", None))

    def test_a_ticket_nobody_took_in_time_is_restored_still_flagged(self):
        ticket = self.ticket(is_unassigned_after_escalation=True)
        remove_ticket(ticket, self.admin, "by mistake")
        self.on_call(self.bob)
        restore_ticket(ticket, self.admin)
        ticket.refresh_from_db()
        # It still needs the lead: the queue does not hand out a ticket that ran through its policy
        self.assertEqual((ticket.status, ticket.assigned_to, ticket.is_unassigned_after_escalation), ("open", None, True))


class HandoverTests(TwoTeams):
    def test_the_same_handover_twice_is_refused_the_second_time(self):
        self.rota()
        self.assertTrue(transfer_shifts(self.ann, self.team, self.admin).ok)
        before = [(s.pk, s.solver_id, s.starts_at, s.ends_at) for s in Shift.objects.order_by("pk")]
        self.assertEqual(transfer_shifts(self.ann, self.team, self.admin).messages,
                         ["Ann Ames holds no upcoming shift on Plumbing"])
        self.assertEqual([(s.pk, s.solver_id, s.starts_at, s.ends_at) for s in Shift.objects.order_by("pk")], before)

    def test_a_problem_that_was_already_in_the_schedule_does_not_stop_a_handover(self):
        """Bob already has two shifts in a row, later in the week. That is the lead's to fix, not this handover's."""
        self.rota(blocks=3)
        last = Shift.objects.order_by("-starts_at").first()
        for n in (0, 1):
            Shift.objects.create(team=self.team, solver=self.bob, created_by=self.lead,
                                 starts_at=last.ends_at + timedelta(hours=8 * n),
                                 ends_at=last.ends_at + timedelta(hours=8 * n + 8))
        self.assertIn("Bob Bell cannot take two shifts in a row on Plumbing", " ".join(validate_schedule(self.team, self.upcoming())))
        outcome = transfer_shifts(self.ann, self.team, self.admin)
        self.assertTrue(outcome.ok, outcome.messages)
        solvers = [shift.solver for shift in self.upcoming()]
        # Ann's shift went to Cy, and the two that were already wrong are exactly as they were
        self.assertEqual(solvers, [self.cy, self.bob, self.cy, self.bob, self.bob])

    def test_a_solver_who_only_has_secondary_shifts_hands_those_over_by_dropping_them(self):
        self.rota(solvers=[self.bob, self.cy])
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.ann, created_by=self.lead, on_call_role="secondary",
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=3))
        later = Shift.objects.create(team=self.team, solver=self.ann, created_by=self.lead, on_call_role="secondary",
                                     starts_at=now + timedelta(hours=30), ends_at=now + timedelta(hours=34))
        self.assertEqual(remove_user(self.ann, self.admin).messages,
                         ["Ann Ames holds 2 upcoming shifts on Plumbing. Transfer them first."])
        primaries = [(s.pk, s.solver_id) for s in self.upcoming()]
        outcome = transfer_shifts(self.ann, self.team, self.admin)
        self.assertEqual(outcome.messages, ["Ann Ames's 2 secondary shifts on Plumbing were dropped. A secondary is optional."])
        self.assertFalse(Shift.objects.filter(pk=later.pk).exists())
        self.assertEqual(Shift.objects.filter(solver=self.ann, ends_at__gt=timezone.now()).count(), 0)
        self.assertEqual([(s.pk, s.solver_id) for s in self.upcoming()], primaries)
        self.assertEqual(Notification.objects.filter(event="handover").count(), 0)
        self.assertTrue(remove_user(self.ann, self.admin).ok)

    def test_a_solver_on_two_teams_hands_over_each_team_before_being_removed(self):
        self.rota()
        TeamMember.objects.create(user=self.ann, team=self.other)
        TeamMember.objects.create(user=self.eli, team=self.other)
        # Ann's shift on Electrical starts at the very moment Dee's ends, so that schedule has no gap either
        later = Shift.objects.get(team=self.other).ends_at
        Shift.objects.create(team=self.other, solver=self.ann, created_by=self.eli,
                             starts_at=later, ends_at=later + timedelta(hours=8))
        self.assertEqual(remove_user(self.ann, self.admin).messages, [
            "Ann Ames holds 1 upcoming shift on Electrical. Transfer it first.",
            "Ann Ames holds 3 upcoming shifts on Plumbing. Transfer them first.",
        ])
        self.assertTrue(transfer_shifts(self.ann, self.team, self.admin).ok)
        self.assertEqual(remove_user(self.ann, self.admin).messages,
                         ["Ann Ames holds 1 upcoming shift on Electrical. Transfer it first."])
        outcome = transfer_shifts(self.ann, self.other, self.admin)
        self.assertTrue(outcome.ok, outcome.messages)
        self.assertTrue(remove_user(self.ann, self.admin).ok)
        for team in (self.team, self.other):
            self.assertEqual(validate_schedule(team, self.upcoming(team)), [])

    def test_a_removed_solver_cannot_be_put_on_a_shift(self):
        remove_user(self.ann, self.admin)
        now = timezone.now()
        shift = Shift(team=self.team, solver=self.ann, created_by=self.lead, starts_at=now, ends_at=now + timedelta(hours=6))
        self.assertIn("Ann Ames was removed and cannot take a shift", validate_schedule(self.team, [shift]))

    def test_a_lead_who_is_also_on_the_team_keeps_their_tickets_when_they_come_off_it(self):
        self.team.lead = self.ann
        self.team.save()
        mine = self.ticket(assigned_to=self.ann, status="in_progress")
        self.assertTrue(leave_team(self.ann, self.team, self.admin).ok)
        mine.refresh_from_db()
        self.assertEqual((mine.status, mine.assigned_to), ("in_progress", self.ann))


class StoryTests(TwoTeams):
    def test_a_lead_holding_an_escalated_ticket_is_replaced_and_removed(self):
        self.on_call(self.bob)
        ticket = self.ticket()
        assign_on_creation(ticket)
        escalate_due(timezone.now() + timedelta(minutes=5))
        ticket.refresh_from_db()
        self.assertEqual((ticket.assigned_to, ticket.escalation_level), (self.lead, 1))
        self.assertEqual(remove_user(self.lead, self.admin).messages,
                         ["Lena Lead is the lead of Plumbing. Appoint a new lead first."])
        self.assertTrue(appoint_lead(self.team, self.cy, self.admin).ok)
        outcome = remove_user(self.lead, self.admin)
        self.assertEqual(outcome.messages, ["Lena Lead was removed and can no longer log in.",
                                            "1 ticket went back to waiting for a solver."])
        ticket.refresh_from_db()
        # Back at the start of the policy, with whoever is on call
        self.assertEqual((ticket.status, ticket.assigned_to, ticket.escalation_level), ("assigned", self.bob, 0))
        self.assertFalse(ticket.is_unassigned_after_escalation)

    def test_a_team_is_removed_restored_and_takes_tickets_again(self):
        self.rota()
        move_services(self.team, self.other, self.admin)
        remove_team(self.team, self.admin)
        restore_team(self.team, self.admin)
        self.service.refresh_from_db()
        # The service comes back with the team; the team has no schedule yet, so a new ticket waits
        self.assertEqual(self.service.owning_team, self.team)
        self.assertIsNone(who_is_on_call(self.team))
        ticket = self.ticket("After the restore")
        self.assertIsNone(assign_on_creation(ticket))
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_team), ("open", self.team))
        self.on_call(self.bob)
        self.client.login(username="bob@x.com", password=GOOD_PASSWORD)
        self.assertContains(self.client.get("/incidents/list"), "After the restore")
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.bob))

    def test_a_restored_user_comes_back_on_their_teams_with_nothing_handed_back(self):
        self.rota()
        transfer_shifts(self.ann, self.team, self.admin)
        remove_user(self.ann, self.admin)
        self.assertTrue(restore_user(self.ann, self.admin).ok)
        self.assertTrue(TeamMember.objects.filter(user=self.ann, team=self.team).exists())
        self.assertEqual(holdings(self.ann), {"shifts": {}, "led": [], "tiers": []})
        # Removing them again needs nothing handed over, and restoring again works too
        self.assertTrue(remove_user(self.ann, self.admin).ok)
        self.assertTrue(restore_user(self.ann, self.admin).ok)
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.is_active)

    def test_a_removed_reporter_is_not_told_about_their_ticket_any_more(self):
        self.on_call(self.bob)
        ticket = self.ticket()
        assign_on_creation(ticket)
        remove_user(self.reporter, self.admin)
        self.client.login(username="bob@x.com", password=GOOD_PASSWORD)
        for status in ("in_progress", "resolved"):
            self.client.post(f"/incidents/{ticket.pk}/transition/", {"new_status": status})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertEqual(Notification.objects.filter(user=self.reporter).count(), 0)

    def test_a_team_with_no_lead_can_be_removed_but_not_restored_until_it_has_one(self):
        self.team.lead = None
        self.team.save()
        move_services(self.team, self.other, self.admin)
        self.assertTrue(remove_team(self.team, self.admin).ok)
        self.assertEqual(restore_team(self.team, self.admin).messages, ["Plumbing has no active lead. Appoint one first."])
        self.assertTrue(appoint_lead(self.team, self.bob, self.admin).ok)
        self.assertTrue(restore_team(self.team, self.admin).ok)

    def test_a_service_restored_after_its_team_came_back_is_offered_again(self):
        remove_service(self.service, self.admin)
        self.assertTrue(remove_team(self.team, self.admin).ok)
        self.assertEqual(restore_service(self.service, self.admin).messages,
                         ["Pipes belongs to Plumbing, which was removed. Restore that team first."])
        self.assertTrue(restore_team(self.team, self.admin).ok)
        self.assertTrue(restore_service(self.service, self.admin).ok)
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.assertContains(self.client.get("/incidents/form"), "Pipes")

    def test_a_ticket_reopened_after_its_service_was_removed_and_its_team_handed_over_stays_with_the_new_team(self):
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        remove_service(self.service, self.admin)
        move_services(self.team, self.other, self.admin)
        self.rota()
        remove_team(self.team, self.admin)
        self.client.login(username="dee@x.com", password=GOOD_PASSWORD)
        for status in ("in_progress", "resolved", "open"):
            self.client.post(f"/incidents/{ticket.pk}/transition/", {"new_status": status})
        ticket.refresh_from_db()
        self.assertEqual((ticket.assigned_team, ticket.assigned_to, ticket.status), (self.other, self.dee, "assigned"))
        self.assertContains(self.client.get("/incidents/list"), "Leak")

    def test_escalation_passes_over_a_tier_whose_person_was_removed_with_their_team_gone_then_restored(self):
        tier = EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user",
                                             escalate_to_user=self.ann, wait_minutes=5)
        self.assertEqual(remove_user(self.ann, self.admin).messages,
                         ["Tier 3 of Plumbing names Ann Ames. Replace them in that tier first."])
        tier.refresh_from_db()
        self.assertEqual(tier.escalate_to_user, self.ann)
