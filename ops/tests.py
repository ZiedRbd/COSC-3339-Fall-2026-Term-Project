from django.test import TestCase

from .models import Incident, Service, Team, User


# Run with: python manage.py test ops
# Each test gets a fresh empty database. self.client acts as a browser.

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


class PageTests(TestCase):
    """Every public page loads and the nav links are present."""

    def test_public_pages_load(self):
        """Home, services, login, and register all return 200."""
        for path in ["/", "/services/", "/login/", "/register/"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_nav_links_on_every_page(self):
        """The shared nav bar with home, services, and incidents links is on every page."""
        for path in ["/", "/services/", "/login/", "/register/"]:
            html = self.client.get(path).content.decode()
            for link in ['href="/"', "/services/", "/incidents/"]:
                self.assertIn(link, html, f"{link} missing on {path}")

    def test_incident_pages_require_login(self):
        """Visiting any incident page while logged out redirects to the login page."""
        for path in ["/incidents/list", "/incidents/form", "/incidents/landing"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith("/login/"))


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
        self.assertRedirects(response, "/incidents/list")

    def test_login_works_with_different_email_case(self):
        """Login is not case sensitive on the email."""
        response = self.client.post("/login/", {
            "email": "USER@Example.COM", "password": GOOD_PASSWORD,
        })
        self.assertRedirects(response, "/incidents/list")

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


class IncidentTests(TestCase):
    """Logged in users can create, edit, and soft delete tickets."""

    def setUp(self):
        self.user = make_user()
        self.service = make_service()
        self.client.login(username="user@example.com", password=GOOD_PASSWORD)

    def ticket_data(self, **overrides):
        data = {
            "title": "Sink leaking",
            "description": "Steady drip under the sink",
            "service": self.service.pk,
            "priority": "high",
            "building": "Moody",
            "room": "214",
        }
        data.update(overrides)
        return data

    def test_create_ticket(self):
        """A submitted ticket is saved with the signed in user as the reporter."""
        response = self.client.post("/incidents/form", self.ticket_data())
        self.assertRedirects(response, "/incidents/list")
        ticket = Incident.objects.get(title="Sink leaking")
        self.assertEqual(ticket.reported_by, self.user)
        self.assertEqual(ticket.priority, "high")
        self.assertEqual(ticket.building, "Moody")

    def test_create_ticket_without_location(self):
        """Building and room are optional."""
        self.client.post("/incidents/form", self.ticket_data(building="", room=""))
        self.assertTrue(Incident.objects.filter(title="Sink leaking").exists())

    def test_ticket_appears_in_list_newest_first(self):
        """The most recently created ticket is at the top of the list."""
        self.client.post("/incidents/form", self.ticket_data(title="First"))
        self.client.post("/incidents/form", self.ticket_data(title="Second"))
        html = self.client.get("/incidents/list").content.decode()
        self.assertLess(html.index("Second"), html.index("First"))

    def test_edit_ticket(self):
        """Editing saves the new values on the same row."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(
            f"/incidents/{ticket.pk}/edit/",
            self.ticket_data(title="Sink fixed", priority="low"),
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "Sink fixed")
        self.assertEqual(ticket.priority, "low")

    def test_edit_form_is_prefilled(self):
        """The edit page opens with the current values already filled in."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        html = self.client.get(f"/incidents/{ticket.pk}/edit/").content.decode()
        self.assertIn("Sink leaking", html)
        self.assertIn("Moody", html)

    def test_delete_is_soft(self):
        """Deleting sets is_deleted and keeps the row in the database."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        ticket.refresh_from_db()
        self.assertTrue(ticket.is_deleted)
        self.assertTrue(Incident.objects.filter(pk=ticket.pk).exists())

    def test_deleted_ticket_is_hidden_from_list(self):
        """A deleted ticket no longer appears in the list."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        html = self.client.get("/incidents/list").content.decode()
        self.assertNotIn("Sink leaking", html)

    def test_delete_persists_across_sessions(self):
        """A deletion is visible from a second, separate login."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        other = self.client_class()
        other.login(username="user@example.com", password=GOOD_PASSWORD)
        html = other.get("/incidents/list").content.decode()
        self.assertNotIn("Sink leaking", html)

    def test_delete_ignores_get(self):
        """Opening the delete URL in the browser does nothing; only POST deletes."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.get(f"/incidents/{ticket.pk}/delete/")
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_deleted)

    def test_editing_deleted_ticket_returns_404(self):
        """A deleted ticket cannot be reopened through its edit URL."""
        self.client.post("/incidents/form", self.ticket_data())
        ticket = Incident.objects.get(title="Sink leaking")
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        response = self.client.get(f"/incidents/{ticket.pk}/edit/")
        self.assertEqual(response.status_code, 404)


class ServicesPageTests(TestCase):
    """The services page groups active services under their team."""

    def test_services_grouped_by_team(self):
        """The services page shows each service under the team that owns it."""
        service = make_service()
        html = self.client.get("/services/").content.decode()
        self.assertIn(service.owning_team.name, html)
        self.assertIn(service.name, html)

    def test_inactive_services_are_hidden(self):
        """Services marked inactive do not appear on the page."""
        service = make_service()
        service.is_active = False
        service.save()
        html = self.client.get("/services/").content.decode()
        self.assertNotIn(service.name, html)
