"""Shared test helpers."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import EscalationTier, Incident, IncidentUpdate, Service, Shift, Team, TeamMember, User


GOOD_PASSWORD = "Good!Pass1"


def register(client, email, password=GOOD_PASSWORD, password2=None):
    """Submit the registration form. password2 defaults to password."""
    return client.post("/register/", {
        "first_name": "Test",
        "last_name": "User",
        "email": email,
        "password": password,
        "password2": password2 if password2 is not None else password,
    })


def make_user(email="user@example.com"):
    """Create a user directly, bypassing the form."""
    return User.objects.create_user(
        username=email, email=email, password=GOOD_PASSWORD,
        first_name="Test", last_name="User",
    )


def make_service():
    """Create one team and one service to file tickets against."""
    team = Team.objects.create(name="Plumbing")
    return Service.objects.create(name="Restroom Plumbing", owning_team=team)


class Campus(TestCase):
    """One team of three solvers on an eight hour rota, its lead, a reporter and an administrator."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin@x.com", email="admin@x.com",
                                                   password=GOOD_PASSWORD, first_name="Ada", last_name="Min")
        self.reporter = self.person("r@x.com", "Rae", "Port", "reporter")
        self.lead = self.person("lead@x.com", "Lena", "Lead", "solver")
        self.ann = self.person("ann@x.com", "Ann", "Ames", "solver")
        self.bob = self.person("bob@x.com", "Bob", "Bell", "solver")
        self.cy = self.person("cy@x.com", "Cy", "Cole", "solver")
        self.team = Team.objects.create(name="Plumbing", lead=self.lead)
        for user in (self.ann, self.bob, self.cy):
            TeamMember.objects.create(user=user, team=self.team)
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        EscalationTier.objects.create(team=self.team, tier_number=1, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="lead", wait_minutes=10)

    def person(self, email, first, last, role):
        return User.objects.create_user(username=email, email=email, password=GOOD_PASSWORD,
                                        first_name=first, last_name=last, role=role)

    def rota(self, team=None, solvers=None, blocks=9):
        """Eight hour shifts in turn, the first one already an hour old."""
        team = team or self.team
        solvers = solvers or [self.ann, self.bob, self.cy]
        start = timezone.now() - timedelta(hours=1)
        for n in range(blocks):
            Shift.objects.create(team=team, solver=solvers[n % len(solvers)], created_by=self.lead,
                                 starts_at=start + timedelta(hours=8 * n), ends_at=start + timedelta(hours=8 * n + 8))

    def upcoming(self, team=None):
        return list(Shift.objects.filter(team=team or self.team, on_call_role="primary", ends_at__gt=timezone.now())
                    .order_by("starts_at"))

    def ticket(self, title="Leak", **fields):
        return Incident.objects.create(title=title, description="d", service=self.service,
                                       reported_by=self.reporter, assigned_team=self.team, **fields)

    def entries(self, ticket, kind):
        return list(IncidentUpdate.objects.filter(incident=ticket, update_type=kind).values_list("body", flat=True))
