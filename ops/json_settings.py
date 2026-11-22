"""
The settings of the site, read from config/settings.json.

Every number, limit and piece of wording that somebody may want to change
without touching the code lives in that one file. It is read here once,
when the server starts, and kept in memory as SETTINGS. The rest of the
code reads SETTINGS and never opens the file itself, so a change to the
file takes effect at the next restart.

The file is checked as it is read. A setting that is missing, misspelt,
of the wrong kind or out of range stops the server from starting, with a
message that names the setting and says what it must be. Nothing in the
file is secret: passwords and keys stay in .env.
"""
import json
from pathlib import Path
from zoneinfo import available_timezones

from django.core.exceptions import ImproperlyConfigured

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.json"

SEVERITIES = ("low", "medium", "high", "critical")
# What Pillow calls each picture format the site can store, and how the format is written in a sentence
PICTURE_FORMAT_NAMES = {"JPEG": "JPEG", "PNG": "PNG", "WEBP": "WebP"}


# ── What one setting must be. Each returns the sentence saying so, or None when the value is right. ──


def whole_number(lowest, highest):
    def check(value):
        if type(value) is not int or not lowest <= value <= highest:
            return f"must be a whole number from {lowest} to {highest}"
    return check


def number(lowest, highest):
    def check(value):
        if type(value) not in (int, float) or not lowest <= value <= highest:
            return f"must be a number from {lowest} to {highest}"
    return check


def yes_or_no(value):
    if type(value) is not bool:
        return "must be true or false"


def text(value):
    if type(value) is not str or not value.strip():
        return "must be text that is not empty"


def list_of_words(value):
    if type(value) is not list or not all(type(word) is str and word for word in value):
        return "must be a list of words"


def one_for_each_severity(check_one):
    def check(value):
        if type(value) is not dict or set(value) != set(SEVERITIES):
            return f"must have exactly these four: {', '.join(SEVERITIES)}"
        for severity in SEVERITIES:
            problem = check_one(value[severity])
            if problem:
                return f"{severity} {problem}"
    return check


def picture_formats(value):
    known = ", ".join(PICTURE_FORMAT_NAMES)
    if type(value) is not list or not value or not set(value) <= set(PICTURE_FORMAT_NAMES):
        return f"must be a list with at least one of: {known}"


def time_zone(value):
    if value not in available_timezones():
        return "must be a time zone name such as America/Chicago"


# Every section and setting the file must hold, in the order they are written there.
# A highest value that matches a database column is as far as that column goes.
EXPECTED = {
    "tickets": {
        "max_tickets_a_solver_can_hold": whole_number(1, 50),
        "waiting_ticket_number_that_notifies_the_administrator": whole_number(1, 50),
        "escalation_wait_multiplier_by_severity": one_for_each_severity(number(0.1, 10)),
        "title_max_characters": whole_number(10, 200),
        "room_max_characters": whole_number(1, 50),
        "comment_max_characters": whole_number(10, 5000),
        "severity_descriptions_on_the_ticket_form": one_for_each_severity(text),
    },
    "escalation_policy": {
        "new_team_minutes_for_the_on_call_solver": whole_number(1, 10080),
        "new_team_minutes_for_the_team_lead": whole_number(1, 10080),
        "tier_wait_max_minutes": whole_number(1, 10080),
    },
    "on_call_schedule": {
        "primary_shift_max_hours": whole_number(1, 24),
        "secondary_shift_max_hours": whole_number(1, 168),
        "rest_hours_between_secondary_shifts": whole_number(0, 168),
    },
    "override_and_removal": {
        "reason_min_characters": whole_number(1, 100),
        "reason_max_characters": whole_number(10, 5000),
    },
    "auditor": {
        "report_max_characters": whole_number(10, 5000),
    },
    "accounts": {
        "name_min_characters": whole_number(1, 20),
        "name_max_characters": whole_number(2, 150),
        "password_min_characters": whole_number(6, 64),
        "password_needs_an_uppercase_letter": yes_or_no,
        "password_needs_a_lowercase_letter": yes_or_no,
        "password_needs_a_number": yes_or_no,
        "password_needs_a_symbol": yes_or_no,
        "profile_picture_max_megabytes": whole_number(1, 5),
        "profile_picture_formats": picture_formats,
    },
    "administrator_console": {
        "newest_tickets_shown": whole_number(10, 5000),
    },
    "notifications": {
        "unread_shown_in_the_bell": whole_number(1, 100),
        "minutes_email_is_paused_after_a_failure": whole_number(0, 1440),
    },
    "email_server": {
        "host": text,
        "port": whole_number(1, 65535),
        "use_tls": yes_or_no,
        "timeout_seconds": whole_number(1, 60),
    },
    "site": {
        "time_zone": time_zone,
    },
    "building_search": {
        "words_that_describe_a_place_inside_a_building": list_of_words,
    },
}

