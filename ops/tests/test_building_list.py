"""The campus building list, a ticket's link to it, and the reporter's rating."""
from importlib import import_module

from django.apps import apps
from django.db import IntegrityError, transaction
from django.test import TestCase

from ops.buildings import best_match, search
from ops.models import Building, Incident, Service, Team, TeamMember, User
from ops.tests.helpers import GOOD_PASSWORD

load = import_module("ops.migrations.0018_campus_buildings").load
keep_the_names = import_module("ops.migrations.0018_campus_buildings").keep_the_names
add_short_names = import_module("ops.migrations.0019_more_short_names").add_short_names


class CampusListTests(TestCase):
    def test_the_campus_list_is_loaded_with_the_database(self):
        self.assertEqual(Building.objects.filter(kind="campus").count(), 24)
        self.assertEqual(Building.objects.filter(kind="residence").count(), 12)
        for name in ("Main Building", "Munday Library", "Jacques Dujarié Hall", "St. André Apartments"):
            self.assertTrue(Building.objects.filter(name=name, is_active=True).exists(), name)

    def test_loading_it_again_adds_nothing(self):
        load(apps, None)
        self.assertEqual(Building.objects.count(), 36)

    def test_the_search_finds_real_buildings_by_how_people_say_them(self):
        campus = list(Building.objects.all())
        for typed, name in (("lbj", "Lady Bird Johnson Hall"), ("library", "Munday Library"),
                            ("nat sci n", "John Brooks Williams Natural Sciences Center–North"),
                            ("dujarie", "Jacques Dujarié Hall"), ("rec center", "Recreation and Athletic Center"),
                            ("ragsdale", "Robert and Pearle Ragsdale Center")):
            self.assertEqual(search(typed, campus)[0].name, name, typed)

    def test_text_that_says_more_than_a_name_still_finds_its_building(self):
        campus = list(Building.objects.all())
        for typed, name in (("Moody 214", "Moody Hall"), ("Fleck Hall 3rd floor", "Fleck Hall"),
                            ("library basement", "Munday Library"), ("Hunt Hall Cafe", "Edmund Hunt Hall"),
                            ("Moody Theatre", "Mary Moody Northen Theatre"), ("LeMans", "Le Mans Hall"),
                            ("Recreation Center", "Recreation and Athletic Center"), ("Old Main", "Main Building"),
                            ("Queen of Peace", "Our Lady Queen of Peace Chapel"), ("JBWN 205", None),
                            ("Moreau Casitas 3", "Casitas"), ("Saint Andre Apts", "St. André Apartments")):
            found = best_match(typed, campus)
            self.assertEqual(found.name if found else None,
                             "John Brooks Williams Natural Sciences Center–North" if typed == "JBWN 205" else name, typed)

    def test_nothing_on_the_real_list_is_guessed_from_part_of_a_name(self):
        """What reporters really typed before the list existed, none of it a building."""
        campus = list(Building.objects.all())
        for typed in ("Hall C", "B", "a", "G", "Campus", "campus wide", "Main St entrance", "Main campus",
                      "Parking lot by Main", "IT operations office", "Hill", "Hilltop", "St", "St.", "Saint",
                      "South", "East", "Health", "Research", "Lady", "House", "Our", "Of", "Gym", "Art", "Phys",
                      "Doyle", "Doyle Hall", "Science Hall", "Student Center", "N/A", "none", "test", "asdf",
                      "Everywhere", "Outside", "the parking lot", "Fleck/Trustee", "Between Moody and Fleck",
                      "Moody Hall and Fleck Hall", "Library, Moody Hall", "Natural Sciences", "图书馆", "!!!"):
            self.assertIsNone(best_match(typed, campus), typed)

    def test_every_building_is_found_by_its_own_name_and_each_of_its_short_names(self):
        campus = list(Building.objects.all())
        for building in campus:
            for name in [building.name] + [alias for alias in building.aliases.split(",") if alias.strip()]:
                self.assertEqual(best_match(name, campus), building, name)

    def test_the_extra_short_names_can_be_added_twice(self):
        add_short_names(apps, None)
        add_short_names(apps, None)
        self.assertEqual(Building.objects.count(), 36)
        self.assertEqual(Building.objects.get(name="Le Mans Hall").aliases, "Le Mans, LeMans")


class TicketBuildingTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Plumbing")
        self.service = Service.objects.create(name="Pipes", owning_team=self.team)
        self.reporter = User.objects.create_user(username="r@x.com", email="r@x.com", password=GOOD_PASSWORD,
                                                 first_name="Rae", last_name="Port")
        self.solver = User.objects.create_user(username="s@x.com", email="s@x.com", password=GOOD_PASSWORD,
                                               first_name="Tim", last_name="Diaz", role="solver")
        TeamMember.objects.create(user=self.solver, team=self.team)
        self.moody = Building.objects.get(name="Moody Hall")
        self.client.login(username="r@x.com", password=GOOD_PASSWORD)

    def fields(self, **changes):
        data = {"title": "Leak", "description": "d", "building": self.moody.pk, "room": "214",
                "service": self.service.pk, "priority": "low"}
        data.update(changes)
        return data

    def old_ticket(self, typed):
        return Incident.objects.create(title="Old leak", description="d", service=self.service,
                                       reported_by=self.reporter, assigned_team=self.team, building_typed=typed)

    def test_the_form_offers_the_campus_list(self):
        page = self.client.get("/incidents/form")
        self.assertContains(page, "Select a building, optional")
        self.assertContains(page, "Moody Hall")
        self.assertContains(page, "Teresa Hall")

    def test_a_removed_building_is_not_offered(self):
        Building.objects.filter(name="Teresa Hall").update(is_active=False)
        page = self.client.get("/incidents/form")
        self.assertNotContains(page, "Teresa Hall")
        self.client.post("/incidents/form", self.fields(building=Building.objects.get(name="Teresa Hall").pk))
        self.assertEqual(Incident.objects.count(), 0)

    def test_a_ticket_points_at_the_building_that_was_picked(self):
        self.client.post("/incidents/form", self.fields())
        ticket = Incident.objects.get()
        self.assertEqual(ticket.building, self.moody)
        self.assertEqual(ticket.building_typed, "")
        self.assertEqual(ticket.building_name, "Moody Hall")

    def test_a_ticket_can_still_be_filed_with_no_building(self):
        self.client.post("/incidents/form", self.fields(building=""))
        self.assertIsNone(Incident.objects.get().building)

    def test_an_old_ticket_shows_what_was_typed(self):
        ticket = self.old_ticket("Doyle")
        self.assertEqual(ticket.building_name, "Doyle")
        self.assertContains(self.client.get(f"/incidents/{ticket.pk}/"), "Doyle")
        self.client.logout()
        self.client.login(username="s@x.com", password=GOOD_PASSWORD)
        self.assertContains(self.client.get("/incidents/list"), "Doyle")

    def test_editing_an_old_ticket_keeps_what_was_typed(self):
        ticket = self.old_ticket("Doyle")
        self.client.post(f"/incidents/{ticket.pk}/edit/", self.fields(title="Old leak again", building=""))
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "Old leak again")
        self.assertEqual(ticket.building_name, "Doyle")
        self.assertFalse(ticket.incidentupdate_set.filter(body__contains="Building changed").exists())

    def test_changing_the_building_is_written_to_the_timeline(self):
        ticket = self.old_ticket("Doyle")
        self.client.post(f"/incidents/{ticket.pk}/edit/", self.fields(title="Old leak"))
        ticket.refresh_from_db()
        self.assertEqual(ticket.building, self.moody)
        self.assertTrue(ticket.incidentupdate_set.filter(
            body='Building changed from "Doyle" to "Moody Hall"').exists())

    def test_a_ticket_on_a_building_removed_later_can_still_be_edited(self):
        self.client.post("/incidents/form", self.fields())
        ticket = Incident.objects.get()
        Building.objects.filter(pk=self.moody.pk).update(is_active=False)
        self.client.post(f"/incidents/{ticket.pk}/edit/", self.fields(title="Leak again"))
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "Leak again")
        self.assertEqual(ticket.building, self.moody)

    def test_old_tickets_are_pointed_at_their_building_when_the_text_is_clear(self):
        clear = self.old_ticket("Moody")
        longer = self.old_ticket("Library basement")
        unknown = self.old_ticket("Doyle")
        blank = self.old_ticket("")
        load(apps, None)
        for ticket, name in ((clear, "Moody Hall"), (longer, "Munday Library"), (unknown, None), (blank, None)):
            typed = ticket.building_typed
            ticket.refresh_from_db()
            self.assertEqual(ticket.building.name if ticket.building else None, name)
            self.assertEqual(ticket.building_typed, typed)

    def test_adding_short_names_links_tickets_it_can_now_recognise_and_leaves_the_rest(self):
        late = self.old_ticket("Moody Theatre")
        linked = self.old_ticket("Fleck")
        linked.building = self.moody
        linked.save()
        unknown = self.old_ticket("Hall C")
        add_short_names(apps, None)
        for ticket, name in ((late, "Mary Moody Northen Theatre"), (linked, "Moody Hall"), (unknown, None)):
            ticket.refresh_from_db()
            self.assertEqual(ticket.building.name if ticket.building else None, name)

    def test_going_back_to_free_text_keeps_where_the_problem_is(self):
        self.client.post("/incidents/form", self.fields())
        picked = Incident.objects.get()
        typed = self.old_ticket("Doyle")
        both = self.old_ticket("Moody")
        both.building = self.moody
        both.save()
        keep_the_names(apps, None)
        for ticket, text in ((picked, "Moody Hall"), (typed, "Doyle"), (both, "Moody")):
            ticket.refresh_from_db()
            self.assertEqual(ticket.building_typed, text)

    def test_a_rating_is_empty_or_from_one_to_five(self):
        ticket = self.old_ticket("")
        self.assertIsNone(ticket.rating)
        for score in (1, 5):
            ticket.rating = score
            ticket.save()
        for score in (0, 6):
            ticket.rating = score
            with self.assertRaises(IntegrityError), transaction.atomic():
                ticket.save()
