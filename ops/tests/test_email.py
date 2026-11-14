"""Every notification also goes out by email, and a broken mail server never breaks the site."""
from unittest import mock

from django.core import mail
from django.test import TestCase

from ops.models import Incident, Notification, Service, Team, User
from ops.notifications import notify
from ops.tests.helpers import GOOD_PASSWORD


class EmailTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Port")
        self.incident = Incident.objects.create(title="Leak", description="x", service=self.service,
                                                reported_by=self.reporter)

    def test_a_notification_writes_the_row_and_sends_one_email_to_that_person(self):
        note = notify(self.tim, self.incident, "assigned", "Ticket #1 was assigned to you")
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["tim@x.com"])
        self.assertEqual((sent.cc, sent.bcc), ([], []))
        self.assertIn("Ticket #1 was assigned to you", sent.body)
        self.assertIsNotNone(note.emailed_at)

    def test_the_email_greets_the_person_by_name(self):
        notify(self.tim, self.incident, "assigned", "x")
        self.assertIn("Hello Tim Diaz,", mail.outbox[0].body)
        self.assertNotIn("Hello tim@x.com", mail.outbox[0].body)

    def test_the_subject_names_the_ticket_and_the_event(self):
        notify(self.tim, self.incident, "assigned", "x")
        notify(self.tim, self.incident, "escalated", "x")
        subjects = [m.subject for m in mail.outbox]
        self.assertEqual(subjects, [f"CampusDesk ticket #{self.incident.pk}: Assigned to you",
                                    f"CampusDesk ticket #{self.incident.pk}: Escalated to you"])

    def test_a_title_with_a_line_break_cannot_break_the_email(self):
        """The subject never carries user text, so a crafted title is harmless."""
        self.incident.title = "Leak\nBcc: someone@else.com"
        self.incident.save()
        note = notify(self.reporter, self.incident, "resolved", f"Your ticket ({self.incident.title}) was resolved")
        self.assertIsNotNone(note)
        self.assertNotIn("\n", mail.outbox[0].subject)

    def test_a_mail_server_that_fails_does_not_stop_the_notification(self):
        with mock.patch("ops.notifications.send_mail", side_effect=OSError("mail server is down")):
            with self.assertLogs("ops.notifications", level="ERROR"):
                note = notify(self.tim, self.incident, "assigned", "Ticket #1 was assigned to you")
        self.assertEqual(Notification.objects.filter(user=self.tim).count(), 1)
        self.assertIsNone(note.emailed_at)

    def test_filing_a_ticket_still_works_when_the_mail_server_is_down(self):
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        with mock.patch("ops.notifications.send_mail", side_effect=OSError("mail server is down")):
            with self.assertLogs("ops.notifications", level="ERROR"):
                notify(self.tim, self.incident, "assigned", "x")
                resp = self.client.get("/profile/")
        self.assertEqual(resp.status_code, 200)

    def test_nobody_inactive_and_nobody_without_an_address_is_emailed(self):
        self.tim.is_active = False
        self.tim.save()
        self.assertIsNone(notify(self.tim, self.incident, "assigned", "x"))
        self.reporter.email = ""
        self.reporter.save()
        note = notify(self.reporter, self.incident, "resolved", "x")
        self.assertIsNone(note.emailed_at)
        self.assertEqual(mail.outbox, [])
