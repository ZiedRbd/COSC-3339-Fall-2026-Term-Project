"""
Every function that reads config/settings.json, tried with the value in
the file and then with a different one, to show it follows the setting
and not a number left behind in the code.
"""
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.test import SimpleTestCase
from django.utils import timezone

from ops import buildings, console, forms, notifications, overrides, removal, scheduling, views
from ops.console_forms import UserForm
from ops.json_settings import (SETTINGS, number, one_of, password_rules_sentence, picture_format_names, whole_number,
                               yes_or_no)
from ops.models import Building, EscalationTier, Incident, IncidentUpdate, Notification, Shift, Team
from ops.notifications import notify
from ops.overrides import override, override_warnings
from ops.removal import remove_ticket
from ops.scheduling import assign_now, ensure_policy, escalate_due, reassign, validate_schedule, validate_secondary
from ops.tests.helpers import GOOD_PASSWORD, Campus


def setting(section, **values):
    """The file's settings with these values changed, for the length of a with block."""
    return mock.patch.dict(SETTINGS[section], values)


class OnCall(Campus):
    def on_call(self, solver, role="primary"):
        now = timezone.now()
        return Shift.objects.create(team=self.team, solver=solver, created_by=self.lead, on_call_role=role,
                                    starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def file(self, count):
        """File this many tickets one after the other. Returns who each one went to."""
        return [assign_now(self.ticket(f"Ticket {number}"), self.reporter) for number in range(count)]

    def queued(self):
        return list(Notification.objects.filter(event="queued").order_by("id"))


# ── The checks on one value ───────────────────────────────────────────


class CheckTests(SimpleTestCase):
    def test_a_whole_number_must_be_whole_and_inside_its_range(self):
        check = whole_number(1, 50)
        for right in (1, 3, 50):
            self.assertIsNone(check(right), right)
        for wrong in (0, 51, -3, 2.0, 2.5, "3", True, None, [3]):
            self.assertEqual(check(wrong), "must be a whole number from 1 to 50", wrong)

    def test_a_number_may_have_a_fraction_and_must_be_inside_its_range(self):
        check = number(0.1, 10)
        for right in (0.1, 0.5, 1, 10):
            self.assertIsNone(check(right), right)
        for wrong in (0, 0.05, 10.5, "1", True, None):
            self.assertEqual(check(wrong), "must be a number from 0.1 to 10", wrong)

    def test_yes_or_no_takes_only_true_and_false(self):
        self.assertIsNone(yes_or_no(True))
        self.assertIsNone(yes_or_no(False))
        for wrong in (1, 0, "true", None):
            self.assertEqual(yes_or_no(wrong), "must be true or false", wrong)

    def test_a_list_reads_as_a_sentence(self):
        self.assertEqual(one_of(["JPEG"]), "JPEG")
        self.assertEqual(one_of(["JPEG", "PNG"]), "JPEG or PNG")
        self.assertEqual(one_of(["JPEG", "PNG", "WebP"]), "JPEG, PNG or WebP")

    def test_the_picture_formats_sentence_follows_the_setting(self):
        with setting("accounts", profile_picture_formats=["PNG"]):
            self.assertEqual(picture_format_names(), "PNG")
        with setting("accounts", profile_picture_formats=["JPEG", "WEBP"]):
            self.assertEqual(picture_format_names(), "JPEG or WebP")

    def test_the_password_sentence_follows_the_setting(self):
        off = dict(password_needs_an_uppercase_letter=False, password_needs_a_lowercase_letter=False,
                   password_needs_a_number=False, password_needs_a_symbol=False)
        with setting("accounts", **off):
            self.assertEqual(password_rules_sentence(), "At least 8 characters.")
        with setting("accounts", **{**off, "password_needs_a_number": True}):
            self.assertEqual(password_rules_sentence(), "At least 8 characters, with a number.")
        with setting("accounts", **{**off, "password_needs_an_uppercase_letter": True, "password_needs_a_symbol": True,
                                    "password_min_characters": 12}):
            self.assertEqual(password_rules_sentence(), "At least 12 characters, with an uppercase letter and a symbol.")


# ── tickets ───────────────────────────────────────────────────────────


class TicketCapTests(OnCall):
    def setUp(self):
        super().setUp()
        self.on_call(self.ann)
        self.on_call(self.bob, "secondary")

    def test_with_the_value_in_the_file_each_solver_takes_three(self):
        self.assertEqual(self.file(7), [self.ann] * 3 + [self.bob] * 3 + [None])
        self.assertIn("everyone on call for Plumbing holds 3 tickets.", self.queued()[0].message)

    def test_with_a_cap_of_two_each_solver_takes_two(self):
        with mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 2):
            self.assertEqual(self.file(5), [self.ann] * 2 + [self.bob] * 2 + [None])
        self.assertIn("everyone on call for Plumbing holds 2 tickets.", self.queued()[0].message)

    def test_with_a_cap_of_one_the_sentences_say_one_ticket(self):
        with mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 1):
            self.assertEqual(self.file(3), [self.ann, self.bob, None])
            bobs = Incident.objects.get(assigned_to=self.bob)
            self.assertEqual(reassign(bobs, self.ann, self.lead), "Ann Ames already holds 1 ticket")
        self.assertIn("everyone on call for Plumbing holds 1 ticket.", self.queued()[0].message)

    def test_a_reassign_is_refused_at_the_cap_and_allowed_below_it(self):
        self.file(4)
        bobs = Incident.objects.get(assigned_to=self.bob)
        self.assertEqual(reassign(bobs, self.ann, self.lead), "Ann Ames already holds 3 tickets")
        with mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 4):
            self.assertIsNone(reassign(bobs, self.ann, self.lead))
        bobs.refresh_from_db()
        self.assertEqual(bobs.assigned_to, self.ann)

    def test_an_escalation_passes_over_a_person_who_is_at_the_cap(self):
        self.ticket("The lead's own", assigned_to=self.lead, status="in_progress")
        overdue = timezone.now() - timedelta(minutes=6)
        first = self.ticket("First", assigned_to=self.ann, status="assigned", escalation_timer_started_at=overdue)
        with mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 1):
            escalate_due()
        first.refresh_from_db()
        self.assertEqual((first.status, first.assigned_to, first.is_unassigned_after_escalation), ("open", None, True))
        # With the cap in the file the lead, who holds one, has room
        second = self.ticket("Second", assigned_to=self.ann, status="assigned", escalation_timer_started_at=overdue)
        escalate_due()
        second.refresh_from_db()
        self.assertEqual(second.assigned_to, self.lead)

    def test_an_override_warns_at_the_cap_whatever_the_cap_is(self):
        self.ticket("Ann's", assigned_to=self.ann, status="assigned")
        ticket = self.ticket("Bob's", assigned_to=self.bob, status="assigned")
        self.assertNotIn("already holds", " ".join(override_warnings(ticket, new_solver=self.ann)))
        with mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 1), mock.patch.object(overrides, "MAX_ACTIVE_TICKETS", 1):
            self.assertIn("Ann Ames already holds 1 ticket. This will be number 2.",
                          override_warnings(ticket, new_solver=self.ann))

    def test_the_ticket_page_says_who_is_full(self):
        self.ticket("Ann's", assigned_to=self.ann, status="assigned")
        ticket = self.ticket("Bob's", assigned_to=self.bob, status="assigned")
        self.client.force_login(self.lead)
        with mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 1), mock.patch.object(views, "MAX_ACTIVE_TICKETS", 1):
            page = self.client.get(f"/incidents/{ticket.pk}/")
        self.assertContains(page, "Ann Ames, primary on call, already holds 1 ticket</p>")


