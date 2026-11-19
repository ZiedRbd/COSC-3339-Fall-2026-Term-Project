"""Removing and restoring users, teams, services, buildings and tickets, and the handovers that come first."""
from datetime import timedelta

from django.core import mail
from django.utils import timezone

from ops.models import (Building, EscalationTier, Incident, IncidentUpdate, Notification, Service, Shift, Team,
                        TeamMember, User)
from ops.removal import (appoint_lead, holdings, leave_team, move_services, remove_building, remove_service,
                         remove_team, remove_ticket, remove_user, replace_in_tier, restore_building, restore_service,
                         restore_team, restore_ticket, restore_user, transfer_shifts)
from ops.scheduling import assign_on_creation, validate_schedule
from ops.tests.helpers import GOOD_PASSWORD, Campus


class TransferShiftsTests(Campus):
    def test_the_rest_of_the_team_takes_over_and_the_schedule_stays_valid(self):
        self.rota()
        self.assertEqual(validate_schedule(self.team, self.upcoming()), [])
        outcome = transfer_shifts(self.ann, self.team, self.admin)
        self.assertTrue(outcome.ok, outcome.messages)
        self.assertEqual(outcome.messages, ["Ann Ames's 3 upcoming shifts on Plumbing are now covered by Bob Bell and Cy Cole."])
        shifts = self.upcoming()
        self.assertEqual(validate_schedule(self.team, shifts), [])
        self.assertNotIn(self.ann, [shift.solver for shift in shifts])
        for before, after in zip(shifts, shifts[1:]):
            self.assertNotEqual(before.solver, after.solver)
        self.assertEqual(holdings(self.ann)["shifts"], {})

    def test_the_shift_running_now_is_cut_at_this_moment(self):
        self.rota()
        first = Shift.objects.order_by("starts_at").first()
        end = first.ends_at
        transfer_shifts(self.ann, self.team, self.admin)
        first.refresh_from_db()
        self.assertEqual(first.solver, self.ann)
        self.assertLessEqual(first.ends_at, timezone.now())
        rest = self.upcoming()[0]
        self.assertEqual(rest.starts_at, first.ends_at)
        self.assertEqual(rest.ends_at, end)
        self.assertNotEqual(rest.solver, self.ann)

    def test_the_preferred_solver_gets_a_shift_they_are_free_for(self):
        self.rota()
        transfer_shifts(self.ann, self.team, self.admin, prefer=self.cy)
        self.assertEqual(self.upcoming()[0].solver, self.cy)

    def test_a_shift_goes_to_somebody_who_does_not_have_the_next_one(self):
        self.rota(blocks=3)
        transfer_shifts(self.ann, self.team, self.admin)
        # Bob has the second shift, so the first goes to Cy and nobody else has to move
        self.assertEqual([shift.solver for shift in self.upcoming()], [self.cy, self.bob, self.cy])

    def test_it_is_refused_when_nobody_else_can_cover(self):
        TeamMember.objects.filter(user=self.cy).delete()
        self.rota(solvers=[self.ann, self.bob])
        before = [(s.pk, s.solver_id, s.ends_at) for s in Shift.objects.order_by("pk")]
        outcome = transfer_shifts(self.ann, self.team, self.admin)
        self.assertFalse(outcome.ok)
        self.assertIn("Plumbing cannot stay covered without Ann Ames", outcome.messages[0])
        self.assertEqual([(s.pk, s.solver_id, s.ends_at) for s in Shift.objects.order_by("pk")], before)

    def test_a_solver_on_call_for_another_team_is_passed_over(self):
        self.rota(blocks=3)
        other = Team.objects.create(name="Electrical", lead=self.lead)
        TeamMember.objects.create(user=self.cy, team=other)
        now = timezone.now()
        Shift.objects.create(team=other, solver=self.cy, created_by=self.lead,
                             starts_at=now - timedelta(hours=2), ends_at=now + timedelta(hours=3))
        outcome = transfer_shifts(self.ann, self.team, self.admin)
        self.assertTrue(outcome.ok, outcome.messages)
        # Cy would have been first choice, but is busy: Bob takes the first shift and the rest move round him
        self.assertEqual([shift.solver for shift in self.upcoming()], [self.bob, self.cy, self.bob])
        self.assertEqual(validate_schedule(self.team, self.upcoming()), [])

    def test_secondary_shifts_are_dropped(self):
        self.rota()
        now = timezone.now()
        running = Shift.objects.create(team=self.team, solver=self.ann, created_by=self.lead, on_call_role="secondary",
                                       starts_at=now + timedelta(hours=8), ends_at=now + timedelta(hours=12))
        outcome = transfer_shifts(self.ann, self.team, self.admin)
        self.assertTrue(outcome.ok, outcome.messages)
        self.assertFalse(Shift.objects.filter(pk=running.pk).exists())
        self.assertIn("Ann Ames's 1 secondary shift on Plumbing was dropped. A secondary is optional.", outcome.messages)

    def test_whoever_takes_shifts_is_told_once(self):
        self.rota()
        transfer_shifts(self.ann, self.team, self.admin)
        notes = Notification.objects.filter(event="handover")
        self.assertEqual({note.user for note in notes}, {self.bob, self.cy})
        self.assertEqual(notes.count(), 2)
        self.assertIn("on Plumbing", notes.first().message)

    def test_only_an_administrator_and_only_when_there_is_something_to_hand_over(self):
        self.rota()
        self.assertEqual(transfer_shifts(self.ann, self.team, self.lead).messages, ["Only an administrator can do this"])
        self.assertEqual(transfer_shifts(self.lead, self.team, self.admin).messages,
                         ["Lena Lead holds no upcoming shift on Plumbing"])


