"""Finding a building from what somebody typed."""
from collections import namedtuple

from django.test import SimpleTestCase

from ops.buildings import best_match, matches, normalize, search

Building = namedtuple("Building", "name aliases")

CAMPUS = [
    Building("Moody Hall", ""),
    Building("Mary Moody Northen Theatre", "Theatre"),
    Building("Munday Library", "Library"),
    Building("Jacques Dujarié Hall", "Dujarie"),
    Building("Lady Bird Johnson Hall", "Johnson Hall, LBJ"),
    Building("John Brooks Williams Natural Sciences Center–North", "Natural Sciences North"),
    Building("Recreation and Athletic Center", "RAC, Rec Center"),
    Building("St. André Apartments", ""),
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

    def test_free_text_is_matched_to_one_building_or_to_none(self):
        self.assertEqual(best_match("Moody", CAMPUS).name, "Moody Hall")
        self.assertEqual(best_match("Library", CAMPUS).name, "Munday Library")
        self.assertEqual(best_match("rec center", CAMPUS).name, "Recreation and Athletic Center")
        self.assertIsNone(best_match("Doyle", CAMPUS))
        self.assertIsNone(best_match("", CAMPUS))
        # "hall" begins a word in three names equally well
        self.assertIsNone(best_match("hall", CAMPUS))