class QueueNotificationTests(OnCall):
    """With a cap of one and one solver on call, every ticket after the first has to wait."""

    def setUp(self):
        super().setUp()
        self.on_call(self.ann)
        cap = mock.patch.object(scheduling, "MAX_ACTIVE_TICKETS", 1)
        cap.start()
        self.addCleanup(cap.stop)

    def told(self):
        return [note.user.email for note in self.queued()]

    def test_with_the_value_in_the_file_the_second_waiting_ticket_reaches_the_administrator(self):
        self.file(3)
        self.assertEqual(self.told(), ["lead@x.com", "admin@x.com"])
        self.assertNotIn("waiting for Plumbing", self.queued()[0].message)
        self.assertIn(" 2 tickets are waiting for Plumbing.", self.queued()[1].message)

    def test_set_to_three_the_lead_hears_about_two_and_the_administrator_about_the_third(self):
        with setting("tickets", waiting_ticket_number_that_notifies_the_administrator=3):
            self.file(4)
        self.assertEqual(self.told(), ["lead@x.com", "lead@x.com", "admin@x.com"])
        self.assertIn(" 3 tickets are waiting for Plumbing.", self.queued()[2].message)

    def test_set_to_one_the_administrator_hears_about_the_first_and_it_says_one_ticket(self):
        with setting("tickets", waiting_ticket_number_that_notifies_the_administrator=1):
            self.file(2)
        self.assertEqual(self.told(), ["admin@x.com"])
        self.assertIn(" 1 ticket is waiting for Plumbing.", self.queued()[0].message)


