"""Each role sees the messages meant for it: a reporter sees where a ticket stands, not the team's alerts."""
from datetime import timedelta

from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.utils import timezone

from ops.models import EscalationTier, Incident, Service, Shift, Team, TeamMember, User
from ops.scheduling import assign_on_creation, escalate_due
from ops.tests.helpers import GOOD_PASSWORD


class TicketPageByRoleTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = self.person("r@x.com", "Rae", "Lee", "reporter")
        self.lead = self.person("lead@x.com", "Pat", "Lee", "solver")
        self.tim = self.person("tim@x.com", "Tim", "Diaz", "solver")
        self.admin = User.objects.create_superuser(username="admin@x.com", email="admin@x.com",
                                                   password=GOOD_PASSWORD, first_name="Ada", last_name="Min")
        for user in (self.tim, self.lead):
            TeamMember.objects.create(user=user, team=self.team)
        self.team.lead = self.lead
        self.team.save()
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="lead", wait_minutes=10)

    def person(self, email, first, last, role):
        return User.objects.create_user(username=email, email=email, password=GOOD_PASSWORD,
                                        first_name=first, last_name=last, role=role)

    def on_call(self):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def file(self):
        ticket = Incident.objects.create(title="Leak", description="d", service=self.svc, reported_by=self.reporter)
        assign_on_creation(ticket)
        return ticket

    def nobody_took_it(self):
        """A ticket that went from the on-call solver to the lead and then ran out."""
        self.on_call()
        ticket = self.file()
        escalate_due(timezone.now() + timedelta(minutes=5))
        escalate_due(timezone.now() + timedelta(minutes=15))
        return ticket

    def page(self, email, ticket):
        self.client.login(username=email, password=GOOD_PASSWORD)
        return self.client.get(f"/incidents/{ticket.pk}/")

    def test_a_reporter_is_not_shown_the_alert_that_nobody_took_the_ticket(self):
        page = self.page("r@x.com", self.nobody_took_it())
        for internal in ("escalation policy ran out", "needs attention", "did not start work", "Escalated",
                         "team lead has been told", "ran-out", "tl-escalation"):
            self.assertNotContains(page, internal)
        self.assertContains(page, "Waiting for a solver to pick it up.")

    def test_a_reporter_sees_who_has_the_ticket_after_an_escalation_and_not_why(self):
        self.on_call()
        ticket = self.file()
        escalate_due(timezone.now() + timedelta(minutes=5))
        page = self.page("r@x.com", ticket)
        self.assertContains(page, "Now with Pat Lee")
        self.assertContains(page, "Assigned to Pat Lee.")
        self.assertNotContains(page, "did not start work")
        self.assertNotContains(page, "who has not started on it yet")

    def test_a_reporter_whose_ticket_is_waiting_is_not_told_why_the_team_has_nobody(self):
        ticket = self.file()
        page = self.page("r@x.com", ticket)
        self.assertNotContains(page, "Nobody is on call")
        self.assertContains(page, "Waiting for a solver")
        self.assertContains(self.page("tim@x.com", ticket), "Nobody is on call for Plumbing right now")

    def test_the_solver_and_the_lead_still_see_the_alert_and_the_reasons(self):
        ticket = self.nobody_took_it()
        for email in ("tim@x.com", "lead@x.com"):
            page = self.page(email, ticket)
            self.assertContains(page, "escalation policy ran out")
            self.assertContains(page, "Tim Diaz did not start work within 5 minutes")
            self.assertContains(page, "ran-out")

    def test_the_administrator_sees_the_alert_and_is_not_offered_a_comment_box(self):
        ticket = self.nobody_took_it()
        page = self.page("admin@x.com", ticket)
        self.assertContains(page, "escalation policy ran out")
        self.assertNotContains(page, "Post comment")
        self.assertNotContains(page, "comment-form")

    def test_the_reporter_and_the_solver_keep_their_comment_box(self):
        ticket = self.nobody_took_it()
        self.assertContains(self.page("r@x.com", ticket), "Post comment")
        self.assertContains(self.page("tim@x.com", ticket), "Post note")


class ErrorPageTests(TestCase):
    def test_a_missing_page_is_the_sites_own_page(self):
        page = self.client.get("/no/such/page/")
        self.assertEqual(page.status_code, 404)
        self.assertContains(page, "Page not found", status_code=404)
        self.assertContains(page, "Go to the home page", status_code=404)

    def test_a_form_sent_from_a_stale_page_says_to_try_again(self):
        strict = Client(enforce_csrf_checks=True)
        page = strict.post("/login/", {"email": "a@x.com", "password": "x"})
        self.assertEqual(page.status_code, 403)
        self.assertContains(page, "Please try again", status_code=403)
        self.assertNotContains(page, "CSRF", status_code=403)

    def test_the_page_for_a_server_fault_stands_on_its_own(self):
        html = render_to_string("500.html")
        self.assertIn("Something went wrong", html)
        self.assertNotIn("{%", html)
