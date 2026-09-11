"""Where a person is — the places gazetteer behind real location exclusions.

"Location: anywhere, except India" is only true when every profile location is
read back to the countries it points at. What is pinned here:

  · countries_in — a country named in the string wins; US state codes and
    "Indiana" never read as India; ambiguous names ("Georgia", "Punjab") keep
    both meanings; "Remote" reads as unknown, never as everywhere;
  · matches — region, country, state and city places, and None for a location
    that can't be read;
  · suggest, aliases_of, regions_outside — the chip box, the query guard and
    the search rotation never let an excluded place back in;
  · speed — 2,000 locations in well under half a second.

Pure stdlib, no Qt, no network, no files.
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import places  # noqa: E402


class CountriesIn(unittest.TestCase):
    TABLE = (
        ("Hyderabad, Sindh, Pakistan", {"PK"}),
        ("London, Ontario, Canada", {"CA"}),
        ("Indianapolis, Indiana, United States", {"US"}),
        ("Indiana", {"US"}),
        ("Fort Wayne, IN", {"US"}),
        ("Hyderabad", {"IN"}),
        ("Punjab", {"IN", "PK"}),
        ("Georgia", {"GE", "US"}),
        ("Atlanta, Georgia", {"US"}),
        ("Pune, Maharashtra, India", {"IN"}),
        ("Bengaluru", {"IN"}),
        ("Greater Mumbai Area", {"IN"}),
        ("Bombay", {"IN"}),
        ("Gurgaon, Haryana", {"IN"}),
        ("Delhi NCR", {"IN"}),
        ("India", {"IN"}),
        ("Vadodara, Gujarat", {"IN"}),
        ("Pune/Pimpri-Chinchwad Area", {"IN"}),
        ("Chennai, TN", {"IN"}),
        ("Lahore, Punjab", {"PK"}),
        ("Lebanon, Pennsylvania", {"US"}),
        ("Paris, Texas", {"US"}),
        ("Dubai, United Arab Emirates", {"AE"}),
        ("Colombo, Sri Lanka", {"LK"}),
        ("Dhaka, Bangladesh", {"BD"}),
        ("Kathmandu, Nepal", {"NP"}),
        ("München, Bayern, Deutschland", {"DE"}),
        ("São Paulo, Brazil", {"BR"}),
        ("San Francisco Bay Area", {"US"}),
        ("Viet Nam", {"VN"}),
        ("U.A.E.", {"AE"}),
        ("Remote", set()),
        ("Worldwide", set()),
        ("IN", set()),
        ("", set()),
    )

    def test_table(self):
        for text, want in self.TABLE:
            with self.subTest(text=text):
                self.assertEqual(places.countries_in(text), frozenset(want))

    def test_never_india(self):
        for text in ("Dubai, United Arab Emirates", "Colombo, Sri Lanka",
                     "Dhaka, Bangladesh", "Kathmandu, Nepal", "Indiana",
                     "Fort Wayne, IN", "Hyderabad, Sindh, Pakistan"):
            with self.subTest(text=text):
                self.assertNotIn("IN", places.countries_in(text))

    def test_not_a_string(self):
        self.assertEqual(places.countries_in(None), frozenset())


class Matches(unittest.TestCase):
    def test_places(self):
        self.assertIs(places.matches("Vadodara, Gujarat, India", "Gujarat"), True)
        self.assertIs(places.matches("Mumbai, Maharashtra, India", "Gujarat"), False)
        self.assertIs(places.matches("Berlin, Germany", "Europe"), True)
        self.assertIs(places.matches("Dubai, United Arab Emirates", "India"), False)
        self.assertIs(places.matches("Greater Mumbai Area", "India"), True)
        self.assertIs(places.matches("Bombay", "Mumbai"), True)
        self.assertIs(places.matches("Hyderabad, Sindh, Pakistan", "Telangana"), False)
        self.assertIs(places.matches("Hyderabad, Sindh, Pakistan", "South Asia"), True)
        self.assertIs(places.matches("Istanbul", "Europe"), True)   # Turkey: Europe AND
        self.assertIs(places.matches("Istanbul", "Middle East"), True)  # the Middle East

    def test_unreadable_is_none(self):
        self.assertIsNone(places.matches("", "India"))
        self.assertIsNone(places.matches("Remote", "India"))
        self.assertIsNone(places.matches(None, "India"))

    def test_unknown_place_is_a_phrase(self):
        self.assertIs(places.matches("Andheri East, Mumbai", "Andheri East"), True)
        self.assertIs(places.matches("Andheri West, Mumbai", "Andheri East"), False)


class Resolve(unittest.TestCase):
    def test_names_and_aliases(self):
        self.assertEqual(places.resolve("usa").key, "country:US")
        self.assertEqual(places.resolve("  U.K. ").key, "country:GB")
        self.assertEqual(places.resolve("KSA").key, "country:SA")
        self.assertEqual(places.resolve("Türkiye").key, "country:TR")
        self.assertEqual(places.resolve("baroda").key, "city:IN:vadodara")
        self.assertEqual(places.resolve("APAC").kind, "region")
        self.assertIsNone(places.resolve("Remote"))
        self.assertIsNone(places.resolve(""))

    def test_ambiguous_names_pick_the_bigger_place(self):
        self.assertEqual(places.resolve("Georgia").key, "country:GE")
        self.assertEqual(places.resolve("Georgia, United States").key, "state:US:georgia")
        self.assertEqual(places.resolve("Hyderabad").key, "city:IN:hyderabad")
        self.assertEqual(places.resolve("Hyderabad, Pakistan").key, "city:PK:hyderabad")

    def test_labels_resolve_to_themselves(self):
        for place in places._PLACES:
            with self.subTest(label=place.label):
                self.assertIs(places.resolve(place.label), place)


class Suggest(unittest.TestCase):
    def test_order(self):
        self.assertEqual(places.suggest("ind")[:2], ["India", "Indonesia"])
        self.assertIn("Indiana", places.suggest("ind"))
        self.assertEqual(places.suggest("bomb")[0], "Mumbai")
        self.assertEqual(places.suggest("uk")[0], "United Kingdom")

    def test_blank(self):
        self.assertEqual(places.suggest(""), [])
        self.assertEqual(places.suggest("   "), [])
        self.assertLessEqual(len(places.suggest("a", limit=3)), 3)


class AliasesOf(unittest.TestCase):
    def test_india_holds_its_cities_and_states(self):
        names = places.aliases_of("India")
        for name in ("india", "bharat", "mumbai", "bombay", "gujarat", "vadodara"):
            self.assertIn(name, names)
        self.assertNotIn("dubai", names)

    def test_region_holds_its_countries(self):
        names = places.aliases_of("Europe")
        for name in ("germany", "berlin", "united kingdom", "london", "dach"):
            self.assertIn(name, names)
        self.assertNotIn("india", names)

    def test_unknown(self):
        self.assertEqual(places.aliases_of("Atlantis"), [])


class RegionsOutside(unittest.TestCase):
    def test_except_india(self):
        phrases = places.regions_outside(["India"])
        self.assertEqual(phrases[:4], ["United States", "United Kingdom", "Germany",
                                       "United Arab Emirates"])
        banned = set(places.aliases_of("India"))
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertNotIn("IN", places.resolve(phrase).countries)
                self.assertNotIn(phrase.casefold(), banned)

    def test_excluded_region_removes_its_countries(self):
        europe = places.resolve("Europe").countries
        phrases = places.regions_outside(["Europe"])
        self.assertTrue(phrases)
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertFalse(places.resolve(phrase).countries & europe)

    def test_includes_bound_the_rotation(self):
        phrases = places.regions_outside(["Germany"], ["Europe"])
        self.assertIn("France", phrases)
        self.assertNotIn("Germany", phrases)
        self.assertNotIn("United States", phrases)
        # an exclusion inside an include splits it into what is left
        split = places.regions_outside(["Gujarat"], ["India"])
        self.assertIn("Maharashtra", split)
        self.assertNotIn("Gujarat", split)
        self.assertNotIn("India", split)


class Speed(unittest.TestCase):
    def test_two_thousand_locations(self):
        base = ["Pune, Maharashtra, India", "San Francisco Bay Area", "Dubai, United Arab Emirates",
                "Hyderabad, Sindh, Pakistan", "Greater Mumbai Area", "Berlin, Germany",
                "Fort Wayne, IN", "Remote", "London, England, United Kingdom",
                "Indianapolis, Indiana, United States"]
        texts = [f"{base[i % len(base)]} {i}" for i in range(2000)]   # all distinct: no cache help
        places._read.cache_clear()
        start = time.perf_counter()
        for text in texts:
            places.matches(text, "India")
            places.countries_in(text)
        self.assertLess(time.perf_counter() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