class SeverityMultiplierTests(Campus):
    """Tier 1 of the team waits 5 minutes for a medium ticket."""

    def waited(self, minutes, priority="medium"):
        return self.ticket(f"{priority} for {minutes}", assigned_to=self.ann, status="assigned", priority=priority,
                           escalation_timer_started_at=timezone.now() - timedelta(minutes=minutes))

    def holder(self, ticket):
        ticket.refresh_from_db()
        return ticket.assigned_to

    def test_with_the_values_in_the_file(self):
        critical, high, medium, low = (self.waited(3, "critical"), self.waited(4, "high"), self.waited(4.5),
                                       self.waited(9, "low"))
        late_medium = self.waited(5.5)
        escalate_due()
        # Waits are 2.5, 3.75, 5 and 10 minutes
        self.assertEqual([self.holder(t) for t in (critical, high, medium, low, late_medium)],
                         [self.lead, self.lead, self.ann, self.ann, self.lead])

    def test_a_low_ticket_escalates_after_twice_the_wait(self):
        late_low = self.waited(10.5, "low")
        self.assertEqual(escalate_due(), 1)
        self.assertEqual(self.holder(late_low), self.lead)
        self.assertIn("did not start work within 10 minutes for a low ticket", self.entries(late_low, "escalation")[0])

    def test_a_changed_multiplier_changes_when_a_ticket_escalates(self):
        ticket = self.waited(3)
        self.assertEqual(escalate_due(), 0)
        with mock.patch.dict(scheduling.SEVERITY_FACTOR, {"medium": 0.5}):
            self.assertEqual(escalate_due(), 1)
        self.assertEqual(self.holder(ticket), self.lead)
        self.assertIn("Ann Ames did not start work within 2.5 minutes for a medium ticket",
                      self.entries(ticket, "escalation")[0])

    def test_a_larger_multiplier_makes_a_ticket_wait_longer(self):
        ticket = self.waited(8)
        with mock.patch.dict(scheduling.SEVERITY_FACTOR, {"medium": 2}):
            self.assertEqual(escalate_due(), 0)
        self.assertEqual(escalate_due(), 1)
        self.assertEqual(self.holder(ticket), self.lead)


