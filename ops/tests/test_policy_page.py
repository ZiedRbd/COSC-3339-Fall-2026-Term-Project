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
        # Opening the page gives a team with no policy the default one. The
        # tests below start from tier 1 alone.
        self.client.get(self.url)
        self.default = self.tiers()
        self.team.escalation_tiers.filter(tier_number__gt=1).delete()

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

    def test_a_team_with_no_policy_gets_the_default_one(self):
        self.assertEqual(self.default, [(1, "on_call", None, 5), (2, "lead", None, 10)])
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
        # Administration ends every policy by itself, so it is never a choice in the dropdown
        choices = html[html.index('<select name="target"'):html.index("</select>")]
        self.assertNotIn("dministration", choices)
        self.assertNotIn("policy.js", html)

    def test_the_page_says_how_a_policy_ends(self):
        self.assertContains(self.client.get(self.url),
                            "The ticket turns red and unassigned, and you are notified to reassign it.")

    # ---- the Administration checkbox

    def tick(self, on):
        data = {"action": "administration"}
        if on:
            data["administration"] = "on"
        return self.client.post(self.url, data, follow=True)

    def administration(self, team=None):
        return EscalationTier.objects.filter(team=team or self.team, escalate_to="administration")

    def numbers(self):
        return list(self.team.escalation_tiers.values_list("tier_number", "escalate_to"))

    def test_administration_is_off_until_the_lead_ticks_the_box(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn('<input type="checkbox" name="administration">', page)
        self.assertNotIn("<td>Administration</td>", page)
        self.assertFalse(self.administration().exists())

    def test_ticking_the_box_makes_administration_the_last_tier(self):
        page = self.tick(True)
        self.assertContains(page, "Administration is now the last tier of this policy")
        self.assertContains(page, "<td>Administration</td>")
        self.assertContains(page, '<input type="checkbox" name="administration" checked>')
        self.assertEqual(self.numbers(), [(1, "on_call"), (2, "administration")])
        self.tick(True)
        self.assertEqual(self.administration().count(), 1, "ticking it again adds no second row")

    def test_a_tier_added_while_administration_is_ticked_goes_before_it(self):
        self.tick(True)
        self.add("lead", 10)
        self.add(f"user:{self.tim.pk}", 5)
        self.assertEqual(self.numbers(), [(1, "on_call"), (2, "lead"), (3, "user"), (4, "administration")])
        page = self.client.get(self.url)
        self.assertContains(page, "<td>Administration</td>")
        self.assertContains(page, "Add tier 4")

    def test_removing_a_tier_keeps_administration_last(self):
        self.tick(True)
        self.add("lead", 10)
        self.add(f"user:{self.tim.pk}", 5)
        self.remove(2)
        self.assertEqual(self.numbers(), [(1, "on_call"), (2, "user"), (3, "administration")])

    def test_the_administration_row_cannot_be_edited_or_removed_like_a_tier(self):
        self.tick(True)
        row = self.administration().get()
        for action in ("save", "remove"):
            response = self.client.post(self.url, {"action": action, "tier": row.pk, f"t{row.pk}-wait_minutes": 30})
            self.assertEqual(response.status_code, 404, action)
        self.assertEqual(self.administration().get().wait_minutes, row.wait_minutes)
        self.assertNotContains(self.client.get(self.url), f'form="tier-{row.pk}"')

    def test_unticking_the_box_takes_administration_off_again(self):
        self.tick(True)
        page = self.tick(False)
        self.assertContains(page, "Administration is no longer a tier of this policy")
        self.assertNotContains(page, "<td>Administration</td>")
        self.assertFalse(self.administration().exists())
        self.assertEqual(self.numbers(), [(1, "on_call")])

    def test_the_box_belongs_to_one_team(self):
        self.tick(True)
        self.assertFalse(self.administration(self.other).exists())

    def test_only_the_lead_can_tick_the_box(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.tick(True)
        self.assertFalse(self.administration().exists())

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

    def test_only_plain_digits_are_a_whole_number(self):
        for wait in ("1_0", "+5", "5.0", "\uff15"):
            self.assertContains(self.add("lead", wait), WAIT_ERROR, count=1, msg_prefix=repr(wait))
        self.assertEqual(len(self.tiers()), 1)
        self.add("lead", " 007 ")
        self.assertEqual(self.tiers()[-1], (2, "lead", None, 7))

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

    def test_a_post_with_no_action_or_an_unknown_one_changes_nothing(self):
        for action in (None, "", "delete-everything"):
            data = {"target": "lead", "wait_minutes": 5}
            if action is not None:
                data["action"] = action
            self.client.post(self.url, data)
        self.assertEqual(len(self.tiers()), 1)

    def test_a_new_tier_takes_the_number_after_the_last_one_even_across_a_gap(self):
        EscalationTier.objects.create(team=self.team, tier_number=5, escalate_to="lead", wait_minutes=10)
        self.add(self.person(self.tim), 5)
        self.assertEqual([t[0] for t in self.tiers()], [1, 5, 6])

    def test_a_row_the_page_could_not_have_made_still_renders(self):
        """A later tier saved as on-call, or as a person with nobody named, shows with nothing chosen."""
        EscalationTier.objects.create(team=self.team, tier_number=2, escalate_to="on_call", wait_minutes=5)
        EscalationTier.objects.create(team=self.team, tier_number=3, escalate_to="user", wait_minutes=5)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_removing_a_tier_keeps_waiting_tickets_in_their_place(self):
        """
        On call, Tim, the lead. One ticket is with Tim and one with the lead when Tim's tier is
        removed. Tim's ticket must still go to the lead next, and the lead's must still be the last step.
        """
        from datetime import timedelta
        from django.utils import timezone
        from ops.models import Incident, Service
        from ops.scheduling import escalate_due
        self.add(self.person(self.tim), 5)
        self.add("lead", 10)
        service = Service.objects.create(name="Pipes", owning_team=self.team)
        now = timezone.now()

        def ticket(holder, level):
            return Incident.objects.create(
                title="Leak", description="d", service=service, reported_by=self.outsider, assigned_team=self.team,
                assigned_to=holder, status="assigned", escalation_level=level, escalation_timer_started_at=now)
        with_tim, with_lead = ticket(self.tim, 1), ticket(self.lead, 2)
        self.remove(2)
        with_tim.refresh_from_db()
        with_lead.refresh_from_db()
        self.assertEqual((with_tim.escalation_level, with_lead.escalation_level), (0, 1))
        escalate_due(now + timedelta(minutes=5))
        with_tim.refresh_from_db()
        with_lead.refresh_from_db()
        self.assertEqual(with_tim.assigned_to, self.lead)
        self.assertEqual((with_lead.assigned_to, with_lead.status), (self.lead, "assigned"))
        escalate_due(now + timedelta(minutes=10))
        with_lead.refresh_from_db()
        self.assertTrue(with_lead.is_unassigned_after_escalation)

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
        self.assertEqual(shape(empty), [(1, "on_call", None, 5), (2, "lead", None, 10)])

    def test_the_rows_and_the_columns_change_in_separate_migrations(self):
        """PostgreSQL refuses to alter a table in the transaction that edited its rows."""
        data = import_module("ops.migrations.0010_simpler_escalation_policy").Migration
        schema = import_module("ops.migrations.0011_tier_fields_for_simpler_policy").Migration
        self.assertEqual([type(op).__name__ for op in data.operations], ["RunPython"])
        self.assertEqual({type(op).__name__ for op in schema.operations}, {"AlterField"})
