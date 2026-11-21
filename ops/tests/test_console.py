"""The administrator console: who may open it, and every action its dialog offers."""
from datetime import timedelta

from django.utils import timezone

from ops.models import Building, EscalationTier, Incident, Service, Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD, Campus


class ConsoleCase(Campus):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def done(self, response):
        """The dialog's work went through: the page is told to load again."""
        self.assertEqual(response.status_code, 204, getattr(response, "content", b"")[:400])
        self.assertEqual(response["X-Console-Done"], "1")

    def notices(self):
        """What the page shows once it has loaded again."""
        return [str(message) for message in self.client.get("/console/").context["messages"]]


class AccessTests(ConsoleCase):
    def test_only_an_administrator_can_open_the_console_or_any_of_its_dialogs(self):
        addresses = ["/console/", "/console/users/add/", f"/console/users/{self.ann.pk}/remove/",
                     f"/console/teams/{self.team.pk}/remove/", f"/console/services/{self.service.pk}/edit/"]
        for person in (self.reporter, self.ann, self.lead):
            self.client.force_login(person)
            for address in addresses:
                self.assertEqual(self.client.get(address).status_code, 404, (person.email, address))
            self.assertEqual(self.client.post(f"/console/restore/user/{self.bob.pk}/").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get("/console/").status_code, 302)

    def test_the_console_link_is_in_the_navigation_for_an_administrator_only(self):
        self.assertContains(self.client.get("/"), 'href="/console/"')
        self.client.force_login(self.lead)
        self.assertNotContains(self.client.get("/"), 'href="/console/"')

    def test_the_page_lists_every_part_of_the_system_and_remembers_the_tab(self):
        ticket = self.ticket("Dripping tap")
        response = self.client.get("/console/?tab=teams")
        self.assertEqual(response.context["open_tab"], "teams")
        self.assertEqual([tab["label"] for tab in response.context["tabs"]],
                         ["Users", "Teams", "Services", "Buildings", "Tickets", "Removed"])
        for shown in ("Ann Ames", "Plumbing", "Pipes", "Dripping tap", "Team lead", "Administrator"):
            self.assertContains(response, shown)
        self.assertContains(response, f"/console/tickets/{ticket.pk}/override/")
        self.assertEqual(self.client.get("/console/?tab=nonsense").context["open_tab"], "users")