class CommentAndReportLengthTests(Campus):
    def setUp(self):
        super().setUp()
        self.auditor = self.person("aud@x.com", "Audie", "Tor", "auditor")
        self.incident = self.ticket()

    def comments(self):
        return IncidentUpdate.objects.filter(incident=self.incident, update_type__in=("comment", "note")).count()

    def reports(self):
        return Notification.objects.filter(event="auditor_report").count()

    def test_a_comment_up_to_the_limit_is_kept_and_one_over_is_refused(self):
        self.client.force_login(self.reporter)
        address = f"/incidents/{self.incident.pk}/comment/"
        self.client.post(address, {"body": "x" * 1000})
        self.assertEqual(self.comments(), 1)
        page = self.client.post(address, {"body": "x" * 1001}, follow=True)
        self.assertContains(page, "Comment is too long. The limit is 1000 characters")
        self.assertEqual(self.comments(), 1)

    def test_the_comment_limit_follows_the_setting(self):
        self.client.force_login(self.reporter)
        address = f"/incidents/{self.incident.pk}/comment/"
        with setting("tickets", comment_max_characters=20):
            page = self.client.post(address, {"body": "x" * 21}, follow=True)
            self.assertContains(page, "Comment is too long. The limit is 20 characters")
            self.assertContains(page, 'maxlength="20"')
            self.assertEqual(self.comments(), 0)
            self.client.post(address, {"body": "x" * 20})
        self.assertEqual(self.comments(), 1)

    def test_a_report_up_to_the_limit_is_sent_and_one_over_is_refused(self):
        self.client.force_login(self.auditor)
        address = f"/incidents/{self.incident.pk}/report/"
        self.client.post(address, {"body": "x" * 1000})
        self.assertEqual(self.reports(), 1)
        page = self.client.post(address, {"body": "x" * 1001}, follow=True)
        self.assertContains(page, "Report is too long, please keep report to less than 1000 characters")
        self.assertEqual(self.reports(), 1)

    def test_the_report_limit_follows_the_setting(self):
        self.client.force_login(self.auditor)
        address = f"/incidents/{self.incident.pk}/report/"
        with setting("auditor", report_max_characters=30):
            page = self.client.post(address, {"body": "x" * 31}, follow=True)
            self.assertContains(page, "please keep report to less than 30 characters")
            self.assertContains(page, 'maxlength="30"')
            self.assertEqual(self.reports(), 0)
            self.client.post(address, {"body": "x" * 30})
        self.assertEqual(self.reports(), 1)


class TicketFormTests(Campus):
    def form(self, **changes):
        data = {"title": "Leak", "description": "Water on the floor", "service": self.service.pk, "priority": "low"}
        data.update(changes)
        return forms.IncidentForm(data)

    def test_the_title_and_the_room_stop_at_their_limits(self):
        self.assertTrue(self.form(title="x" * 80, room="x" * 20).is_valid())
        self.assertIn("title", self.form(title="x" * 81).errors)
        self.assertIn("room", self.form(room="x" * 21).errors)

    def test_the_four_severities_carry_the_descriptions_in_the_file(self):
        choices = forms.IncidentForm.base_fields["priority"].choices
        self.assertEqual(choices[0], ("", "Select a severity level"))
        self.assertEqual(choices[1:], [
            ("low", "Low - minor inconvenience, service still works"),
            ("medium", "Medium - partial disruption, a workaround exists"),
            ("high", "High - major disruption, no workaround"),
            ("critical", "Critical - safety hazard or full outage"),
        ])
        for severity in ("low", "medium", "high", "critical"):
            self.assertTrue(self.form(priority=severity).is_valid(), severity)
        self.assertIn("priority", self.form(priority="urgent").errors)
        self.assertIn("priority", self.form(priority="").errors)


# ── escalation_policy ─────────────────────────────────────────────────


class NewTeamPolicyTests(Campus):
    def policy_of(self, name):
        team = Team.objects.create(name=name, lead=self.lead)
        ensure_policy(team)
        return list(team.escalation_tiers.order_by("tier_number").values_list("tier_number", "escalate_to", "wait_minutes"))

    def test_a_new_team_gets_the_waits_in_the_file(self):
        self.assertEqual(self.policy_of("Electrical"), [(1, "on_call", 5), (2, "lead", 10)])

    def test_a_new_team_follows_changed_waits(self):
        with setting("escalation_policy", new_team_minutes_for_the_on_call_solver=7, new_team_minutes_for_the_team_lead=20):
            self.assertEqual(self.policy_of("Grounds"), [(1, "on_call", 7), (2, "lead", 20)])

    def test_a_team_that_has_a_policy_keeps_it(self):
        with setting("escalation_policy", new_team_minutes_for_the_on_call_solver=7):
            ensure_policy(self.team)
        self.assertEqual(list(self.team.escalation_tiers.values_list("wait_minutes", flat=True)), [5, 10])

    def test_the_longest_wait_of_a_tier_is_the_one_in_the_file(self):
        wait = forms.EscalationTierForm.base_fields["wait_minutes"]
        self.assertEqual((wait.min_value, wait.max_value), (1, 1440))
        self.assertEqual(forms.WAIT_ERROR, "Wait must be a whole number of minutes above zero, and at most 1440")
        self.client.force_login(self.lead)
        tier = self.team.escalation_tiers.get(tier_number=1)
        address = f"/policy/{self.team.pk}/"
        self.assertContains(self.client.post(address, {"action": "save", "tier": tier.pk, "wait_minutes": 1441}, follow=True),
                            forms.WAIT_ERROR)
        tier.refresh_from_db()
        self.assertEqual(tier.wait_minutes, 5)


