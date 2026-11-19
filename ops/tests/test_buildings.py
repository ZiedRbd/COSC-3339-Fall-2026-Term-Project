"""Finding a building from what somebody typed."""
from collections import namedtuple

from django.test import SimpleTestCase

from ops.buildings import best_match, matches, normalize, search

Building = namedtuple("Building", "name aliases")

CAMPUS = [
    Building("Moody Hall", "Moody"),
    Building("Mary Moody Northen Theatre", "Theatre, Moody Theatre"),
    Building("Munday Library", "Library"),
    Building("Jacques Dujarié Hall", "Dujarie"),
    Building("Lady Bird Johnson Hall", "Johnson Hall, LBJ"),
    Building("John Brooks Williams Natural Sciences Center–North", "Natural Sciences North"),
    Building("Recreation and Athletic Center", "RAC, Rec Center"),
    Building("St. André Apartments", ""),
    Building("Main Building", "Main"),
    Building("Basil Moreau Hall", "Moreau"),
    Building("Casitas", "Moreau Casitas"),
]


def names(buildings):
    return [building.name for building in buildings]


class BuildingSearchTests(SimpleTestCase):
    def test_case_accents_and_punctuation_do_not_matter(self):
        self.assertEqual(normalize("Jacques  Dujarié Hall"), "jacques dujarie hall")
        self.assertEqual(normalize("St. André Apartments"), "st andre apartments")
        self.assertEqual(normalize("Natural Sciences Center–North"), "natural sciences center north")
        self.assertEqual(names(search("DUJARIE", CAMPUS)), ["Jacques Dujarié Hall"])
        self.assertEqual(names(search("st andre", CAMPUS)), ["St. André Apartments"])

    def test_the_beginning_of_a_word_is_enough(self):
        self.assertEqual(names(search("mun", CAMPUS)), ["Munday Library"])
        self.assertEqual(names(search("nat sci", CAMPUS)),
                         ["John Brooks Williams Natural Sciences Center–North"])

    def test_every_typed_word_has_to_be_found(self):
        self.assertEqual(names(search("moody theatre", CAMPUS)), ["Mary Moody Northen Theatre"])
        self.assertEqual(search("moody pool", CAMPUS), [])

    def test_the_middle_of_a_word_does_not_count(self):
        self.assertFalse(matches("ody", CAMPUS[0]))

    def test_a_short_name_finds_the_building(self):
        self.assertEqual(names(search("lbj", CAMPUS)), ["Lady Bird Johnson Hall"])
        self.assertEqual(names(search("rac", CAMPUS)), ["Recreation and Athletic Center"])

    def test_typed_words_must_all_be_in_the_same_name(self):
        # "lbj" is one short name and "hall" is in another: together they name nothing
        self.assertEqual(search("lbj hall", CAMPUS), [])

    def test_a_name_that_begins_with_the_text_comes_before_one_that_contains_it(self):
        self.assertEqual(names(search("moody", CAMPUS)), ["Moody Hall", "Mary Moody Northen Theatre"])

    def test_an_exact_name_comes_first(self):
        self.assertEqual(names(search("library", CAMPUS))[0], "Munday Library")
        self.assertEqual(names(search("rec center", CAMPUS))[0], "Recreation and Athletic Center")

    def test_nothing_typed_lists_every_building_in_order(self):
        self.assertEqual(names(search("", CAMPUS)), sorted(names(CAMPUS), key=normalize))

    def test_text_in_another_alphabet_matches_nothing_instead_of_everything(self):
        self.assertEqual(normalize("图书馆"), "图书馆")
        self.assertEqual(search("图书馆", CAMPUS), [])
        self.assertEqual(normalize("ﬁne Straße ２１４"), "fine strasse 214")


class BestMatchTests(SimpleTestCase):
    """Filing an old ticket under a building with nobody there to confirm: sure, or not at all."""

    def building(self, typed):
        found = best_match(typed, CAMPUS)
        return found.name if found else None

    def test_a_whole_name_or_short_name_is_recognised(self):
        for typed, name in (("Moody", "Moody Hall"), ("moody hall", "Moody Hall"), ("MOODY HALL", "Moody Hall"),
                            ("Library", "Munday Library"), ("rec center", "Recreation and Athletic Center"),
                            ("RAC", "Recreation and Athletic Center"), ("LBJ", "Lady Bird Johnson Hall"),
                            ("Dujarié", "Jacques Dujarié Hall"), ("St. Andre Apartments", "St. André Apartments")):
            self.assertEqual(self.building(typed), name, typed)

    def test_words_for_a_place_inside_the_building_may_come_with_the_name(self):
        for typed, name in (("Moody 214", "Moody Hall"), ("2nd floor Moody", "Moody Hall"),
                            ("MOODY HALL, ROOM 3", "Moody Hall"), ("Moody's", "Moody Hall"),
                            ("library basement", "Munday Library"), ("Outside the library", "Munday Library"),
                            ("Library, 2nd floor", "Munday Library"), ("LBJ Hall", "Lady Bird Johnson Hall"),
                            ("Johnson Hall lobby", "Lady Bird Johnson Hall"), ("The RAC", "Recreation and Athletic Center"),
                            ("Main lobby", "Main Building"), ("Moody Hall Moody Hall", "Moody Hall")):
            self.assertEqual(self.building(typed), name, typed)

    def test_the_beginning_of_a_word_is_not_enough(self):
        for typed in ("Mood", "Lib", "nat sci", "Rec", "Lady", "Johnson", "St", "Andre", "M", "B", "a"):
            self.assertIsNone(self.building(typed), typed)

    def test_text_that_says_more_than_a_place_in_the_building_is_left_alone(self):
        for typed in ("Main St entrance", "Main campus", "Main parking lot", "Parking lot by Main",
                      "Moody copy shop", "Library of Congress", "Hall C", "Hall", "Campus", "Doyle", "test", "N/A",
                      "the parking lot", "x" * 100, "", "   ", "!!!"):
            self.assertIsNone(self.building(typed), typed)

    def test_text_that_names_two_buildings_is_about_neither(self):
        for typed in ("Moody and Library", "Library, Moody Hall", "Moody Hall Theatre", "Between Moody and Main"):
            self.assertIsNone(self.building(typed), typed)

    def test_a_name_inside_a_longer_name_means_the_longer_one(self):
        self.assertEqual(self.building("Moreau"), "Basil Moreau Hall")
        self.assertEqual(self.building("Moreau Casitas 3"), "Casitas")
        self.assertEqual(self.building("Moody Theatre"), "Mary Moody Northen Theatre")
        self.assertEqual(self.building("Mary Moody Northen Theatre lobby"), "Mary Moody Northen Theatre")

    def test_two_buildings_with_the_same_name_are_never_guessed_between(self):
        twins = [Building("Annex", ""), Building("annex", "")]
        self.assertIsNone(best_match("Annex", twins))