class UserTests(ConsoleCase):
    NEW = {"first_name": "Dee", "last_name": "Dunn", "email": "Dee@X.com", "role": "auditor", "password": GOOD_PASSWORD}

    def test_a_user_is_added_with_a_role_and_can_log_in(self):
        self.done(self.client.post("/console/users/add/", self.NEW))
        dee = User.objects.get(email="dee@x.com")
        self.assertEqual((dee.role, dee.username, dee.first_name), ("auditor", "dee@x.com", "Dee"))
        self.assertTrue(dee.check_password(GOOD_PASSWORD))
        self.assertEqual(self.notices(), ["Dee Dunn was added as an auditor."])

    def test_a_mistake_comes_back_in_the_dialog_and_nothing_is_saved(self):
        response = self.client.post("/console/users/add/", {**self.NEW, "email": "ann@x.com", "password": "short"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This email is already registered")
        self.assertContains(response, "Password needs at least 8 characters")
        self.assertEqual(User.objects.count(), 6)
        self.assertContains(self.client.post("/console/users/add/", {**self.NEW, "password": ""}),
                            "A new account needs a password")

    def test_an_edit_changes_the_details_and_keeps_the_password_unless_one_is_typed(self):
        details = {"first_name": "Anna", "last_name": "Ames", "email": "anna@x.com", "role": "solver", "password": ""}
        self.done(self.client.post(f"/console/users/{self.ann.pk}/edit/", details))
        self.ann.refresh_from_db()
        self.assertEqual((self.ann.first_name, self.ann.email, self.ann.username), ("Anna", "anna@x.com", "anna@x.com"))
        self.assertTrue(self.ann.check_password(GOOD_PASSWORD))
        self.done(self.client.post(f"/console/users/{self.ann.pk}/edit/", {**details, "password": "Other!Pass2"}))
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.check_password("Other!Pass2"))

    def test_a_solver_on_a_team_cannot_be_given_another_role(self):
        details = {"first_name": "Ann", "last_name": "Ames", "email": "ann@x.com", "role": "reporter", "password": ""}
        self.assertContains(self.client.post(f"/console/users/{self.ann.pk}/edit/", details),
                            "This solver is on a team. Take them off every team first.")
        details.update(first_name="Lena", last_name="Lead", email="lead@x.com")
        self.assertContains(self.client.post(f"/console/users/{self.lead.pk}/edit/", details),
                            "This solver leads a team. Appoint a new lead first.")
        self.ann.refresh_from_db()
        self.assertEqual(self.ann.role, "solver")

    def test_the_administrator_cannot_remove_their_own_account(self):
        response = self.client.post(f"/console/users/{self.admin.pk}/remove/", {"step": "finish"})
        self.assertContains(response, "You cannot remove the account you are signed in with.")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_a_user_who_holds_nothing_is_removed_and_can_be_reactivated(self):
        address = f"/console/users/{self.reporter.pk}/remove/"
        self.assertContains(self.client.get(address), "Rae Port holds nothing that needs handing over.")
        self.done(self.client.post(address, {"step": "finish"}))
        self.reporter.refresh_from_db()
        self.assertFalse(self.reporter.is_active)
        self.assertEqual(self.reporter.removed_by, self.admin)
        self.assertContains(self.client.get("/console/?tab=removed"), "Reactivate account")
        response = self.client.post(f"/console/restore/user/{self.reporter.pk}/")
        self.assertRedirects(response, "/console/?tab=removed")
        self.reporter.refresh_from_db()
        self.assertTrue(self.reporter.is_active)

    def test_a_solver_hands_over_shifts_and_a_tier_in_the_dialog_before_the_removal_goes_through(self):
        self.rota()
        tier = EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user",
                                             escalate_to_user=self.ann, wait_minutes=5)
        held = self.ticket(assigned_to=self.ann, status="in_progress")
        address = f"/console/users/{self.ann.pk}/remove/"
        dialog = self.client.get(address)
        self.assertContains(dialog, "3 upcoming shifts on Plumbing")
        self.assertContains(dialog, "Tier 3 of the Plumbing escalation policy")
        self.assertContains(dialog, 'disabled title="Hand over everything above first"')
        # Pressing Remove early is refused, and says what is still held
        self.assertContains(self.client.post(address, {"step": "finish"}), "Transfer them first.")
        self.assertContains(self.client.post(address, {"step": "shifts", "team": self.team.pk, "person": ""}),
                            "notice success")
        self.assertNotIn(self.ann.pk, [shift.solver_id for shift in self.upcoming()])
        after_tier = self.client.post(address, {"step": "tier", "tier": tier.pk, "person": self.bob.pk})
        self.assertContains(after_tier, "Ann Ames holds nothing that needs handing over.")
        self.assertContains(after_tier, "Their 1 unfinished ticket goes back to the queue.")
        tier.refresh_from_db()
        self.assertEqual(tier.escalate_to_user, self.bob)
        self.done(self.client.post(address, {"step": "finish"}))
        self.ann.refresh_from_db()
        held.refresh_from_db()
        self.assertFalse(self.ann.is_active)
        self.assertNotEqual(held.assigned_to, self.ann)

    def test_a_lead_is_replaced_in_the_dialog_before_the_removal_goes_through(self):
        address = f"/console/users/{self.lead.pk}/remove/"
        self.assertContains(self.client.get(address), "Lead of Plumbing")
        self.assertContains(self.client.post(address, {"step": "lead", "team": self.team.pk, "person": self.bob.pk}),
                            "Lena Lead holds nothing that needs handing over.")
        self.team.refresh_from_db()
        self.assertEqual(self.team.lead, self.bob)
        self.done(self.client.post(address, {"step": "finish"}))