class RemoveUserTests(Campus):
    def test_it_is_refused_while_they_hold_a_shift_lead_a_team_or_sit_in_a_tier(self):
        self.rota()
        self.team.lead = self.ann
        self.team.save()
        EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user",
                                      escalate_to_user=self.ann, wait_minutes=5)
        outcome = remove_user(self.ann, self.admin)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.messages, [
            "Ann Ames holds 3 upcoming shifts on Plumbing. Transfer them first.",
            "Ann Ames is the lead of Plumbing. Appoint a new lead first.",
            "Tier 3 of Plumbing names Ann Ames. Replace them in that tier first.",
        ])
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.is_active)

    def test_after_the_three_handovers_the_removal_goes_through(self):
        self.rota()
        self.team.lead = self.ann
        self.team.save()
        tier = EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user",
                                             escalate_to_user=self.ann, wait_minutes=5)
        self.assertTrue(transfer_shifts(self.ann, self.team, self.admin).ok)
        self.assertEqual(appoint_lead(self.team, self.bob, self.admin).messages, ["Bob Bell now leads Plumbing."])
        self.assertEqual(replace_in_tier(tier, self.cy, self.admin).messages, ["Tier 3 of Plumbing now names Cy Cole."])
        outcome = remove_user(self.ann, self.admin)
        self.assertEqual(outcome.messages, ["Ann Ames was removed and can no longer log in."])
        self.ann.refresh_from_db()
        self.assertFalse(self.ann.is_active)
        self.assertEqual(self.ann.removed_by, self.admin)
        self.assertIsNotNone(self.ann.removed_at)

    def test_a_removed_user_cannot_log_in_or_register_again(self):
        remove_user(self.reporter, self.admin)
        self.assertFalse(self.client.login(username="r@x.com", password=GOOD_PASSWORD))
        page = self.client.post("/login/", {"email": "r@x.com", "password": GOOD_PASSWORD}, follow=True)
        self.assertContains(page, "Invalid email or password")
        page = self.client.post("/register/", {"first_name": "Rae", "last_name": "Port", "email": "r@x.com",
                                               "password": GOOD_PASSWORD, "password2": GOOD_PASSWORD})
        self.assertContains(page, "This email is already registered")
        self.assertEqual(User.objects.filter(email="r@x.com").count(), 1)

    def test_a_user_who_is_signed_in_is_signed_out_by_their_next_click(self):
        self.client.login(username="ann@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.client.get("/incidents/list").status_code, 200)
        remove_user(self.ann, self.admin)
        self.assertRedirects(self.client.get("/incidents/list"), "/login/?next=/incidents/list")

    def test_their_tickets_go_back_to_waiting_and_are_handed_out_again(self):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.bob, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        working = self.ticket("Working on it", assigned_to=self.ann, status="in_progress")
        done = self.ticket("Done", assigned_to=self.ann, status="resolved")
        outcome = remove_user(self.ann, self.admin)
        self.assertEqual(outcome.messages[1], "1 ticket went back to waiting for a solver.")
        working.refresh_from_db()
        done.refresh_from_db()
        # Bob is on call and has room, so the queue gives it to him straight away
        self.assertEqual((working.status, working.assigned_to), ("assigned", self.bob))
        self.assertEqual(self.entries(working, "removal"),
                         ["Ann Ames was removed, so this ticket is waiting for a solver again."])
        self.assertEqual((done.status, done.assigned_to), ("resolved", self.ann))

    def test_a_reporters_tickets_carry_on(self):
        ticket = self.ticket()
        self.assertTrue(remove_user(self.reporter, self.admin).ok)
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_deleted)
        self.assertEqual(ticket.reported_by, self.reporter)

    def test_what_is_refused(self):
        self.assertEqual(remove_user(self.admin, self.admin).messages, ["You cannot remove your own account"])
        self.assertEqual(remove_user(self.ann, self.lead).messages, ["Only an administrator can do this"])
        remove_user(self.ann, self.admin)
        self.assertEqual(remove_user(self.ann, self.admin).messages, ["Ann Ames is already removed"])

    def test_a_restored_user_can_log_in_again(self):
        remove_user(self.ann, self.admin)
        self.assertTrue(restore_user(self.ann, self.admin).ok)
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.is_active)
        self.assertIsNone(self.ann.removed_at)
        self.assertIsNone(self.ann.removed_by)
        self.assertTrue(self.client.login(username="ann@x.com", password=GOOD_PASSWORD))
        self.assertEqual(restore_user(self.ann, self.admin).messages, ["Ann Ames is not removed"])

    def test_a_removed_solver_leaves_the_dropdowns_and_the_team_list(self):
        remove_user(self.ann, self.admin)
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.assertNotContains(self.client.get(f"/schedule/{self.team.pk}/"), "Ann Ames")
        self.assertNotContains(self.client.get(f"/policy/{self.team.pk}/"), "Ann Ames")
        self.client.logout()
        self.client.login(username="bob@x.com", password=GOOD_PASSWORD)
        self.assertNotContains(self.client.get("/profile/"), "Ann Ames")


