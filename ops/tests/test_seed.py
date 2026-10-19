"""The demo data the seed command loads."""
import io

from django.core.management import call_command
from django.test import TestCase

from ops.models import Team, TeamMember, User


class SeedLeadsTests(TestCase):
    """The seed sets up the leads and solvers the sprint roster asks for."""

    def test_seed_assigns_leads_and_six_solvers(self):
        """Pat leads two teams and is a Plumbing member. Maya leads one and is on no team."""
        call_command("seed", stdout=io.StringIO())
        pat = User.objects.get(email="pat.diaz@campusdesk.edu")
        maya = User.objects.get(email="maya.ortiz@campusdesk.edu")
        self.assertEqual(Team.objects.get(name="Plumbing").lead, pat)
        self.assertEqual(Team.objects.get(name="Electrical").lead, pat)
        self.assertEqual(Team.objects.get(name="IT Support").lead, maya)
        self.assertTrue(TeamMember.objects.filter(user=pat, team__name="Plumbing").exists())
        self.assertFalse(TeamMember.objects.filter(user=maya).exists())
        self.assertEqual(User.objects.filter(role="solver").count(), 6)
        self.assertFalse(Team.objects.filter(lead__isnull=True).exists())
        self.assertEqual({pat.role, maya.role}, {"solver"})
