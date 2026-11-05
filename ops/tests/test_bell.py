"""The bell in the nav shows unread notifications from the table and clears them."""
from django.test import TestCase

from ops.models import Incident, Notification, Service, Team, User
from ops.tests.helpers import GOOD_PASSWORD


class BellTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.other = User.objects.create_user(username="o@x.com", email="o@x.com", password=GOOD_PASSWORD, role="solver")
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc, reported_by=self.tim)
        self.a = Notification.objects.create(user=self.tim, incident=self.inc, event="assigned", message="Ticket #1 is yours")
        self.b = Notification.objects.create(user=self.tim, incident=self.inc, event="escalated", message="Ticket #1 escalated to you")
        Notification.objects.create(user=self.other, incident=self.inc, event="assigned", message="not for Tim")
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)

    def test_badge_counts_only_my_unread_rows(self):
        resp = self.client.get("/profile/")
        self.assertContains(resp, '<span class="notification-badge">2</span>')
        self.assertContains(resp, "Ticket #1 escalated to you")
        self.assertNotContains(resp, "not for Tim")

    def test_opening_one_marks_it_read_and_goes_to_the_ticket(self):
        resp = self.client.get(f"/notifications/{self.a.pk}/open/")
        self.assertRedirects(resp, f"/incidents/{self.inc.pk}/", fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertIsNotNone(self.a.read_at)
        resp = self.client.get("/profile/")
        self.assertContains(resp, '<span class="notification-badge">1</span>')

    def test_cannot_open_someone_elses(self):
        theirs = Notification.objects.get(user=self.other)
        self.assertEqual(self.client.get(f"/notifications/{theirs.pk}/open/").status_code, 404)

    def test_mark_all_read_clears_the_badge(self):
        self.client.post("/notifications/read-all/")
        resp = self.client.get("/profile/")
        self.assertNotContains(resp, "notification-badge")
        self.assertContains(resp, "No new notifications")

    def test_signed_out_pages_still_render(self):
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 200)
