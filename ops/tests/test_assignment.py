"""Handing a new ticket to the on-call solver."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ops.models import Incident, IncidentUpdate, Service, Shift, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD


class AutoAssignmentTests(TestCase):
    """A new ticket goes to whoever is on call for the team that owns its service."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(
            username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.tim = User.objects.create_user(
            username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
            first_name="Tim", last_name="Diaz", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)

    def file_ticket(self, service=None):
        resp = self.client.post("/incidents/form", {
            "title": "Leak", "description": "d", "service": (service or self.svc).pk,
            "priority": "low", "building": "", "room": ""})
        self.assertEqual(resp.status_code, 302)
        return Incident.objects.get(title="Leak")

    def put_tim_on_call(self):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.tim, created_by=self.tim,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))

    def test_ticket_goes_to_the_on_call_solver(self):
        """Tim is on call, so the new ticket is his and is marked assigned."""
        self.put_tim_on_call()
        inc = self.file_ticket()
        self.assertEqual(inc.assigned_to, self.tim)
        self.assertEqual(inc.assigned_team, self.team)
        self.assertEqual(inc.status, "assigned")

    def test_assignment_is_on_the_timeline_right_after_creation(self):
        """The timeline names who got the ticket, stamped moments after it was filed."""
        self.put_tim_on_call()
        inc = self.file_ticket()
        row = inc.incidentupdate_set.get(update_type="assignment")
        self.assertEqual(row.new_assignee, self.tim)
        self.assertIn("Tim Diaz", row.body)
        self.assertLess(row.created_at - inc.created_at, timedelta(seconds=5))

    def test_nobody_on_call_leaves_the_ticket_open(self):
        """No shifts at all: the ticket is created, stays open, and says why."""
        inc = self.file_ticket()
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")
        row = inc.incidentupdate_set.get(update_type="assignment_failed")
        self.assertIn("Nobody is on call for Plumbing right now", row.body)

    def test_service_without_a_team_does_not_crash(self):
        """A ticket against a team-less service is created and left unassigned."""
        loose = Service.objects.create(name="Lost and Found", owning_team=None)
        inc = self.file_ticket(service=loose)
        self.assertIsNone(inc.assigned_team)
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")
        row = inc.incidentupdate_set.get(update_type="assignment_failed")
        self.assertIn("Nobody is on call for Lost and Found right now", row.body)

    def test_deactivated_on_call_solver_is_not_assigned(self):
        """Tim is on the rota but deactivated, so the ticket stays open."""
        self.put_tim_on_call()
        self.tim.is_active = False
        self.tim.save()
        inc = self.file_ticket()
        self.assertIsNone(inc.assigned_to)
        self.assertEqual(inc.status, "open")

    def test_assigned_ticket_can_only_move_to_in_progress(self):
        """From assigned, a solver can start work but cannot jump to resolved."""
        self.put_tim_on_call()
        inc = self.file_ticket()
        self.client.logout()
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "resolved"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, "assigned")
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "in_progress"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, "in_progress")