class TeamTests(ConsoleCase):
    def test_a_team_is_added_with_a_lead_and_the_default_policy(self):
        self.done(self.client.post("/console/teams/add/", {"name": " Grounds  crew ", "description": "", "lead": self.cy.pk}))
        team = Team.objects.get(name="Grounds crew")
        self.assertEqual(team.lead, self.cy)
        self.assertEqual(list(team.escalation_tiers.values_list("tier_number", "escalate_to")), [(1, "on_call"), (2, "lead")])

    def test_a_team_name_cannot_repeat_an_active_or_a_removed_team(self):
        Team.objects.create(name="Old crew", is_active=False)
        self.assertContains(self.client.post("/console/teams/add/", {"name": "plumbing", "lead": self.cy.pk}),
                            "A team already has this name")
        self.assertContains(self.client.post("/console/teams/add/", {"name": "Old Crew", "lead": self.cy.pk}),
                            "A removed team has this name. Restore it from the Removed tab.")
        self.assertContains(self.client.post("/console/teams/add/", {"name": "New", "lead": self.reporter.pk}),
                            "Select a valid choice")

    def test_a_team_is_renamed(self):
        self.done(self.client.post(f"/console/teams/{self.team.pk}/edit/", {"name": "Pipes and drains", "description": "Water"}))
        self.team.refresh_from_db()
        self.assertEqual((self.team.name, self.team.description, self.team.lead), ("Pipes and drains", "Water", self.lead))

    def test_members_are_added_and_a_new_lead_is_appointed_in_the_members_dialog(self):
        dee = self.person("dee@x.com", "Dee", "Dunn", "solver")
        address = f"/console/teams/{self.team.pk}/members/"
        self.assertContains(self.client.get(address), "Ann Ames")
        self.assertContains(self.client.post(address, {"step": "add", "person": dee.pk}), "Dee Dunn is now on Plumbing.")
        self.assertTrue(TeamMember.objects.filter(user=dee, team=self.team).exists())
        # A reporter is not added, whatever the request says
        self.client.post(address, {"step": "add", "person": self.reporter.pk})
        self.assertFalse(TeamMember.objects.filter(user=self.reporter).exists())
        self.assertContains(self.client.post(address, {"step": "lead", "person": self.bob.pk}), "notice success")
        self.team.refresh_from_db()
        self.assertEqual(self.team.lead, self.bob)

    def test_a_solver_comes_off_a_team_after_handing_over_their_shifts_there(self):
        self.rota()
        address = f"/console/teams/{self.team.pk}/members/{self.ann.pk}/leave/"
        self.assertContains(self.client.get(address), "Take Ann Ames off Plumbing")
        self.assertContains(self.client.post(address, {"step": "shifts", "team": self.team.pk, "person": self.bob.pk}),
                            "Ann Ames holds nothing on Plumbing that needs handing over.")
        self.done(self.client.post(address, {"step": "finish"}))
        self.assertFalse(TeamMember.objects.filter(user=self.ann, team=self.team).exists())
        self.ann.refresh_from_db()
        self.assertTrue(self.ann.is_active)

    def test_a_lead_comes_off_their_own_team_without_naming_a_new_lead(self):
        # Lena leads Plumbing. Leading a team does not need a seat on it, so nothing is handed over.
        TeamMember.objects.create(user=self.lead, team=self.team)
        held = self.ticket(assigned_to=self.lead, status="in_progress")
        address = f"/console/teams/{self.team.pk}/members/{self.lead.pk}/leave/"
        dialog = self.client.get(address)
        self.assertNotContains(dialog, "Lead of Plumbing")
        self.assertContains(dialog, "Lena still leads Plumbing and keeps its tickets.")
        self.done(self.client.post(address, {"step": "finish"}))
        self.team.refresh_from_db()
        held.refresh_from_db()
        self.assertEqual((self.team.lead, held.assigned_to), (self.lead, self.lead))
        self.assertFalse(TeamMember.objects.filter(user=self.lead, team=self.team).exists())

    def test_the_dialog_counts_the_tickets_that_go_back_when_a_solver_comes_off_a_team(self):
        self.ticket(assigned_to=self.ann, status="in_progress")
        address = f"/console/teams/{self.team.pk}/members/{self.ann.pk}/leave/"
        self.assertContains(self.client.get(address), "Their 1 unfinished ticket on this team goes back to its queue.")

    def test_removing_a_ticket_says_who_is_told(self):
        held = self.ticket(assigned_to=self.ann, status="assigned")
        waiting = self.ticket("Nobody has it")
        self.assertContains(self.client.get(f"/console/tickets/{held.pk}/remove/"),
                            "Its reporter and Ann Ames, who holds it, are told.")
        self.assertContains(self.client.get(f"/console/tickets/{waiting.pk}/remove/"), "Its reporter is told.")

    def test_a_team_moves_its_services_and_tickets_before_it_is_removed_and_can_be_restored(self):
        other = Team.objects.create(name="Electrical", lead=self.lead)
        waiting = self.ticket()
        address = f"/console/teams/{self.team.pk}/remove/"
        dialog = self.client.get(address)
        self.assertContains(dialog, "Services: Pipes")
        self.assertContains(dialog, "1 unfinished ticket")
        self.assertContains(dialog, 'disabled title="Move its work to another team first"')
        self.assertContains(self.client.post(address, {"step": "finish"}), "notice error")
        self.assertContains(self.client.post(address, {"step": "move", "team": other.pk}),
                            "Plumbing has no service and no unfinished ticket left.")
        self.service.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual((self.service.owning_team, waiting.assigned_team), (other, other))
        self.done(self.client.post(address, {"step": "finish"}))
        self.team.refresh_from_db()
        self.assertFalse(self.team.is_active)
        self.assertContains(self.client.get("/console/?tab=removed"), f"/console/restore/team/{self.team.pk}/")
        self.client.post(f"/console/restore/team/{self.team.pk}/")
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_active)

    def test_a_restore_that_is_refused_says_why_on_the_page(self):
        team = Team.objects.create(name="Old crew", is_active=False)
        self.client.post(f"/console/restore/team/{team.pk}/")
        team.refresh_from_db()
        self.assertFalse(team.is_active)
        self.assertTrue(self.notices())
        self.assertEqual(self.client.post("/console/restore/planet/1/").status_code, 404)
        self.assertEqual(self.client.get(f"/console/restore/team/{team.pk}/").status_code, 405)


