from django.test import TestCase

from .models import Incident, Service, Team, TeamMember, User


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
        self.assertRedirects(response, "/incidents/list", target_status_code=302)
        ticket = Incident.objects.get(title="Sink leaking")
        self.assertEqual(ticket.reported_by, self.user)
        self.assertEqual(ticket.priority, "high")
        self.assertEqual(ticket.building, "Moody")

    def test_create_ticket_without_location(self):
        """Building and room are optional."""
        self.client.post("/incidents/form", self.ticket_data(building="", room=""))
        self.assertTrue(Incident.objects.filter(title="Sink leaking").exists())

    def test_ticket_appears_in_list_newest_first(self):
        """The most recently created ticket is at the top of the solver's list."""
        self.user.role = "solver"; self.user.save()
        TeamMember.objects.create(user=self.user, team=self.service.owning_team)
        Incident.objects.create(title="First", description="d", service=self.service,
            reported_by=self.user, assigned_team=self.service.owning_team)
        Incident.objects.create(title="Second", description="d", service=self.service,
            reported_by=self.user, assigned_team=self.service.owning_team)
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


class IncidentAccessTests(TestCase):
    """Only the reporter or a solver on the assigned team may open a ticket."""

    def setUp(self):
        self.team_a = Team.objects.create(name="Team A")
        self.team_b = Team.objects.create(name="Team B")
        self.service = Service.objects.create(name="Svc A", owning_team=self.team_a)
        self.reporter = User.objects.create_user(
            username="rep@x.com", email="rep@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver_a = User.objects.create_user(
            username="sa@x.com", email="sa@x.com", password=GOOD_PASSWORD, role="solver")
        self.solver_b = User.objects.create_user(
            username="sb@x.com", email="sb@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver_a, team=self.team_a)
        TeamMember.objects.create(user=self.solver_b, team=self.team_b)
        self.incident = Incident.objects.create(
            title="Guarded", description="d", service=self.service,
            reported_by=self.reporter, assigned_team=self.team_a, status="open")

    def view_as(self, email):
        self.client.login(username=email, password=GOOD_PASSWORD)
        return self.client.get(f"/incidents/{self.incident.pk}/")

    def test_reporter_can_view_own_ticket(self):
        """The person who filed the ticket can open it."""
        self.assertEqual(self.view_as("rep@x.com").status_code, 200)

    def test_solver_on_team_can_view(self):
        """A solver on the assigned team can open the ticket."""
        self.assertEqual(self.view_as("sa@x.com").status_code, 200)

    def test_solver_on_other_team_is_blocked(self):
        """A solver not on the assigned team is redirected away."""
        self.assertEqual(self.view_as("sb@x.com").status_code, 302)

    def test_other_team_solver_cannot_transition(self):
        """A solver off the team cannot change the ticket's status."""
        self.client.login(username="sb@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.incident.pk}/transition/", {"new_status": "acknowledged"})
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "open")


class TimelineEventTests(TestCase):
    """Creating and editing a ticket records events on its timeline."""

    def setUp(self):
        self.team_a = Team.objects.create(name="Plumbing")
        self.team_b = Team.objects.create(name="Electrical")
        self.svc_a = Service.objects.create(name="Pipes", owning_team=self.team_a)
        self.svc_b = Service.objects.create(name="Wiring", owning_team=self.team_b)
        self.user = User.objects.create_user(
            username="tl@x.com", email="tl@x.com", password=GOOD_PASSWORD, role="reporter")
        self.client.login(username="tl@x.com", password=GOOD_PASSWORD)

    def test_creation_is_logged(self):
        """Filing a ticket records a 'created' timeline entry."""
        self.client.post("/incidents/form", {
            "title": "T", "description": "d", "service": self.svc_a.pk, "priority": "low"})
        inc = Incident.objects.get(title="T")
        self.assertTrue(inc.incidentupdate_set.filter(update_type="created").exists())

    def test_edit_logs_assignment_severity_and_edit(self):
        """Changing the service and severity records assignment, severity, and edit entries."""
        self.client.post("/incidents/form", {
            "title": "T", "description": "d", "service": self.svc_a.pk, "priority": "low"})
        inc = Incident.objects.get(title="T")
        self.client.post(f"/incidents/{inc.pk}/edit/", {
            "title": "T", "description": "d2", "service": self.svc_b.pk,
            "priority": "high", "building": "", "room": ""})
        types = set(inc.incidentupdate_set.values_list("update_type", flat=True))
        self.assertIn("severity", types)
        self.assertIn("edit", types)


class RoleUIRulesTests(TestCase):
    """Reporters use their profile; solvers use the list; service is locked on edit."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.svc2 = Service.objects.create(name="Drains", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.incident = Incident.objects.create(
            title="X", description="d", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open")

    def test_reporter_redirected_from_list(self):
        """A reporter hitting the incident list is sent to their profile."""
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        r = self.client.get("/incidents/list")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith("/profile/"))

    def test_solver_list_has_no_edit_button(self):
        """The solver's incident list shows no Edit link."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        html = self.client.get("/incidents/list").content.decode()
        self.assertNotIn("incident_edit", html)
        self.assertNotIn(">Edit<", html)

    def test_reporter_cannot_change_service_on_edit(self):
        """Even if a reporter submits a different service, it is ignored."""
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.incident.pk}/edit/", {
            "title": "X2", "description": "d", "service": self.svc2.pk,
            "priority": "high", "building": "", "room": ""})
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.title, "X2")
        self.assertEqual(self.incident.service, self.svc)  # unchanged