class LeadAndTierTests(Campus):
    def test_a_new_lead_is_an_active_solver_and_is_told(self):
        self.assertEqual(appoint_lead(self.team, self.reporter, self.admin).messages,
                         ["The lead of a team has to be an active solver"])
        self.assertEqual(appoint_lead(self.team, self.lead, self.admin).messages, ["Lena Lead already leads Plumbing"])
        self.assertTrue(appoint_lead(self.team, self.bob, self.admin).ok)
        self.team.refresh_from_db()
        self.assertEqual(self.team.lead, self.bob)
        note = Notification.objects.get(user=self.bob, event="handover")
        self.assertIn("You now lead Plumbing", note.message)

    def test_a_tier_names_another_solver_on_the_team(self):
        tier = EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user",
                                             escalate_to_user=self.ann, wait_minutes=5)
        self.assertEqual(replace_in_tier(tier, self.lead, self.admin).messages,
                         ["A tier of Plumbing can only name an active solver on that team"])
        self.assertEqual(replace_in_tier(tier, self.ann, self.admin).messages, ["Tier 3 of Plumbing already names Ann Ames"])
        self.assertTrue(replace_in_tier(tier, self.cy, self.admin).ok)
        tier.refresh_from_db()
        self.assertEqual(tier.escalate_to_user, self.cy)
        self.assertEqual({note.user for note in Notification.objects.filter(event="handover")}, {self.cy, self.lead})

    def test_a_tier_that_names_no_person_has_nobody_to_replace(self):
        tier = EscalationTier.objects.get(team=self.team, tier_number=2)
        self.assertEqual(replace_in_tier(tier, self.cy, self.admin).messages, ["Tier 2 of Plumbing does not name a person"])


