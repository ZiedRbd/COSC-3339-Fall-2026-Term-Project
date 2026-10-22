"""Registration and login."""
from django.test import TestCase

from ops.models import User
from ops.tests.helpers import GOOD_PASSWORD, register, make_user


class RegistrationTests(TestCase):
    """Registration enforces the email and password rules."""

    def test_valid_registration_creates_user_and_redirects_to_login(self):
        """A valid form creates the account and sends the user to log in."""
        response = register(self.client, "new@example.com")
        self.assertRedirects(response, "/login/")
        self.assertTrue(User.objects.filter(email="new@example.com").exists())

    def test_password_is_hashed_in_database(self):
        """The stored password is a PBKDF2 hash, never the plain text."""
        register(self.client, "new@example.com")
        user = User.objects.get(email="new@example.com")
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertNotEqual(user.password, GOOD_PASSWORD)

    def test_password_rules_are_enforced(self):
        """Each missing rule, length, upper, lower, digit, symbol, blocks registration."""
        bad_passwords = {
            "too short": "Sh0rt!A",
            "no uppercase": "nouppercase1!",
            "no lowercase": "NOLOWERCASE1!",
            "no number": "NoNumbers!!",
            "no symbol": "NoSymbol11",
        }
        for reason, password in bad_passwords.items():
            register(self.client, "new@example.com", password)
            self.assertFalse(
                User.objects.filter(email="new@example.com").exists(),
                f"account was created with a password that has {reason}",
            )

    def test_mismatched_confirmation_is_rejected(self):
        """Password and confirmation must match."""
        register(self.client, "new@example.com", GOOD_PASSWORD, "Other!Pass1")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_invalid_email_format_is_rejected(self):
        """A string that is not shaped like an email is rejected."""
        register(self.client, "not-an-email")
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_email_is_rejected(self):
        """The same email cannot register twice."""
        register(self.client, "new@example.com")
        register(self.client, "new@example.com")
        self.assertEqual(User.objects.filter(email="new@example.com").count(), 1)

    def test_email_is_stored_lowercase(self):
        """Emails are saved lowercase regardless of how they were typed."""
        register(self.client, "New@Example.COM")
        self.assertTrue(User.objects.filter(email="new@example.com").exists())

    def test_duplicate_email_rejected_regardless_of_case(self):
        """Changing the capitalization does not get around the duplicate check."""
        register(self.client, "new@example.com")
        register(self.client, "NEW@EXAMPLE.COM")
        self.assertEqual(User.objects.count(), 1)

    def test_names_need_at_least_two_characters(self):
        """A one character first or last name is rejected."""
        for field in ["first_name", "last_name"]:
            self.client.post("/register/", {
                "first_name": "A" if field == "first_name" else "Test",
                "last_name": "B" if field == "last_name" else "User",
                "email": "new@example.com",
                "password": GOOD_PASSWORD,
                "password2": GOOD_PASSWORD,
            })
            self.assertFalse(
                User.objects.filter(email="new@example.com").exists(),
                f"account was created with a one character {field}",
            )

    def test_password_rules_are_shown_on_the_page(self):
        """The registration page tells the user what the password needs."""
        html = self.client.get("/register/").content.decode()
        for rule in ["8 characters", "uppercase", "lowercase", "number", "symbol"]:
            self.assertIn(rule, html)


class LoginTests(TestCase):
    """Login checks credentials and sends users to the incident list."""

    def setUp(self):
        make_user()

    def test_successful_login_redirects_to_incident_list(self):
        """Correct credentials land on the incident list, as the sprint requires."""
        response = self.client.post("/login/", {
            "email": "user@example.com", "password": GOOD_PASSWORD,
        })
        self.assertRedirects(response, "/incidents/list", target_status_code=302)

    def test_login_works_with_different_email_case(self):
        """Login is not case sensitive on the email."""
        response = self.client.post("/login/", {
            "email": "USER@Example.COM", "password": GOOD_PASSWORD,
        })
        self.assertRedirects(response, "/incidents/list", target_status_code=302)

    def test_wrong_password_shows_error(self):
        """A bad password returns to the login page with an error message."""
        response = self.client.post("/login/", {
            "email": "user@example.com", "password": "wrong",
        }, follow=True)
        self.assertIn(b"Invalid email or password", response.content)

    def test_logout_ends_session(self):
        """After logging out, incident pages are locked again."""
        self.client.login(username="user@example.com", password=GOOD_PASSWORD)
        self.client.post("/logout/")
        response = self.client.get("/incidents/list")
        self.assertEqual(response.status_code, 302)
