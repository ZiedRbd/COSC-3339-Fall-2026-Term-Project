"""The profile page for reporters and solvers."""
from django.test import TestCase

from ops.models import Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class ProfileAccessTests(TestCase):
    """The profile page requires login."""

    def test_profile_requires_login(self):
        """A logged-out visitor is redirected away from the profile."""
        r = self.client.get("/profile/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith("/login/"))


class SolverProfileTests(TestCase):
    """A solver's profile shows their team and members, not ticket columns."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD,
            first_name="Sol", last_name="Ver", role="solver")
        self.mate = User.objects.create_user(
            username="m@x.com", email="m@x.com", password=GOOD_PASSWORD,
            first_name="Team", last_name="Mate", role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        TeamMember.objects.create(user=self.mate, team=self.team)

    def test_solver_profile_lists_team_and_members(self):
        """The solver sees their team name and both members."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        html = self.client.get("/profile/").content.decode()
        self.assertIn("Plumbing", html)
        self.assertIn("Team Mate", html)
        self.assertIn("(you)", html)

    def test_solver_profile_has_no_edit_links(self):
        """Solvers get no ticket edit links on their profile."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        html = self.client.get("/profile/").content.decode()
        self.assertNotIn("/edit/", html)

    def test_solver_profile_links_to_team_tickets(self):
        """The solver profile offers a route to the tickets assigned to their team."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        html = self.client.get("/profile/").content.decode()
        self.assertIn("/incidents/list", html)
        self.assertIn("View tickets assigned to Plumbing", html)