class ServiceAndBuildingTests(ConsoleCase):
    def test_a_service_is_added_edited_removed_and_restored(self):
        self.done(self.client.post("/console/services/add/", {"name": "Drains", "description": "", "owning_team": self.team.pk,
                                                              "criticality": "high"}))
        drains = Service.objects.get(name="Drains")
        self.assertEqual((drains.owning_team, drains.criticality, drains.is_active), (self.team, "high", True))
        self.assertContains(self.client.post("/console/services/add/", {"name": "pipes", "owning_team": self.team.pk,
                                                                        "criticality": "low"}),
                            "A service already has this name")
        self.done(self.client.post(f"/console/services/{drains.pk}/edit/", {"name": "Storm drains", "description": "Outside",
                                                                            "owning_team": self.team.pk, "criticality": "low"}))
        drains.refresh_from_db()
        self.assertEqual((drains.name, drains.criticality), ("Storm drains", "low"))
        self.assertContains(self.client.get(f"/console/services/{drains.pk}/remove/"), "Nobody can file a new ticket for it.")
        self.done(self.client.post(f"/console/services/{drains.pk}/remove/"))
        drains.refresh_from_db()
        self.assertFalse(drains.is_active)
        self.client.post(f"/console/restore/service/{drains.pk}/")
        drains.refresh_from_db()
        self.assertTrue(drains.is_active)

    def test_a_service_with_unfinished_tickets_stays_with_its_team(self):
        other = Team.objects.create(name="Electrical", lead=self.lead)
        self.ticket()
        response = self.client.post(f"/console/services/{self.service.pk}/edit/", {
            "name": "Pipes", "description": "", "owning_team": other.pk, "criticality": "medium"})
        self.assertContains(response, "This service has unfinished tickets with its team.")
        self.service.refresh_from_db()
        self.assertEqual(self.service.owning_team, self.team)

    def test_a_building_is_added_edited_removed_and_restored(self):
        self.done(self.client.post("/console/buildings/add/", {"name": "Test Annex", "aliases": "annex", "kind": "campus"}))
        annex = Building.objects.get(name="Test Annex")
        self.done(self.client.post(f"/console/buildings/{annex.pk}/edit/", {"name": "Test Annex", "aliases": "annex, ta",
                                                                           "kind": "residence"}))
        annex.refresh_from_db()
        self.assertEqual((annex.aliases, annex.kind), ("annex, ta", "residence"))
        self.done(self.client.post(f"/console/buildings/{annex.pk}/remove/"))
        annex.refresh_from_db()
        self.assertFalse(annex.is_active)
        self.assertContains(self.client.post("/console/buildings/add/", {"name": "test annex", "kind": "campus"}),
                            "A removed building has this name. Restore it from the Removed tab.")
        self.client.post(f"/console/restore/building/{annex.pk}/")
        annex.refresh_from_db()
        self.assertTrue(annex.is_active)