class LeaveTeamTests(Campus):
    def test_a_solver_comes_off_a_team_once_their_shifts_there_are_handed_over(self):
        self.rota()
        other = Team.objects.create(name="Electrical", lead=self.lead)
        TeamMember.objects.create(user=self.ann, team=other)
        outcome = leave_team(self.ann, self.team, self.admin)
        self.assertEqual(outcome.messages, ["Ann Ames holds 3 upcoming shifts on Plumbing. Transfer them first."])
        transfer_shifts(self.ann, self.team, self.admin)
        held = self.ticket(assigned_to=self.ann, status="in_progress")
        self.assertEqual(leave_team(self.ann, self.team, self.admin).messages,
                         ["Ann Ames is no longer on Plumbing.", "1 ticket went back to waiting for a solver."])
        # Ann is told the ticket she was working on is no longer hers
        self.assertEqual(list(Notification.objects.filter(user=self.ann, event="override")
                              .values_list("message", flat=True)),
                         [f"Ticket #{held.pk} for Pipes, medium severity, went back to the queue because you are no "
                          f"longer on Plumbing. You no longer hold it."])
        self.assertFalse(TeamMember.objects.filter(user=self.ann, team=self.team).exists())
        self.assertTrue(TeamMember.objects.filter(user=self.ann, team=other).exists())
        held.refresh_from_db()
        self.assertNotEqual(held.assigned_to, self.ann)
        self.assertEqual(self.entries(held, "removal"),
                         ["Ann Ames left Plumbing, so this ticket is waiting for a solver again."])

    def test_leading_a_team_does_not_stop_a_solver_from_leaving_it(self):
        self.team.lead = self.ann
        self.team.save()
        self.assertTrue(leave_team(self.ann, self.team, self.admin).ok)
        self.assertEqual(leave_team(self.ann, self.team, self.admin).messages, ["Ann Ames is not on Plumbing"])


class ServiceAndBuildingTests(Campus):
    def test_a_removed_service_keeps_its_open_tickets_and_takes_no_new_ones(self):
        open_ticket = self.ticket()
        closed = self.ticket("Old", status="closed")
        outcome = remove_service(self.service, self.admin)
        self.assertEqual(outcome.messages, ["Pipes was removed. No new ticket can be filed against it.",
                                         "Its 1 unfinished ticket carries on as normal."])
        self.service.refresh_from_db()
        self.assertFalse(self.service.is_active)
        self.assertEqual(self.service.removed_by, self.admin)
        self.assertEqual(self.entries(open_ticket, "removal"),
                         ["The service Pipes was removed. This ticket carries on as normal."])
        self.assertEqual(self.entries(closed, "removal"), [])
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.assertNotContains(self.client.get("/incidents/form"), "Pipes")
        self.assertNotContains(self.client.get("/services/"), "Pipes")

    def test_a_service_comes_back_unless_its_team_is_gone(self):
        remove_service(self.service, self.admin)
        self.team.is_active = False
        self.team.save()
        self.assertEqual(restore_service(self.service, self.admin).messages,
                         ["Pipes belongs to Plumbing, which was removed. Restore that team first."])
        self.team.is_active = True
        self.team.save()
        self.assertTrue(restore_service(self.service, self.admin).ok)
        self.service.refresh_from_db()
        self.assertTrue(self.service.is_active)
        self.assertIsNone(self.service.removed_at)

    def test_a_building_is_removed_and_restored(self):
        moody = Building.objects.get(name="Moody Hall")
        ticket = self.ticket(building=moody)
        self.assertEqual(remove_building(moody, self.admin).messages, ["Moody Hall was removed from the building list."])
        moody.refresh_from_db()
        self.assertEqual((moody.is_active, moody.removed_by), (False, self.admin))
        ticket.refresh_from_db()
        self.assertEqual(ticket.building_name, "Moody Hall")
        self.assertTrue(restore_building(moody, self.admin).ok)
        moody.refresh_from_db()
        self.assertEqual((moody.is_active, moody.removed_by, moody.removed_at), (True, None, None))


