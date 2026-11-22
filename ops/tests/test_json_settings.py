"""config/settings.json: it is checked as it is read, and the code and the pages use what it holds."""
import copy
import json
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from ops import buildings, console, forms, notifications, scheduling, timeline
from ops.json_settings import (EXPECTED, SETTINGS, SETTINGS_FILE, load, password_rules_sentence, picture_format_names,
                               problems_in)
from ops.tests.helpers import Campus


class TheFileTests(SimpleTestCase):
    def changed(self, section, name, value):
        settings = copy.deepcopy(SETTINGS)
        settings[section][name] = value
        return problems_in(settings)

    def test_the_file_in_the_repository_is_right(self):
        self.assertEqual(problems_in(json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))), [])

    def test_the_file_holds_exactly_the_settings_the_code_expects(self):
        self.assertEqual({section: sorted(held) for section, held in SETTINGS.items()},
                         {section: sorted(expected) for section, expected in EXPECTED.items()})

    def test_a_missing_setting_is_named(self):
        settings = copy.deepcopy(SETTINGS)
        del settings["tickets"]["max_tickets_a_solver_can_hold"]
        self.assertEqual(problems_in(settings), ['"tickets" is missing the setting "max_tickets_a_solver_can_hold"'])

    def test_a_missing_section_is_named(self):
        settings = copy.deepcopy(SETTINGS)
        del settings["auditor"]
        self.assertEqual(problems_in(settings), ['the section "auditor" is missing'])

    def test_a_misspelt_setting_is_caught(self):
        settings = copy.deepcopy(SETTINGS)
        settings["tickets"]["max_tikets"] = 4
        settings["tickts"] = {}
        self.assertEqual(problems_in(settings), [
            '"tickets" has a setting nobody reads: "max_tikets". Check its spelling.',
            'there is a section nobody reads: "tickts". Check its spelling.',
        ])

    def test_a_value_of_the_wrong_kind_or_out_of_range_is_refused(self):
        cases = [
            ("tickets", "max_tickets_a_solver_can_hold", "3", "must be a whole number from 1 to 50"),
            ("tickets", "max_tickets_a_solver_can_hold", 0, "must be a whole number from 1 to 50"),
            ("tickets", "max_tickets_a_solver_can_hold", True, "must be a whole number from 1 to 50"),
            ("tickets", "title_max_characters", 201, "must be a whole number from 10 to 200"),
            ("tickets", "escalation_wait_multiplier_by_severity", {"critical": 0.5},
             "must have exactly these four: low, medium, high, critical"),
            ("tickets", "escalation_wait_multiplier_by_severity", {"low": 2, "medium": 1, "high": 0.75, "critical": 0},
             "critical must be a number from 0.1 to 10"),
            ("accounts", "password_needs_a_symbol", "yes", "must be true or false"),
            ("accounts", "profile_picture_formats", ["GIF"], "must be a list with at least one of: JPEG, PNG, WEBP"),
            ("email_server", "host", "", "must be text that is not empty"),
            ("site", "time_zone", "Texas", "must be a time zone name such as America/Chicago"),
            ("building_search", "words_that_describe_a_place_inside_a_building", "room", "must be a list of words"),
        ]
        for section, name, value, sentence in cases:
            with self.subTest(setting=name, value=value):
                self.assertEqual(self.changed(section, name, value), [f'"{section}" / "{name}" {sentence}'])

    def test_a_lowest_value_cannot_be_above_its_highest(self):
        settings = copy.deepcopy(SETTINGS)
        settings["override_and_removal"].update(reason_min_characters=100, reason_max_characters=50)
        self.assertEqual(problems_in(settings), [
            '"override_and_removal" / "reason_min_characters" cannot be larger than '
            '"override_and_removal" / "reason_max_characters"'])
        self.assertEqual(self.changed("escalation_policy", "tier_wait_max_minutes", 4), [
            '"escalation_policy" / "new_team_minutes_for_the_on_call_solver" cannot be larger than '
            '"escalation_policy" / "tier_wait_max_minutes"',
            '"escalation_policy" / "new_team_minutes_for_the_team_lead" cannot be larger than '
            '"escalation_policy" / "tier_wait_max_minutes"',
        ])

    def test_a_bad_file_stops_the_server_with_every_problem_listed(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "none.json"
            with self.assertRaisesMessage(ImproperlyConfigured, "The settings file is missing"):
                load(missing)
            broken = Path(folder) / "broken.json"
            broken.write_text("{ not json", encoding="utf-8")
            with self.assertRaisesMessage(ImproperlyConfigured, "is not valid JSON"):
                load(broken)
            wrong = copy.deepcopy(SETTINGS)
            wrong["tickets"]["max_tickets_a_solver_can_hold"] = 0
            wrong["site"]["time_zone"] = "Texas"
            two_wrong = Path(folder) / "wrong.json"
            two_wrong.write_text(json.dumps(wrong), encoding="utf-8")
            with self.assertRaisesMessage(ImproperlyConfigured, "has 2 problems"):
                load(two_wrong)

    def test_no_text_in_the_file_has_parentheses(self):
        def texts(value):
            if isinstance(value, dict):
                return [text for held in value.values() for text in texts(held)]
            if isinstance(value, list):
                return [text for held in value for text in texts(held)]
            return [value] if isinstance(value, str) else []
        for text in texts(SETTINGS):
            self.assertNotRegex(text, r"[()]")


class TheCodeReadsTheFileTests(SimpleTestCase):
    def test_every_rule_in_the_code_is_the_value_in_the_file(self):
        tickets, schedule, accounts = SETTINGS["tickets"], SETTINGS["on_call_schedule"], SETTINGS["accounts"]
        self.assertEqual(scheduling.MAX_ACTIVE_TICKETS, tickets["max_tickets_a_solver_can_hold"])
        self.assertEqual(scheduling.SEVERITY_FACTOR, tickets["escalation_wait_multiplier_by_severity"])
        self.assertEqual(scheduling.MAX_SHIFT.total_seconds(), schedule["primary_shift_max_hours"] * 3600)
        self.assertEqual(scheduling.MAX_SECONDARY_SHIFT.total_seconds(), schedule["secondary_shift_max_hours"] * 3600)
        self.assertEqual(scheduling.SECONDARY_BREAK.total_seconds(), schedule["rest_hours_between_secondary_shifts"] * 3600)
        self.assertEqual((timeline.MIN_REASON, timeline.MAX_REASON),
                         (SETTINGS["override_and_removal"]["reason_min_characters"],
                          SETTINGS["override_and_removal"]["reason_max_characters"]))
        self.assertEqual(forms.MAX_TIER_WAIT, SETTINGS["escalation_policy"]["tier_wait_max_minutes"])
        self.assertEqual(forms.MAX_AVATAR_BYTES, accounts["profile_picture_max_megabytes"] * 1024 * 1024)
        self.assertEqual(sorted(forms.AVATAR_FORMATS), sorted(accounts["profile_picture_formats"]))
        self.assertEqual(console.NEWEST_TICKETS, SETTINGS["administrator_console"]["newest_tickets_shown"])
        self.assertEqual(notifications.MAIL_PAUSE.total_seconds(),
                         SETTINGS["notifications"]["minutes_email_is_paused_after_a_failure"] * 60)
        self.assertEqual(buildings.DETAIL_WORDS,
                         set(SETTINGS["building_search"]["words_that_describe_a_place_inside_a_building"]))

    def test_the_forms_take_their_limits_from_the_file(self):
        accounts, tickets = SETTINGS["accounts"], SETTINGS["tickets"]
        register = forms.RegisterForm()
        self.assertEqual((register.fields["first_name"].min_length, register.fields["first_name"].max_length),
                         (accounts["name_min_characters"], accounts["name_max_characters"]))
        self.assertEqual(register.fields["password"].min_length, accounts["password_min_characters"])
        self.assertEqual(forms.IncidentForm.base_fields["title"].max_length, tickets["title_max_characters"])
        self.assertEqual(forms.IncidentForm.base_fields["room"].max_length, tickets["room_max_characters"])
        self.assertEqual(dict(forms.IncidentForm.base_fields["priority"].choices[1:]),
                         tickets["severity_descriptions_on_the_ticket_form"])

    def test_sentences_built_from_the_file(self):
        self.assertEqual(password_rules_sentence(),
                         "At least 8 characters, with an uppercase letter, a lowercase letter, a number and a symbol.")
        self.assertEqual(picture_format_names(), "JPEG, PNG or WebP")


class ThePagesShowTheFileTests(Campus):
    def test_the_reason_boxes_carry_the_limits(self):
        self.client.force_login(self.admin)
        ticket = self.ticket()
        limits = SETTINGS["override_and_removal"]
        for address in (f"/console/tickets/{ticket.pk}/override/", f"/console/tickets/{ticket.pk}/remove/"):
            page = self.client.get(address)
            self.assertContains(page, f'minlength="{limits["reason_min_characters"]}" '
                                      f'maxlength="{limits["reason_max_characters"]}"')
            self.assertContains(page, f"Required, at least {limits['reason_min_characters']} characters.")

    def test_the_register_page_lists_the_password_rules(self):
        page = self.client.get("/register/")
        self.assertContains(page, f'data-min-length="{SETTINGS["accounts"]["password_min_characters"]}"')
        self.assertContains(page, f"At least {SETTINGS['accounts']['password_min_characters']} characters")
        for rule in ("upper", "lower", "digit", "symbol"):
            self.assertContains(page, f'data-rule="{rule}"')

    def test_the_comment_box_carries_its_limit(self):
        self.client.force_login(self.reporter)
        ticket = self.ticket()
        self.assertContains(self.client.get(f"/incidents/{ticket.pk}/"),
                            f'maxlength="{SETTINGS["tickets"]["comment_max_characters"]}"')