# Pairs of settings where the first may not be larger than the second
NOT_ABOVE = [
    (("accounts", "name_min_characters"), ("accounts", "name_max_characters")),
    (("override_and_removal", "reason_min_characters"), ("override_and_removal", "reason_max_characters")),
    (("escalation_policy", "new_team_minutes_for_the_on_call_solver"), ("escalation_policy", "tier_wait_max_minutes")),
    (("escalation_policy", "new_team_minutes_for_the_team_lead"), ("escalation_policy", "tier_wait_max_minutes")),
]


def problems_in(settings):
    """Every sentence saying what is wrong with these settings. Empty when they are all right."""
    if type(settings) is not dict:
        return ["the file must hold one object with a section for each group of settings"]
    problems = []
    for section, expected in EXPECTED.items():
        held = settings.get(section)
        if type(held) is not dict:
            problems.append(f'the section "{section}" is missing')
            continue
        for name, check in expected.items():
            if name not in held:
                problems.append(f'"{section}" is missing the setting "{name}"')
                continue
            problem = check(held[name])
            if problem:
                problems.append(f'"{section}" / "{name}" {problem}')
        for name in held:
            if name not in expected:
                problems.append(f'"{section}" has a setting nobody reads: "{name}". Check its spelling.')
    for section in settings:
        if section not in EXPECTED:
            problems.append(f'there is a section nobody reads: "{section}". Check its spelling.')
    if not problems:
        for (low_section, low_name), (high_section, high_name) in NOT_ABOVE:
            if settings[low_section][low_name] > settings[high_section][high_name]:
                problems.append(f'"{low_section}" / "{low_name}" cannot be larger than "{high_section}" / "{high_name}"')
    return problems


def load(path=SETTINGS_FILE):
    """Read and check a settings file. Returns the settings, or refuses with everything that is wrong."""
    try:
        settings = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ImproperlyConfigured(f"The settings file is missing: {path}")
    except json.JSONDecodeError as error:
        raise ImproperlyConfigured(f"The settings file {path} is not valid JSON: {error}")
    problems = problems_in(settings)
    if problems:
        raise ImproperlyConfigured(f"The settings file {path} has {len(problems)} problem"
                                   f"{'' if len(problems) == 1 else 's'}:\n  " + "\n  ".join(problems))
    return settings


SETTINGS = load()


def one_of(names):
    """ "JPEG", "JPEG or PNG", "JPEG, PNG or WebP". """
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def picture_format_names():
    """The accepted profile picture formats as they are written in a sentence."""
    return one_of(PICTURE_FORMAT_NAMES[name] for name in SETTINGS["accounts"]["profile_picture_formats"])


def password_rules():
    """What a password needs, as short phrases in the order the register page lists them."""
    accounts = SETTINGS["accounts"]
    wanted = [
        (accounts["password_needs_an_uppercase_letter"], "an uppercase letter"),
        (accounts["password_needs_a_lowercase_letter"], "a lowercase letter"),
        (accounts["password_needs_a_number"], "a number"),
        (accounts["password_needs_a_symbol"], "a symbol"),
    ]
    return [phrase for needed, phrase in wanted if needed]


def password_rules_sentence():
    """One sentence for a form: "At least 8 characters, with an uppercase letter, ... and a symbol." """
    sentence = f"At least {SETTINGS['accounts']['password_min_characters']} characters"
    phrases = password_rules()
    if phrases:
        sentence += ", with " + (phrases[0] if len(phrases) == 1 else f"{', '.join(phrases[:-1])} and {phrases[-1]}")
    return sentence + "."
