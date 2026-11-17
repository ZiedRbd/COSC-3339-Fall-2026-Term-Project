"""A service that is switched off is not offered on the ticket form."""
from django.test import TestCase

from ops.models import Incident, Service, Team, User
from ops.tests.helpers import GOOD_PASSWORD


class RetiredServiceTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.pipes = Service.objects.create(name="Pipes", owning_team=self.team)
        self.pagers = Service.objects.create(name="Pagers", owning_team=self.team, is_active=False)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Port")
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)

    def fields(self, service, title="Old pager is dead"):
        return {"title": title, "description": "d", "building": "", "room": "",
                "service": service.pk, "priority": "low"}

    def test_the_ticket_form_offers_only_services_that_are_switched_on(self):
        page = self.client.get("/incidents/form")
        self.assertContains(page, "Pipes")
        self.assertNotContains(page, "Pagers")

    def test_a_ticket_cannot_be_filed_against_a_switched_off_service(self):
        self.client.post("/incidents/form", self.fields(self.pagers))
        self.assertEqual(Incident.objects.count(), 0)
        self.client.post("/incidents/form", self.fields(self.pipes))
        self.assertEqual(Incident.objects.count(), 1)

    def test_a_ticket_filed_before_the_service_was_switched_off_can_still_be_edited(self):
        ticket = Incident.objects.create(title="Old pager is dead", description="d", service=self.pagers,
                                         reported_by=self.reporter, assigned_team=self.team)
        self.client.post(f"/incidents/{ticket.pk}/edit/", self.fields(self.pagers, title="Pager is dead again"))
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "Pager is dead again")
        self.assertEqual(ticket.service, self.pagers)
