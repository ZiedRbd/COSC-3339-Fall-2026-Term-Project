"""The lead's escalation policy page: tiers in order, rules enforced, nobody else gets in."""
from django.test import TestCase

from ops.models import EscalationTier, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class PolicyPageTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.other = Team.objects.create(name="Electrical")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.outsider = User.objects.create_user(username="out@x.com", email="out@x.com", password=GOOD_PASSWORD,
                                                 first_name="Ola", last_name="Ng", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        TeamMember.objects.create(user=self.outsider, team=self.other)
        self.team.lead = self.lead
        self.team.save()
        self.url = f"/policy/{self.team.pk}/"
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)

    def add(self, **data):
        return self.client.post(self.url, {"action": "add", **data})

    def tiers(self):
        return [(t.tier_number, t.escalate_to, t.wait_minutes) for t in self.team.escalation_tiers.all()]

    def test_lead_builds_a_policy_tier_by_tier(self):
        self.add(escalate_to="on_call", wait_minutes=5)
        self.add(escalate_to="lead", wait_minutes=10)
        self.add(escalate_to="administration", wait_minutes="")
        self.assertEqual(self.tiers(), [(1, "on_call", 5), (2, "lead", 10), (3, "administration", None)])

    def test_negative_wait_is_refused(self):
        resp = self.add(escalate_to="on_call", wait_minutes=-2)
        self.assertContains(resp, "above zero")
        self.assertEqual(self.tiers(), [])

    def test_zero_or_missing_wait_is_refused_except_for_administration(self):
        self.add(escalate_to="lead", wait_minutes=0)
        self.add(escalate_to="lead", wait_minutes="")
        self.assertEqual(self.tiers(), [])

    def test_administration_tier_cannot_have_a_wait(self):
        resp = self.add(escalate_to="administration", wait_minutes=5)
        self.assertContains(resp, "Leave the wait empty")
        self.assertEqual(self.tiers(), [])

    def test_named_solver_must_be_on_the_team(self):
        resp = self.add(escalate_to="user", escalate_to_user=self.outsider.pk, wait_minutes=5)
        self.assertEqual(self.tiers(), [])
        self.add(escalate_to="user", escalate_to_user=self.tim.pk, wait_minutes=5)
        self.assertEqual(self.team.escalation_tiers.get().escalate_to_user, self.tim)

    def test_named_solver_tier_needs_a_person(self):
        resp = self.add(escalate_to="user", wait_minutes=5)
        self.assertContains(resp, "Pick the person")

    def test_nothing_comes_after_administration(self):
        self.add(escalate_to="administration", wait_minutes="")
        resp = self.add(escalate_to="lead", wait_minutes=5, follow=False)
        self.assertContains(resp, "administration tier is the last one")
        self.assertEqual(len(self.tiers()), 1)

    def test_removing_a_tier_renumbers_the_rest(self):
        self.add(escalate_to="on_call", wait_minutes=5)
        self.add(escalate_to="lead", wait_minutes=10)
        self.add(escalate_to="administration", wait_minutes="")
        first = self.team.escalation_tiers.get(tier_number=1)
        self.client.post(self.url, {"action": "remove", "tier": first.pk})
        self.assertEqual(self.tiers(), [(1, "lead", 10), (2, "administration", None)])

    def test_only_the_lead_gets_in(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        resp = self.add(escalate_to="on_call", wait_minutes=5)
        self.assertEqual(self.tiers(), [])

    def test_each_team_has_its_own_policy(self):
        self.add(escalate_to="on_call", wait_minutes=5)
        self.assertEqual(EscalationTier.objects.filter(team=self.other).count(), 0)

    def test_page_shows_the_tiers_and_links_from_the_schedule(self):
        self.add(escalate_to="user", escalate_to_user=self.tim.pk, wait_minutes=7)
        resp = self.client.get(self.url)
        self.assertContains(resp, "Tim Diaz")
        self.assertContains(resp, "7 min")
        resp = self.client.get(f"/schedule/{self.team.pk}/")
        self.assertContains(resp, self.url)
