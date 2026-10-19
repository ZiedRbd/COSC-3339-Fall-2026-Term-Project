"""Public pages, navigation, and the services page."""
from django.test import TestCase

from ops.tests.helpers import register, make_service


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
