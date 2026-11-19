"""The auditor reads everything and changes nothing."""
from django.core import mail

from ops.models import Incident, Notification
from ops.tests.helpers import Campus


class AuditorTests(Campus):
    def setUp(self):
        super().setUp()
        self.auditor = self.person("aud@x.com", "Audie", "Tor", "auditor")
        self.client.force_login(self.auditor)

    def test_the_auditor_sees_every_ticket_except_the_deleted_ones(self):
        self.ticket("Dripping tap")
        self.ticket("Gone ticket", is_deleted=True)
        response = self.client.get("/incidents/list")
        self.assertContains(response, "Dripping tap")
        self.assertNotContains(response, "Gone ticket")

    def test_the_auditor_cannot_file_a_ticket_and_is_not_offered_to(self):
        self.assertNotContains(self.client.get("/incidents/list"), "Report a problem")
        response = self.client.post("/incidents/form", {"title": "Mine", "description": "d", "service": self.service.pk,
                                                        "priority": "low"})
        self.assertRedirects(response, "/incidents/list")
        self.assertFalse(Incident.objects.filter(title="Mine").exists())

    def test_the_auditor_cannot_move_edit_delete_or_comment_on_a_ticket(self):
        ticket = self.ticket(assigned_to=self.ann, status="assigned")
        self.client.post(f"/incidents/{ticket.pk}/transition/", {"new_status": "in_progress"})
        self.client.post(f"/incidents/{ticket.pk}/edit/", {"title": "Changed", "description": "d", "priority": "low"})
        self.client.post(f"/incidents/{ticket.pk}/delete/")
        self.client.post(f"/incidents/{ticket.pk}/comment/", {"body": "hello"})
        self.assertEqual(self.client.get(f"/console/tickets/{ticket.pk}/override/").status_code, 404)
        ticket.refresh_from_db()
        self.assertEqual((ticket.title, ticket.status, ticket.is_deleted), ("Leak", "assigned", False))
        self.assertEqual(self.entries(ticket, "note") + self.entries(ticket, "comment"), [])

    def test_a_report_reaches_the_active_administrators_and_only_an_auditor_can_send_one(self):
        ticket = self.ticket()
        gone = self.person("old@x.com", "Old", "Admin", "reporter")
        gone.is_superuser, gone.is_active = True, False
        gone.save()
        address = f"/incidents/{ticket.pk}/report/"
        self.client.post(address, {"body": "   "})
        self.assertEqual(Notification.objects.filter(event="auditor_report").count(), 0)
        self.client.post(address, {"body": "Closed with no note"})
        told = Notification.objects.filter(event="auditor_report")
        self.assertEqual([note.user for note in told], [self.admin])
        self.assertNotIn("(", told[0].message)
        self.client.force_login(self.reporter)
        self.client.post(address, {"body": "Not an auditor"})
        self.assertEqual(Notification.objects.filter(event="auditor_report").count(), 1)
        self.assertLessEqual(len(mail.outbox), 1)