class TicketTests(ConsoleCase):
    def on_call(self, solver):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=solver, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def test_a_ticket_is_removed_only_with_a_reason_and_can_be_restored(self):
        ticket = self.ticket(assigned_to=self.ann, status="assigned")
        address = f"/console/tickets/{ticket.pk}/remove/"
        self.assertContains(self.client.get(address), "Remove ticket")
        self.assertEqual(self.client.post(address, {"reason": "  "}).status_code, 200)
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_deleted)
        self.done(self.client.post(address, {"reason": "Filed twice"}))
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_deleted)
        self.assertIn("Filed twice", " ".join(self.entries(ticket, "removal")))
        self.client.post(f"/console/restore/ticket/{ticket.pk}/")
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_deleted)

    def test_an_override_needs_a_reason_and_closes_a_ticket_from_any_state(self):
        ticket = self.ticket(assigned_to=self.ann, status="assigned")
        address = f"/console/tickets/{ticket.pk}/override/"
        self.assertContains(self.client.get(address), "Override ticket")
        self.assertContains(self.client.post(address, {"new_status": "closed", "new_solver": "", "reason": ""}),
                            "An override needs a reason")
        self.assertContains(self.client.post(address, {"new_status": "", "new_solver": "", "reason": "why not"}),
                            "Nothing would change.")
        closing = {"new_status": "closed", "new_solver": "", "reason": "Duplicate of 4"}
        # Closing a ticket nobody resolved steps over the normal order, so it is confirmed first
        self.assertContains(self.client.post(address, closing), "Override anyway")
        self.done(self.client.post(address, {**closing, "confirmed": "closed|"}))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "closed")
        self.assertEqual(len(self.entries(ticket, "override")), 1)

    def test_an_override_that_steps_over_a_rule_warns_first_and_happens_once_confirmed(self):
        self.on_call(self.bob)
        ticket = self.ticket(assigned_to=self.bob, status="assigned")
        address = f"/console/tickets/{ticket.pk}/override/"
        choice = {"new_status": "", "new_solver": str(self.cy.pk), "reason": "Cy knows this pipe"}
        warned = self.client.post(address, choice)
        self.assertContains(warned, "This steps over the normal rules.")
        self.assertContains(warned, "Override anyway")
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.bob)
        # A confirmation given for one choice does not carry over to another
        other = self.client.post(address, {**choice, "new_solver": str(self.ann.pk), "confirmed": f"|{self.cy.pk}"})
        self.assertContains(other, "Override anyway")
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.bob)
        self.done(self.client.post(address, {**choice, "confirmed": f"|{self.cy.pk}"}))
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.cy)

    def test_a_lead_overrides_on_their_own_team_from_the_ticket_page_and_nobody_else_can(self):
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        address = f"/console/tickets/{ticket.pk}/override/"
        for person in (self.ann, self.reporter):
            self.client.force_login(person)
            self.assertEqual(self.client.get(address).status_code, 404)
            self.assertNotContains(self.client.get(f"/incidents/{ticket.pk}/"), address)
        elsewhere = self.person("eve@x.com", "Eve", "Else", "solver")
        Team.objects.create(name="Electrical", lead=elsewhere)
        self.client.force_login(elsewhere)
        self.assertEqual(self.client.post(address, {"new_status": "closed", "reason": "mine now"}).status_code, 404)
        self.client.force_login(self.lead)
        self.assertContains(self.client.get(f"/incidents/{ticket.pk}/"), address)
        self.done(self.client.post(address, {"new_status": "resolved", "new_solver": "", "reason": "Fixed on site",
                                             "confirmed": "resolved|"}))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertEqual(Incident.objects.filter(pk=ticket.pk, is_deleted=False).count(), 1)