# ── on_call_schedule ──────────────────────────────────────────────────


class ShiftLengthTests(Campus):
    def shift(self, hours, starts_in=1, role="primary", solver=None):
        start = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=starts_in)
        return Shift(team=self.team, solver=solver or self.ann, created_by=self.lead, on_call_role=role,
                     starts_at=start, ends_at=start + timedelta(hours=hours))

    def too_long(self, problems):
        return [problem.split(" is longer than ")[1] for problem in problems if " is longer than " in problem]

    def breaks(self, problems):
        return [problem.split(":")[0] for problem in problems if "break between secondary shifts" in problem]

    def test_a_primary_shift_with_the_value_in_the_file(self):
        self.assertEqual(self.too_long(validate_schedule(self.team, [self.shift(12)])), [])
        self.assertEqual(self.too_long(validate_schedule(self.team, [self.shift(13)])), ["12 hours"])

    def test_a_primary_shift_follows_a_changed_limit(self):
        with mock.patch.object(scheduling, "MAX_SHIFT", timedelta(hours=6)):
            self.assertEqual(self.too_long(validate_schedule(self.team, [self.shift(6)])), [])
            self.assertEqual(self.too_long(validate_schedule(self.team, [self.shift(8)])), ["6 hours"])
        with mock.patch.object(scheduling, "MAX_SHIFT", timedelta(hours=1)):
            self.assertEqual(self.too_long(validate_schedule(self.team, [self.shift(2)])), ["1 hour"])

    def test_a_secondary_shift_with_the_value_in_the_file(self):
        self.assertEqual(self.too_long(validate_secondary(self.team, [self.shift(24, role="secondary")])), [])
        self.assertEqual(self.too_long(validate_secondary(self.team, [self.shift(25, role="secondary")])), ["24 hours"])

    def test_a_secondary_shift_follows_a_changed_limit(self):
        with mock.patch.object(scheduling, "MAX_SECONDARY_SHIFT", timedelta(hours=10)):
            self.assertEqual(self.too_long(validate_secondary(self.team, [self.shift(12, role="secondary")])), ["10 hours"])

    def test_the_rest_between_secondary_shifts(self):
        # Ann's second shift starts 10 hours after her first one ends
        shifts = [self.shift(4, starts_in=1, role="secondary"), self.shift(4, starts_in=15, role="secondary")]
        self.assertEqual(set(self.breaks(validate_secondary(self.team, shifts))),
                         {"Ann Ames needs a 24 hour break between secondary shifts"})
        with mock.patch.object(scheduling, "SECONDARY_BREAK", timedelta(hours=12)):
            self.assertEqual(set(self.breaks(validate_secondary(self.team, shifts))),
                             {"Ann Ames needs a 12 hour break between secondary shifts"})
        with mock.patch.object(scheduling, "SECONDARY_BREAK", timedelta(hours=8)):
            self.assertEqual(self.breaks(validate_secondary(self.team, shifts)), [])

    def test_the_schedule_page_states_the_limits(self):
        self.client.force_login(self.lead)
        address = f"/schedule/{self.team.pk}/"
        page = self.client.get(address)
        self.assertContains(page, "A primary shift is at most 12 hours, and nobody takes two in a row.")
        self.assertContains(page, "A secondary shift is at most 24 hours, and a person rests 24 hours between two of them.")
        self.assertContains(page, "takes tickets once the primary holds 3.")
        with setting("on_call_schedule", primary_shift_max_hours=1, secondary_shift_max_hours=36,
                     rest_hours_between_secondary_shifts=1), setting("tickets", max_tickets_a_solver_can_hold=5):
            page = self.client.get(address)
        self.assertContains(page, "A primary shift is at most 1 hour, and nobody takes two in a row.")
        self.assertContains(page, "A secondary shift is at most 36 hours, and a person rests 1 hour between two of them.")
        self.assertContains(page, "takes tickets once the primary holds 5.")


