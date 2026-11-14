"""The lead's escalation policy page: tier 1 is the on-call solver, later tiers a role or a person."""
from importlib import import_module

from django.apps import apps
from django.test import TestCase

from ops.models import EscalationTier, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD

WAIT_ERROR = "Wait must be a whole number of minutes above zero"


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
        # Opening the page gives the team its tier 1
        self.client.get(self.url)

    def add(self, target, wait):
        return self.client.post(self.url, {"action": "add", "target": target, "wait_minutes": wait}, follow=True)

    def save(self, number, wait, target=None):
        tier = self.team.escalation_tiers.get(tier_number=number)
        data = {"action": "save", "tier": tier.pk, f"t{tier.pk}-wait_minutes": wait}
        if target:
            data[f"t{tier.pk}-target"] = target
        return self.client.post(self.url, data, follow=True)

    def remove(self, number):
        tier = self.team.escalation_tiers.get(tier_number=number)
        return self.client.post(self.url, {"action": "remove", "tier": tier.pk}, follow=True)

    def tiers(self):
        return [(t.tier_number, t.escalate_to, t.escalate_to_user, t.wait_minutes)
                for t in self.team.escalation_tiers.all()]

    def person(self, user):
        return f"user:{user.pk}"

    # ---- the shape of a policy

    def test_every_team_starts_with_the_on_call_solver_as_tier_one(self):
        self.assertEqual(self.tiers(), [(1, "on_call", None, 5)])
        self.assertContains(self.client.get(self.url), "On-call solver")

    def test_lead_builds_a_policy_with_a_person_and_a_role(self):
        """The example from the spec: on call, then one named teammate, then the team lead."""
        self.add(self.person(self.tim), 5)
        self.add("lead", 10)
        self.assertEqual(self.tiers(), [(1, "on_call", None, 5), (2, "user", self.tim, 5), (3, "lead", None, 10)])

    def test_the_dropdown_offers_the_lead_and_the_teams_solvers_and_nothing_else(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Team lead (Pat Lee)", html)
        self.assertIn("Tim Diaz", html)
        self.assertNotIn("Ola Ng", html)
        self.assertNotIn("dministration", html)
        self.assertNotIn("policy.js", html)

    def test_the_page_says_how_a_policy_ends(self):
        self.assertContains(self.client.get(self.url), "the ticket is marked unassigned")

    def test_each_team_has_its_own_policy(self):
        self.add("lead", 10)
        self.assertEqual(EscalationTier.objects.filter(team=self.other).count(), 0)

    # ---- validation

    def test_a_wait_of_zero_or_less_is_refused(self):
        for wait in (-2, 0):
            resp = self.add("lead", wait)
            self.assertContains(resp, WAIT_ERROR)
        self.assertEqual(len(self.tiers()), 1)

    def test_a_wait_that_is_missing_text_or_a_fraction_is_refused_with_the_same_sentence(self):
        for wait in ("", "abc", "2.5", "1e3"):
            resp = self.add("lead", wait)
            self.assertContains(resp, WAIT_ERROR, count=1)
            self.assertNotContains(resp, "greater than or equal to")
        self.assertEqual(len(self.tiers()), 1)

    def test_a_wait_longer_than_a_day_is_refused(self):
        self.assertContains(self.add("lead", 1441), "at most 1440")
        self.assertContains(self.add("lead", 9223372036854775807), "at most 1440")
        self.add("lead", 1440)
        self.assertEqual(self.tiers()[-1], (2, "lead", None, 1440))

    def test_a_person_from_another_team_is_refused_with_a_clear_sentence(self):
        resp = self.add(self.person(self.outsider), 5)
        self.assertContains(resp, "Pick the team lead or an active solver on this team")
        self.assertNotContains(resp, "Select a valid choice")
        self.assertEqual(len(self.tiers()), 1)

    def test_a_person_who_does_not_exist_a_reporter_and_an_inactive_solver_are_refused(self):
        reporter = User.objects.create_user(username="rep@x.com", email="rep@x.com", password=GOOD_PASSWORD)
        TeamMember.objects.create(user=reporter, team=self.team)
        self.tim.is_active = False
        self.tim.save()
        for target in ("user:99999", self.person(reporter), self.person(self.tim), "administration", "on_call", ""):
            self.assertContains(self.add(target, 5), "Pick the team lead or an active solver")
        self.assertEqual(len(self.tiers()), 1)

    # ---- a policy always has tier 1

    def test_tier_one_cannot_be_removed(self):
        resp = self.remove(1)
        self.assertContains(resp, "a policy needs at least one tier")
        self.assertEqual(self.tiers(), [(1, "on_call", None, 5)])

    def test_tier_one_has_no_remove_button_and_no_dropdown(self):
        tier = self.team.escalation_tiers.get()
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('value="remove"'), 0)
        self.assertNotIn(f't{tier.pk}-target', html)

    def test_tier_one_stays_the_on_call_solver_whatever_is_posted(self):
        self.save(1, 8, target="lead")
        self.assertEqual(self.tiers(), [(1, "on_call", None, 8)])

    # ---- editing in place

    def test_the_wait_of_any_tier_is_changed_in_its_row(self):
        self.add("lead", 10)
        self.assertContains(self.save(1, 3), "Tier 1 saved")
        self.save(2, 20, target="lead")
        self.assertEqual(self.tiers(), [(1, "on_call", None, 3), (2, "lead", None, 20)])

    def test_who_a_later_tier_escalates_to_is_changed_in_its_row(self):
        self.add("lead", 10)
        self.save(2, 10, target=self.person(self.tim))
        self.assertEqual(self.tiers()[1], (2, "user", self.tim, 10))
        self.save(2, 10, target="lead")
        self.assertEqual(self.tiers()[1], (2, "lead", None, 10))

    def test_a_bad_edit_is_refused_and_the_saved_value_stays(self):
        self.assertContains(self.save(1, 0), WAIT_ERROR)
        self.assertEqual(self.tiers(), [(1, "on_call", None, 5)])

    # ---- removing

    def test_removing_a_tier_renumbers_the_rest(self):
        self.add(self.person(self.tim), 5)
        self.add("lead", 10)
        self.remove(2)
        self.assertEqual(self.tiers(), [(1, "on_call", None, 5), (2, "lead", None, 10)])

    def test_a_tier_id_that_is_not_a_number_or_is_another_teams_is_a_404_not_a_crash(self):
        foreign = EscalationTier.objects.create(team=self.other, tier_number=1, escalate_to="on_call", wait_minutes=5)
        for value in ("abc", "", foreign.pk):
            resp = self.client.post(self.url, {"action": "remove", "tier": value})
            self.assertEqual(resp.status_code, 404, value)
        self.assertTrue(EscalationTier.objects.filter(pk=foreign.pk).exists())

    def test_a_get_never_changes_the_policy(self):
        self.add("lead", 10)
        tier = self.team.escalation_tiers.get(tier_number=2)
        self.client.get(self.url, {"action": "remove", "tier": tier.pk})
        self.assertEqual(len(self.tiers()), 2)

    # ---- people who change after the policy was written

    def test_a_named_person_who_was_deactivated_is_flagged_on_the_page(self):
        self.add(self.person(self.tim), 5)
        self.tim.is_active = False
        self.tim.save()
        self.assertContains(self.client.get(self.url), "Tim Diaz (not available, tier is skipped)")

    # ---- who gets in

    def test_only_the_lead_gets_in(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.add("lead", 10)
        self.assertEqual(len(self.tiers()), 1)

    def test_the_schedule_links_to_the_policy(self):
        self.assertContains(self.client.get(f"/schedule/{self.team.pk}/"), self.url)


class PolicyMigrationTests(TestCase):
    """Policies written before the simpler page keep their order and lose what no longer exists."""

    def test_old_policies_are_brought_to_the_new_shape(self):
        migration = import_module("ops.migrations.0010_simpler_escalation_policy")
        full = Team.objects.create(name="Plumbing")
        odd = Team.objects.create(name="Electrical")
        empty = Team.objects.create(name="IT Support")
        tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD, role="solver")
        make = EscalationTier.objects.create
        make(team=full, tier_number=1, escalate_to="on_call", wait_minutes=5)
        make(team=full, tier_number=2, escalate_to="on_call", wait_minutes=4)
        make(team=full, tier_number=3, escalate_to="lead", wait_minutes=12)
        make(team=full, tier_number=4, escalate_to="administration", wait_minutes=1)
        make(team=odd, tier_number=1, escalate_to="user", escalate_to_user=tim, wait_minutes=7)
        make(team=odd, tier_number=2, escalate_to="administration", wait_minutes=1)

        migration.simplify_policies(apps, None)

        def shape(team):
            return [(t.tier_number, t.escalate_to, t.escalate_to_user, t.wait_minutes)
                    for t in team.escalation_tiers.all()]
        self.assertEqual(shape(full), [(1, "on_call", None, 5), (2, "lead", None, 12)])
        self.assertEqual(shape(odd), [(1, "on_call", None, 7)])
        self.assertEqual(shape(empty), [(1, "on_call", None, 5)])