class ReassignmentTests(TestCase):
    """A lead moves an active ticket to another solver on the team, and the timeline records it."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        self.team.lead = self.lead
        self.team.save()
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             first_name="Jane", last_name="Okoro", role="solver")
        TeamMember.objects.create(user=self.tim, team=self.team)
        TeamMember.objects.create(user=self.jane, team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 role="reporter")
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc,
                                           reported_by=self.reporter, assigned_team=self.team,
                                           assigned_to=self.tim, status="assigned", priority="low")
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=self.jane, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1))

    def post_as(self, email, solver=None):
        self.client.login(username=email, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/reassign/", {"solver": solver.pk} if solver else {})
        self.inc.refresh_from_db()

    def test_lead_reassigns_to_the_solver_on_call(self):
        """Jane is on call, so the lead can hand her the ticket."""
        self.post_as("lead@x.com")
        self.assertEqual(self.inc.assigned_to, self.jane)
        row = self.inc.incidentupdate_set.get(update_type="reassignment")
        self.assertEqual((row.author, row.old_assignee, row.new_assignee), (self.lead, self.tim, self.jane))
        self.assertIn("Tim Diaz", row.body)
        self.assertIn("Jane Okoro", row.body)

    def test_someone_who_is_not_the_lead_is_refused(self):
        """Tim cannot hand his own ticket away."""
        self.post_as("tim@x.com")
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_nobody_on_call_and_nobody_picked_is_refused(self):
        """With no shift running and no choice made there is nobody to give it to."""
        Shift.objects.all().delete()
        self.post_as("lead@x.com")
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_lead_can_pick_a_solver_who_is_not_on_call(self):
        """Any active solver on the team will do, not only the one on call."""
        bob = User.objects.create_user(username="bob@x.com", email="bob@x.com", password=GOOD_PASSWORD,
                                       first_name="Bob", last_name="Ray", role="solver")
        TeamMember.objects.create(user=bob, team=self.team)
        self.post_as("lead@x.com", bob)
        self.assertEqual(self.inc.assigned_to, bob)

    def test_someone_off_the_team_is_refused(self):
        outsider = User.objects.create_user(username="o@x.com", email="o@x.com", password=GOOD_PASSWORD,
                                            first_name="Out", last_name="Sider", role="solver")
        self.post_as("lead@x.com", outsider)
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_reassign_is_offered_in_progress_too(self):
        """The dropdown shows as long as the ticket is active and someone else is on the team."""
        self.inc.status = "in_progress"
        self.inc.save()
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        self.assertIn('class="reassign-form"', self.client.get(f"/incidents/{self.inc.pk}/").content.decode())

    def test_closed_ticket_is_refused(self):
        """Only active tickets move."""
        self.inc.status = "closed"
        self.inc.save()
        self.post_as("lead@x.com")
        self.assertEqual(self.inc.assigned_to, self.tim)

    def test_open_unassigned_ticket_becomes_assigned(self):
        """A ticket nobody holds gets a holder and the assigned status."""
        self.inc.assigned_to = None
        self.inc.status = "open"
        self.inc.save()
        self.post_as("lead@x.com")
        self.assertEqual((self.inc.assigned_to, self.inc.status), (self.jane, "assigned"))

    def test_only_the_lead_sees_the_reassign_form(self):
        """The dropdown suggests the on-call solver, leaves out the holder, and shows for the lead alone."""
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        html = self.client.get(f"/incidents/{self.inc.pk}/").content.decode()
        self.assertIn("Jane Okoro (on call now)", html)
        self.assertNotIn("<option value=\"%d\"" % self.tim.pk, html)
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertNotIn('class="reassign-form"', self.client.get(f"/incidents/{self.inc.pk}/").content.decode())


class AssigneeEditsTests(TestCase):
    """The assigned solver can always edit. The reporter can until work starts."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 role="reporter")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             role="solver")
        for u in (self.tim, self.jane):
            TeamMember.objects.create(user=u, team=self.team)
        self.inc = Incident.objects.create(title="Leak", description="d", service=self.svc,
                                           reported_by=self.reporter, assigned_team=self.team,
                                           assigned_to=self.tim, status="assigned", priority="low")

    def edit_as(self, email, title):
        self.client.login(username=email, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/edit/", {
            "title": title, "description": "d", "service": self.svc.pk,
            "priority": "low", "building": "", "room": ""})
        self.inc.refresh_from_db()
        return self.inc.title

    def test_assigned_solver_can_edit(self):
        self.assertEqual(self.edit_as("tim@x.com", "Fixed title"), "Fixed title")

    def test_reporter_can_still_edit_while_only_assigned(self):
        """Assignment is automatic, so it does not take the ticket away from the reporter."""
        self.assertEqual(self.edit_as("r@x.com", "Reporter edit"), "Reporter edit")

    def test_reporter_cannot_edit_once_work_starts(self):
        self.inc.status = "in_progress"
        self.inc.save()
        self.assertEqual(self.edit_as("r@x.com", "Nope"), "Leak")

    def test_another_solver_cannot_edit(self):
        self.assertEqual(self.edit_as("jane@x.com", "Nope"), "Leak")

    def test_reporter_edits_again_once_unassigned(self):
        self.inc.assigned_to = None
        self.inc.status = "open"
        self.inc.save()
        self.assertEqual(self.edit_as("r@x.com", "Reporter edit"), "Reporter edit")

    def test_edit_button_follows_the_rule(self):
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertIn("Edit details", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)
        self.assertIn("Edit details", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
        self.inc.status = "in_progress"
        self.inc.save()
        self.assertNotIn("Edit details", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())


class ReopenAndWaitingTests(TestCase):
    """Reopening assigns again; a ticket that waited is picked up once someone is on call."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.svc = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Lee", role="reporter")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD,
                                            first_name="Tim", last_name="Diaz", role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD,
                                             first_name="Jane", last_name="Okoro", role="solver")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD,
                                             first_name="Pat", last_name="Lee", role="solver")
        for u in (self.tim, self.jane, self.lead):
            TeamMember.objects.create(user=u, team=self.team)
        self.team.lead = self.lead
        self.team.save()

    def put_on_call(self, solver):
        now = timezone.now()
        Shift.objects.create(team=self.team, solver=solver, created_by=self.lead,
                             starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=7))

    def ticket(self, **extra):
        data = dict(title="Leak", description="d", service=self.svc, reported_by=self.reporter,
                    assigned_team=self.team, priority="low")
        data.update(extra)
        return Incident.objects.create(**data)

    def test_reopen_hands_the_ticket_to_whoever_is_on_call_now(self):
        inc = self.ticket(assigned_to=self.tim, status="resolved")
        self.put_on_call(self.jane)
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "open"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, "assigned")
        self.assertEqual(inc.assigned_to, self.jane)
        self.assertTrue(IncidentUpdate.objects.filter(incident=inc, update_type="assignment", new_assignee=self.jane).exists())

    def test_reopen_with_nobody_on_call_waits_without_a_solver(self):
        inc = self.ticket(assigned_to=self.tim, status="closed")
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{inc.pk}/transition/", {"new_status": "open"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, "open")
        self.assertIsNone(inc.assigned_to)

    def test_waiting_ticket_is_picked_up_when_a_solver_opens_the_list(self):
        inc = self.ticket(status="open")
        self.put_on_call(self.jane)
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.get("/incidents/list")
        inc.refresh_from_db()
        self.assertEqual((inc.status, inc.assigned_to), ("assigned", self.jane))

    def test_waiting_ticket_is_picked_up_when_the_schedule_changes(self):
        inc = self.ticket(status="open")
        self.client.login(username="lead@x.com", password=GOOD_PASSWORD)
        now = timezone.localtime(timezone.now()).replace(minute=0, second=0, microsecond=0)
        resp = self.client.post(f"/schedule/{self.team.pk}/", {
            "solver": self.jane.pk,
            "starts_at_0": now.strftime("%Y-%m-%d"), "starts_at_1": now.strftime("%H:%M"),
            "ends_at_0": (now + timedelta(hours=8)).strftime("%Y-%m-%d"),
            "ends_at_1": (now + timedelta(hours=8)).strftime("%H:%M")}, follow=True)
        self.assertIn("1 waiting ticket assigned", resp.content.decode())
        inc.refresh_from_db()
        self.assertEqual(inc.assigned_to, self.jane)

    def test_nothing_happens_while_nobody_is_on_call(self):
        inc = self.ticket(status="open")
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.client.get("/incidents/list")
        inc.refresh_from_db()
        self.assertEqual((inc.status, inc.assigned_to), ("open", None))


class TransitionPermissionTests(TestCase):
    """Only the assigned solver or the team lead moves a ticket; teammates only look."""

    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        svc = Service.objects.create(name="Pipes", owning_team=self.team)
        reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD, role="reporter")
        self.tim = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD, role="solver")
        self.jane = User.objects.create_user(username="jane@x.com", email="jane@x.com", password=GOOD_PASSWORD, role="solver")
        self.lead = User.objects.create_user(username="lead@x.com", email="lead@x.com", password=GOOD_PASSWORD, role="solver")
        for u in (self.tim, self.jane):
            TeamMember.objects.create(user=u, team=self.team)
        self.team.lead = self.lead
        self.team.save()
        self.inc = Incident.objects.create(title="Leak", description="d", service=svc, reported_by=reporter,
                                           assigned_team=self.team, assigned_to=self.tim, status="assigned", priority="low")

    def move_as(self, email):
        self.client.login(username=email, password=GOOD_PASSWORD)
        self.client.post(f"/incidents/{self.inc.pk}/transition/", {"new_status": "in_progress"})
        self.inc.refresh_from_db()
        return self.inc.status

    def test_teammate_cannot_move_it(self):
        self.assertEqual(self.move_as("jane@x.com"), "assigned")

    def test_assigned_solver_can(self):
        self.assertEqual(self.move_as("tim@x.com"), "in_progress")

    def test_lead_can(self):
        self.assertEqual(self.move_as("lead@x.com"), "in_progress")

    def test_buttons_follow_the_rule(self):
        self.client.login(username="jane@x.com", password=GOOD_PASSWORD)
        self.assertNotIn("Move to In Progress", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
        self.assertNotIn(">In Progress</button>", self.client.get("/incidents/list").content.decode())
        self.client.login(username="tim@x.com", password=GOOD_PASSWORD)
        self.assertIn("Move to In Progress", self.client.get(f"/incidents/{self.inc.pk}/").content.decode())