# ── override_and_removal ──────────────────────────────────────────────


class ReasonLengthTests(Campus):
    def closed_by_override(self, reason):
        return override(self.ticket(), self.admin, reason, new_status="closed")

    def removed(self, reason):
        return remove_ticket(self.ticket(), self.admin, reason)

    def test_with_the_values_in_the_file(self):
        for act in (self.closed_by_override, self.removed):
            with self.subTest(act=act.__name__):
                self.assertEqual(act("abcd").messages, ["The reason needs at least 5 characters"])
                self.assertTrue(act("abcde").ok)
                self.assertTrue(act("x" * 500).ok)
                self.assertEqual(act("x" * 501).messages, ["The reason can be at most 500 characters"])

    def test_spaces_do_not_count_towards_the_shortest_reason(self):
        self.assertEqual(self.closed_by_override("  a    b  ").messages, ["The reason needs at least 5 characters"])

    def test_changed_limits_are_followed(self):
        for module, act in ((overrides, self.closed_by_override), (removal, self.removed)):
            with self.subTest(act=act.__name__), mock.patch.object(module, "MIN_REASON", 10), \
                    mock.patch.object(module, "MAX_REASON", 20):
                self.assertEqual(act("123456789").messages, ["The reason needs at least 10 characters"])
                self.assertTrue(act("1234567890").ok)
                self.assertTrue(act("x" * 20).ok)
                self.assertEqual(act("x" * 21).messages, ["The reason can be at most 20 characters"])

    def test_the_dialog_does_not_warn_before_the_reason_is_long_enough(self):
        self.client.force_login(self.admin)
        ticket = self.ticket(assigned_to=self.ann, status="in_progress")
        address = f"/console/tickets/{ticket.pk}/override/"
        page = self.client.post(address, {"new_status": "closed", "new_solver": "", "reason": "abcd"})
        self.assertContains(page, "The reason needs at least 5 characters")
        self.assertNotContains(page, "Override anyway")
        page = self.client.post(address, {"new_status": "closed", "new_solver": "", "reason": "abcde"})
        self.assertContains(page, "Override anyway")


# ── accounts ──────────────────────────────────────────────────────────


class AccountRuleTests(Campus):
    def register(self, **changes):
        data = {"first_name": "Test", "last_name": "User", "email": "new@x.com", "password": GOOD_PASSWORD,
                "password2": GOOD_PASSWORD}
        data.update(changes)
        return forms.RegisterForm(data)

    def with_password(self, password):
        return self.register(password=password, password2=password)

    def test_a_name_has_to_fit_between_the_shortest_and_the_longest(self):
        for field in ("first_name", "last_name"):
            self.assertIn(field, self.register(**{field: "A"}).errors)
            self.assertTrue(self.register(**{field: "Al"}).is_valid())
            self.assertTrue(self.register(**{field: "A" * 50}).is_valid())
            self.assertIn(field, self.register(**{field: "A" * 51}).errors)

    def test_a_password_needs_the_length_in_the_file(self):
        self.assertIn("password", self.with_password("Good!P1").errors)
        self.assertTrue(self.with_password("Good!Pa1").is_valid())

    def test_each_password_rule_is_enforced_and_can_be_switched_off(self):
        cases = [
            ("password_needs_an_uppercase_letter", "good!pass1", "Password needs an uppercase letter"),
            ("password_needs_a_lowercase_letter", "GOOD!PASS1", "Password needs a lowercase letter"),
            ("password_needs_a_number", "Good!Pass", "Password needs a number"),
            ("password_needs_a_symbol", "GoodPass1", "Password needs a symbol"),
        ]
        for name, password, sentence in cases:
            with self.subTest(rule=name):
                self.assertEqual(self.with_password(password).errors["password"], [sentence])
                with setting("accounts", **{name: False}):
                    self.assertTrue(self.with_password(password).is_valid())

    def test_registering_on_the_site_follows_a_switched_off_rule(self):
        address, data = "/register/", {"first_name": "Test", "last_name": "User", "email": "plain@x.com",
                                       "password": "GoodPass1", "password2": "GoodPass1"}
        self.assertContains(self.client.post(address, data), "Password needs a symbol")
        with setting("accounts", password_needs_a_symbol=False):
            page = self.client.get(address)
            self.assertNotContains(page, 'data-rule="symbol"')
            self.assertContains(page, 'data-rule="digit"')
            self.assertEqual(self.client.post(address, data).status_code, 302)

    def test_the_console_form_has_the_same_rules(self):
        def console_form(**changes):
            data = {"first_name": "New", "last_name": "Person", "email": "np@x.com", "role": "reporter",
                    "password": GOOD_PASSWORD}
            data.update(changes)
            return UserForm(data)
        self.assertTrue(console_form().is_valid())
        self.assertIn("first_name", console_form(first_name="N").errors)
        self.assertIn("last_name", console_form(last_name="P" * 51).errors)
        self.assertEqual(console_form(password="Good!P1").errors["password"], ["Password needs at least 8 characters"])
        self.assertEqual(console_form(password="GoodPass1").errors["password"], ["Password needs a symbol"])
        self.assertEqual(UserForm().fields["password"].help_text,
                         "At least 8 characters, with an uppercase letter, a lowercase letter, a number and a symbol.")
        with setting("accounts", password_min_characters=12, password_needs_a_symbol=False):
            self.assertEqual(console_form(password="GoodPass1").errors["password"],
                             ["Password needs at least 12 characters"])
            self.assertTrue(console_form(password="GoodPassword1").is_valid())
            self.assertEqual(UserForm().fields["password"].help_text,
                             "At least 12 characters, with an uppercase letter, a lowercase letter and a number.")

    def test_the_profile_page_states_the_picture_rules(self):
        self.client.force_login(self.reporter)
        self.assertContains(self.client.get("/profile/"), "JPEG, PNG or WebP, up to 2 MB.")
        with setting("accounts", profile_picture_max_megabytes=1, profile_picture_formats=["PNG"]):
            self.assertContains(self.client.get("/profile/"), "PNG, up to 1 MB.")


