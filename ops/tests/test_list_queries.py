"""The incident list names who holds each ticket without a database query per row."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from ops.models import Incident, Service, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class ListQueryTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Port")
        self.viewer = self.solver("viewer@x.com", "Vera", "View")
        self.client.login(username="viewer@x.com", password=GOOD_PASSWORD)

    def solver(self, email, first, last):
        user = User.objects.create_user(username=email, email=email, password=GOOD_PASSWORD,
                                        first_name=first, last_name=last, role="solver")
        TeamMember.objects.create(user=user, team=self.team)
        return user

    def add_tickets(self, start, count):
        for n in range(start, start + count):
            holder = self.solver(f"s{n}@x.com", "Solver", f"Number{n}")
            Incident.objects.create(title=f"Leak {n}", description="d", service=self.service,
                                    reported_by=self.reporter, assigned_team=self.team,
                                    assigned_to=holder, status="in_progress")

    def queries_for_the_list(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/incidents/list")
        self.assertEqual(response.status_code, 200)
        return len(queries), response.content.decode()

    def test_more_tickets_with_more_holders_cost_no_more_queries(self):
        self.add_tickets(1, 3)
        few, html = self.queries_for_the_list()
        self.assertIn("Solver Number1", html)
        self.add_tickets(4, 12)
        many, html = self.queries_for_the_list()
        self.assertIn("Solver Number15", html)
        self.assertEqual(many, few)