class TeamTests(Campus):
    def setUp(self):
        super().setUp()
        self.other = Team.objects.create(name="Electrical", lead=self.lead)
        self.dee = self.person("dee@x.com", "Dee", "Dunn", "solver")
        TeamMember.objects.create(user=self.dee, team=self.other)

    def test_a_team_cannot_go_while_it_owns_a_service_or_has_an_open_ticket(self):
        self.ticket()
        outcome = remove_team(self.team, self.admin)
        self.assertEqual(outcome.messages, ["Plumbing still owns 1 service. Move it to another team first.",
                                         "Plumbing still has 1 unfinished ticket. Move it to another team first."])
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_active)

    def test_its_services_and_open_tickets_move_to_another_team(self):
        now = timezone.now()
        Shift.objects.create(team=self.other, solver=self.dee, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))
        held = self.ticket(assigned_to=self.ann, status="in_progress")
        finished = self.ticket("Old", assigned_to=self.ann, status="closed")
        outcome = move_services(self.team, self.other, self.admin)
        self.assertEqual(outcome.messages, ["1 service and 1 unfinished ticket moved from Plumbing to Electrical."])
        self.service.refresh_from_db()
        self.assertEqual(self.service.owning_team, self.other)
        held.refresh_from_db()
        finished.refresh_from_db()
        # Dee is on call for Electrical, so its queue hands the ticket to her
        self.assertEqual((held.assigned_team, held.assigned_to, held.status), (self.other, self.dee, "assigned"))
        self.assertEqual(self.entries(held, "removal"), ["This ticket moved from Plumbing to Electrical with its service."])
        self.assertEqual(finished.assigned_team, self.team)
        self.assertEqual(remove_team(self.team, self.admin).messages, ["Plumbing was removed."])
        self.team.refresh_from_db()
        self.assertEqual((self.team.is_active, self.team.removed_by), (False, self.admin))

    def test_the_team_that_takes_over_has_to_be_another_active_team(self):
        for target in (self.team, None):
            self.assertEqual(move_services(self.team, target, self.admin).messages,
                             ["Choose another team that is still active to take the services"])

    def test_a_removed_team_leaves_the_pages(self):
        self.rota()
        move_services(self.team, self.other, self.admin)
        remove_team(self.team, self.admin)
        self.client.login(username="ann@x.com", password=GOOD_PASSWORD)
        self.assertNotContains(self.client.get("/services/"), "Plumbing")
        self.assertNotContains(self.client.get("/calendar/"), "Plumbing")
        self.assertNotContains(self.client.get("/profile/"), "Plumbing")
        self.client.logout()
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.client.get(f"/schedule/{self.team.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/policy/{self.team.pk}/").status_code, 404)

    def test_a_removed_team_gives_up_the_shifts_it_has_not_worked_yet(self):
        self.rota()
        earlier = Shift.objects.create(team=self.team, solver=self.cy, created_by=self.lead,
                                       starts_at=timezone.now() - timedelta(hours=20),
                                       ends_at=timezone.now() - timedelta(hours=12))
        running = Shift.objects.order_by("starts_at")[1]
        move_services(self.team, self.other, self.admin)
        outcome = remove_team(self.team, self.admin)
        self.assertEqual(outcome.messages, ["Plumbing was removed.", "Its 8 upcoming shifts were dropped."])
        self.assertEqual(self.upcoming(), [])
        # What was worked stays as history: the shift that ended, and the part of the running one that is over
        self.assertTrue(Shift.objects.filter(pk=earlier.pk).exists())
        running.refresh_from_db()
        self.assertEqual(running.solver, self.ann)
        self.assertLessEqual(running.ends_at, timezone.now())
        self.assertEqual(Shift.objects.filter(team=self.team).count(), 2)

    def test_the_solvers_of_a_removed_team_are_free_for_other_teams_and_hold_nothing(self):
        self.rota()
        move_services(self.team, self.other, self.admin)
        remove_team(self.team, self.admin)
        TeamMember.objects.create(user=self.bob, team=self.other)
        now = timezone.now()
        shift = Shift(team=self.other, solver=self.bob, created_by=self.lead,
                      starts_at=now + timedelta(hours=8), ends_at=now + timedelta(hours=14))
        self.assertNotIn("Bob Bell is already on call for Plumbing", " ".join(validate_schedule(self.other, [shift])))
        self.assertEqual(holdings(self.ann), {"shifts": {}, "led": [], "tiers": []})
        self.assertTrue(remove_user(self.ann, self.admin).ok)

    def test_a_team_is_restored_without_a_schedule(self):
        self.rota()
        move_services(self.team, self.other, self.admin)
        remove_team(self.team, self.admin)
        outcome = restore_team(self.team, self.admin)
        self.assertEqual(outcome.messages, [
            "Plumbing was restored. It owns no service now. Any service it had stayed with the team that took it.",
            "It has no on-call schedule yet. Lena Lead has to add shifts before its tickets can be assigned.",
        ])
        self.team.refresh_from_db()
        self.assertEqual((self.team.is_active, self.team.removed_by, self.team.removed_at), (True, None, None))
        self.assertEqual(self.upcoming(), [])
        self.assertEqual(restore_team(self.team, self.admin).messages, ["Plumbing is not removed"])

    def test_a_team_is_not_restored_onto_people_who_are_gone(self):
        EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user",
                                      escalate_to_user=self.ann, wait_minutes=5)
        self.team.lead = self.cy
        self.team.save()
        move_services(self.team, self.other, self.admin)
        remove_team(self.team, self.admin)
        # With the team gone, nothing depends on its lead or on the person in its tier, so both can be removed
        self.assertTrue(remove_user(self.cy, self.admin).ok)
        self.assertTrue(remove_user(self.ann, self.admin).ok)
        outcome = restore_team(self.team, self.admin)
        self.assertEqual(outcome.messages, [
            "Plumbing has no active lead. Appoint one first.",
            "Tier 3 of Plumbing names Ann Ames, who cannot take a ticket for it. Replace them in that tier first.",
        ])
        self.team.refresh_from_db()
        self.assertFalse(self.team.is_active)
        self.assertTrue(appoint_lead(self.team, self.bob, self.admin).ok)
        self.assertTrue(replace_in_tier(EscalationTier.objects.get(team=self.team, tier_number=3), self.bob, self.admin).ok)
        self.assertTrue(restore_team(self.team, self.admin).ok)

    def test_removed_services_move_with_the_team_and_can_be_restored_where_they_went(self):
        self.ticket()
        remove_service(self.service, self.admin)
        outcome = move_services(self.team, self.other, self.admin)
        self.assertEqual(outcome.messages, ["1 service and 1 unfinished ticket moved from Plumbing to Electrical."])
        remove_team(self.team, self.admin)
        self.assertTrue(restore_service(self.service, self.admin).ok)
        self.service.refresh_from_db()
        self.assertEqual((self.service.owning_team, self.service.is_active), (self.other, True))