# ── administrator_console and notifications ───────────────────────────


class ConsoleAndBellTests(Campus):
    def test_the_console_lists_only_the_newest_tickets(self):
        now = timezone.now()
        for age, title in enumerate(("Newest one", "Middle one", "Oldest one")):
            ticket = self.ticket(title)
            Incident.objects.filter(pk=ticket.pk).update(created_at=now - timedelta(hours=age))
        self.client.force_login(self.admin)
        page = self.client.get("/console/?tab=tickets")
        for title in ("Newest one", "Middle one", "Oldest one"):
            self.assertContains(page, title)
        self.assertNotContains(page, "newest of")
        with mock.patch.object(console, "NEWEST_TICKETS", 2):
            page = self.client.get("/console/?tab=tickets")
        self.assertContains(page, "Showing the 2 newest of 3")
        self.assertContains(page, "Newest one")
        self.assertContains(page, "Middle one")
        self.assertNotContains(page, "Oldest one")

    def test_the_bell_lists_as_many_as_the_setting_and_counts_them_all(self):
        ticket = self.ticket()
        for number in range(12):
            Notification.objects.create(user=self.reporter, incident=ticket, event="resolved", message=f"Note {number}")
        self.client.force_login(self.reporter)
        context = self.client.get("/profile/").context
        self.assertEqual((context["unread_count"], len(context["unread_notifications"])), (12, 10))
        with setting("notifications", unread_shown_in_the_bell=2):
            context = self.client.get("/profile/").context
        self.assertEqual((context["unread_count"], len(context["unread_notifications"])), (12, 2))