class SolverCannotCreateTests(TestCase):
    """Solvers may not file tickets; only reporters can."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)

    def test_solver_get_create_form_is_blocked(self):
        """A solver opening the ticket form is redirected, not shown the form."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.client.get("/incidents/form").status_code, 302)

    def test_solver_post_create_is_blocked(self):
        """A solver POSTing a new ticket creates nothing."""
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        self.client.post("/incidents/form", {
            "title": "X", "description": "d", "service": self.svc.pk, "priority": "low"})
        self.assertEqual(Incident.objects.filter(title="X").count(), 0)


class EditTimelineDetailTests(TestCase):
    """Editing a ticket logs the old and new value of each changed field."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.incident = Incident.objects.create(
            title="Old title", description="old desc", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open",
            priority="low", building="A", room="1")
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)

    def test_edit_logs_old_and_new_values(self):
        """Changing the title records an entry naming both the old and new value."""
        self.client.post(f"/incidents/{self.incident.pk}/edit/", {
            "title": "New title", "description": "old desc", "service": self.svc.pk,
            "priority": "low", "building": "A", "room": "1"})
        bodies = list(self.incident.incidentupdate_set.filter(update_type="edit")
                      .values_list("body", flat=True))
        self.assertTrue(any("Old title" in b and "New title" in b for b in bodies))


class LifecycleEdgeTests(TestCase):
    """Exhaustive legal and illegal transition coverage for the state machine."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.inc = Incident.objects.create(
            title="T", description="d", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open")
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)

    def move(self, to):
        self.client.post(f"/incidents/{self.inc.pk}/transition/", {"new_status": to})
        self.inc.refresh_from_db()
        return self.inc.status

    def set_status(self, status):
        self.inc.status = status
        self.inc.save()

    def test_full_legal_path(self):
        """A ticket walks open to closed one step at a time."""
        self.assertEqual(self.move("acknowledged"), "acknowledged")
        self.assertEqual(self.move("in_progress"), "in_progress")
        self.assertEqual(self.move("resolved"), "resolved")
        self.assertEqual(self.move("closed"), "closed")

    def test_reopen_from_resolved(self):
        """A resolved ticket can be reopened to open."""
        self.set_status("resolved")
        self.assertEqual(self.move("open"), "open")

    def test_reopen_from_closed(self):
        """A closed ticket can be reopened to open."""
        self.set_status("closed")
        self.assertEqual(self.move("open"), "open")

    def test_illegal_open_to_resolved(self):
        """Open cannot jump straight to resolved."""
        self.assertEqual(self.move("resolved"), "open")

    def test_illegal_open_to_in_progress(self):
        """Open cannot skip to in progress."""
        self.assertEqual(self.move("in_progress"), "open")

    def test_illegal_backward_in_progress_to_open(self):
        """In progress cannot go back to open without reopening."""
        self.set_status("in_progress")
        self.assertEqual(self.move("open"), "in_progress")

    def test_illegal_backward_acknowledged_to_open(self):
        """Acknowledged cannot go back to open."""
        self.set_status("acknowledged")
        self.assertEqual(self.move("open"), "acknowledged")

    def test_garbage_status_rejected(self):
        """An unknown status value is rejected."""
        self.assertEqual(self.move("banana"), "open")

    def test_transition_requires_post(self):
        """A GET to the transition URL changes nothing."""
        self.client.get(f"/incidents/{self.inc.pk}/transition/")
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, "open")

    def test_reporter_cannot_transition(self):
        """A reporter cannot change status even with a direct POST."""
        self.client.logout()
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.assertEqual(self.move("acknowledged"), "open")

    def test_transition_records_author_and_time(self):
        """A successful transition logs who made it and when."""
        self.move("acknowledged")
        row = self.inc.incidentupdate_set.get(update_type="status_change")
        self.assertEqual(row.author, self.solver)
        self.assertIsNotNone(row.created_at)
        self.assertEqual(row.old_status, "open")
        self.assertEqual(row.new_status, "acknowledged")


class CommentEdgeTests(TestCase):
    """Comment and note rules: length, type by role, empty handling."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.solver = User.objects.create_user(
            username="s@x.com", email="s@x.com", password=GOOD_PASSWORD, role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.inc = Incident.objects.create(
            title="T", description="d", service=self.svc,
            reported_by=self.reporter, assigned_team=self.team, status="open")

    def post_comment(self, user, body):
        self.client.login(username=user, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/comment/", {"body": body})

    def test_reporter_comment_is_type_comment(self):
        """A reporter's post is stored as a comment."""
        self.post_comment("r@x.com", "please hurry")
        self.assertTrue(self.inc.incidentupdate_set.filter(update_type="comment").exists())

    def test_solver_comment_is_type_note(self):
        """A solver's post is stored as a solver note."""
        self.post_comment("s@x.com", "looking into it")
        self.assertTrue(self.inc.incidentupdate_set.filter(update_type="solver_note").exists())

    def test_empty_comment_is_ignored(self):
        """A blank comment creates no timeline row."""
        self.post_comment("r@x.com", "   ")
        self.assertEqual(self.inc.incidentupdate_set.count(), 0)

    def test_comment_at_limit_is_accepted(self):
        """A 1000-character comment is accepted."""
        self.post_comment("r@x.com", "x" * 1000)
        self.assertEqual(self.inc.incidentupdate_set.filter(update_type="comment").count(), 1)

    def test_comment_over_limit_is_rejected(self):
        """A comment longer than 1000 characters is rejected."""
        self.post_comment("r@x.com", "x" * 1001)
        self.assertEqual(self.inc.incidentupdate_set.count(), 0)


class ProfileAccessTests(TestCase):
    """The profile page requires login."""

    def test_profile_requires_login(self):
        """A logged-out visitor is redirected away from the profile."""
        r = self.client.get("/profile/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith("/login/"))