class TicketTests(Campus):
    def on_call(self):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.bob, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def test_a_reason_is_required(self):
        ticket = self.ticket()
        for reason in ("", "   ", None):
            self.assertEqual(remove_ticket(ticket, self.admin, reason).messages, ["A reason is needed to remove a ticket"])
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_deleted)

    def test_a_ticket_at_any_status_is_removed_with_who_when_and_why(self):
        for status in ("open", "in_progress", "resolved", "closed"):
            ticket = self.ticket(status, status=status)
            self.assertEqual(remove_ticket(ticket, self.admin, " spam ").messages, [f"Ticket #{ticket.pk} was removed."])
            ticket.refresh_from_db()
            self.assertTrue(ticket.is_deleted)
            self.assertEqual(ticket.removed_by, self.admin)
            self.assertIsNotNone(ticket.removed_at)
            self.assertEqual(self.entries(ticket, "removal"), ["Ticket removed. Reason: spam"])

    def test_the_reporter_and_the_solver_are_told_and_the_slot_is_freed(self):
        self.on_call()
        held = [self.ticket(f"Held {n}") for n in range(3)]
        for ticket in held:
            assign_on_creation(ticket)
        waiting = self.ticket("Waiting")
        assign_on_creation(waiting)
        Notification.objects.all().delete()
        mail.outbox.clear()
        remove_ticket(held[0], self.admin, "duplicate")
        waiting.refresh_from_db()
        self.assertEqual((waiting.status, waiting.assigned_to), ("assigned", self.bob))
        told = Notification.objects.filter(event="override")
        self.assertEqual({note.user for note in told}, {self.reporter, self.bob})
        self.assertIn("was removed by an administrator. Reason: duplicate", told.get(user=self.reporter).message)

    def test_only_an_administrator_and_only_once(self):
        ticket = self.ticket()
        self.assertEqual(remove_ticket(ticket, self.lead, "spam").messages, ["Only an administrator can do this"])
        remove_ticket(ticket, self.admin, "spam")
        self.assertEqual(remove_ticket(ticket, self.admin, "spam").messages, [f"Ticket #{ticket.pk} is already removed"])

    def test_a_restored_ticket_that_was_being_worked_on_waits_for_a_solver(self):
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        remove_ticket(ticket, self.admin, "by mistake")
        self.assertEqual(restore_ticket(ticket, self.admin).messages, [f"Ticket #{ticket.pk} was restored."])
        ticket.refresh_from_db()
        self.assertEqual((ticket.is_deleted, ticket.removed_by, ticket.removed_at), (False, None, None))
        self.assertEqual((ticket.status, ticket.assigned_to), ("open", None))
        self.assertEqual(self.entries(ticket, "restored"), ["Ticket restored. It is waiting for a solver again."])

    def test_a_restored_ticket_is_handed_out_when_somebody_has_room(self):
        self.on_call()
        ticket = self.ticket(assigned_to=self.ann, status="assigned")
        remove_ticket(ticket, self.admin, "by mistake")
        restore_ticket(ticket, self.admin)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.assigned_to), ("assigned", self.bob))

    def test_a_finished_ticket_is_restored_as_it_was(self):
        ticket = self.ticket(assigned_to=self.ann, status="resolved")
        remove_ticket(ticket, self.admin, "by mistake")
        restore_ticket(ticket, self.admin)
        ticket.refresh_from_db()
        self.assertEqual((ticket.is_deleted, ticket.status, ticket.assigned_to), (False, "resolved", self.ann))
        self.assertEqual(self.entries(ticket, "restored"), ["Ticket restored."])
        self.assertEqual(restore_ticket(ticket, self.admin).messages, [f"Ticket #{ticket.pk} is not removed"])

    def test_the_timeline_shows_who_did_it_as_an_administrator(self):
        ticket = self.ticket()
        remove_service(self.service, self.admin)
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        page = self.client.get(f"/incidents/{ticket.pk}/")
        self.assertContains(page, "Removed</span> The service Pipes was removed. This ticket carries on as normal.")
        self.assertContains(page, '<span class="tl-role">administrator</span>')