class EmailPauseTests(Campus):
    def setUp(self):
        super().setUp()
        notifications._mail_paused_until = None
        self.addCleanup(setattr, notifications, "_mail_paused_until", None)

    def fail_then_try_again(self):
        """One send that fails, then another notification. Returns how many sends were attempted."""
        with mock.patch.object(notifications, "send_mail", side_effect=OSError("mail server down")) as send, \
                self.assertLogs("ops.notifications", level="ERROR"):
            notify(self.ann, None, "handover", "First")
            notify(self.ann, None, "handover", "Second")
        return send.call_count

    def test_after_a_failure_email_pauses_for_the_minutes_in_the_file(self):
        self.assertEqual(self.fail_then_try_again(), 1)
        pause = notifications._mail_paused_until - timezone.now()
        self.assertTrue(timedelta(minutes=4, seconds=50) < pause <= timedelta(minutes=5), pause)
        # Both notifications are in the bell all the same
        self.assertEqual(Notification.objects.filter(user=self.ann, event="handover").count(), 2)

    def test_the_pause_follows_a_changed_setting(self):
        with mock.patch.object(notifications, "MAIL_PAUSE", timedelta(minutes=30)):
            self.assertEqual(self.fail_then_try_again(), 1)
            pause = notifications._mail_paused_until - timezone.now()
        self.assertTrue(timedelta(minutes=29) < pause <= timedelta(minutes=30), pause)

    def test_with_no_pause_the_next_email_is_tried_at_once(self):
        with mock.patch.object(notifications, "MAIL_PAUSE", timedelta(0)):
            self.assertEqual(self.fail_then_try_again(), 2)


# ── email_server, site and building_search ────────────────────────────


class DjangoSettingsTests(SimpleTestCase):
    def test_the_time_zone_is_the_one_in_the_file(self):
        self.assertEqual(django_settings.TIME_ZONE, SETTINGS["site"]["time_zone"])

    def test_the_email_server_is_the_one_in_the_file(self):
        server, options = SETTINGS["email_server"], django_settings.GMAIL_MAILER["OPTIONS"]
        self.assertEqual((options["host"], options["port"], options["use_tls"], options["timeout"]),
                         (server["host"], server["port"], server["use_tls"], server["timeout_seconds"]))

    def test_every_page_is_given_the_settings(self):
        self.assertIn("ops.context_processors.site_settings",
                      django_settings.TEMPLATES[0]["OPTIONS"]["context_processors"])


class BuildingWordTests(SimpleTestCase):
    def setUp(self):
        self.hall = Building(name="Zeta Hall", aliases="Zeta")

    def test_a_word_in_the_list_is_read_as_a_place_inside_the_building(self):
        self.assertIs(buildings.best_match("Zeta lobby", [self.hall]), self.hall)
        self.assertIs(buildings.best_match("in the Zeta basement near the stairs", [self.hall]), self.hall)

    def test_a_word_that_is_not_in_the_list_makes_the_text_unclear(self):
        self.assertIsNone(buildings.best_match("Zeta rooftop", [self.hall]))

    def test_the_list_follows_the_setting(self):
        with mock.patch.object(buildings, "DETAIL_WORDS", buildings.DETAIL_WORDS | {"rooftop"}):
            self.assertIs(buildings.best_match("Zeta rooftop", [self.hall]), self.hall)
        with mock.patch.object(buildings, "DETAIL_WORDS", set()):
            self.assertIsNone(buildings.best_match("Zeta lobby", [self.hall]))
            # A room number is a place whatever the list holds
            self.assertIs(buildings.best_match("Zeta 204", [self.hall]), self.hall)


# ── Sentences on pages that quote a setting ───────────────────────────


class PageSentenceTests(Campus):
    def test_the_calendar_says_how_many_tickets_the_primary_holds(self):
        self.client.force_login(self.ann)
        self.assertContains(self.client.get("/calendar/"), "takes tickets once the primary holds 3.")
        with setting("tickets", max_tickets_a_solver_can_hold=5):
            self.assertContains(self.client.get("/calendar/"), "takes tickets once the primary holds 5.")

    def test_the_policy_page_lists_the_multipliers(self):
        self.client.force_login(self.lead)
        address = f"/policy/{self.team.pk}/"
        self.assertContains(self.client.get(address), "Each wait is multiplied by the severity of the ticket: "
                                                      "critical 0.5, high 0.75, medium 1, low 2.")
        with mock.patch.dict(scheduling.SEVERITY_FACTOR, {"critical": 0.25, "low": 3}):
            self.assertContains(self.client.get(address), "critical 0.25, high 0.75, medium 1, low 3.")

    def test_the_shift_form_says_how_many_tickets_the_primary_holds(self):
        self.assertEqual(forms.ShiftForm.base_fields["on_call_role"].help_text,
                         "Primary is required around the clock. Secondary is optional and takes tickets once the "
                         "primary holds 3.")