class WhoIsToldTests(Campus):
    """Nobody loses a ticket, a team or a removed ticket without hearing about it."""

    def told(self, user, event):
        return list(Notification.objects.filter(user=user, event=event).order_by("id").values_list("message", flat=True))

    def test_a_restored_reporter_is_not_said_to_have_had_shifts(self):
        remove_user(self.reporter, self.admin)
        self.assertEqual(restore_user(self.reporter, self.admin).messages, ["Rae Port can log in again."])
        remove_user(self.cy, self.admin)
        self.assertEqual(restore_user(self.cy, self.admin).messages,
                         ["Cy Cole can log in again.", "Their shifts and roles stayed with whoever took them over."])

    def test_the_reporter_hears_that_a_removed_ticket_is_back(self):
        ticket = self.ticket()
        remove_ticket(ticket, self.admin, "by mistake")
        restore_ticket(ticket, self.admin)
        self.assertEqual(self.told(self.reporter, "override")[-1],
                         f"Your ticket #{ticket.pk}, {ticket.title}, was restored by an administrator.")

    def test_the_old_lead_hears_that_somebody_else_leads_the_team(self):
        appoint_lead(self.team, self.ann, self.admin)
        self.assertEqual(self.told(self.lead, "handover"), ["You no longer lead Plumbing. Ann Ames leads it now."])

    def test_a_solver_hears_that_their_ticket_moved_to_another_team(self):
        other = Team.objects.create(name="Electrical", lead=self.lead)
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        move_services(self.team, other, self.admin)
        self.assertEqual(self.told(self.ann, "override"),
                         [f"Ticket #{ticket.pk} for Pipes, medium severity, moved from Plumbing to Electrical with its "
                          f"service. You no longer hold it."])

    def test_a_restored_team_says_which_services_are_still_its_own(self):
        remove_service(self.service, self.admin)
        remove_team(self.team, self.admin)
        self.assertEqual(restore_team(self.team, self.admin).messages[0],
                         "Plumbing was restored. Its 1 service is still removed. Restore it from the same list.")
