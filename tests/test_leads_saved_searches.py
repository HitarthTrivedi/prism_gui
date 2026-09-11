"""The Leads saved-searches store (addons.leads.saved_searches).

A saved search is the owner's filters and run settings under a name, to be run
again whenever they like. What that rests on, pinned against temp folders only:

  · create, update, rename, delete and mark_run each do exactly one thing, and
    the list is most recently used first (last run, else last edit);
  · a name is trimmed and collapsed, 1-80 characters, and unique whatever its
    case — a search being updated may keep its own;
  · nothing but normalised filters and whitelisted settings reaches disk
    (the panel builds them next to cfg, which carries the API keys);
  · a damaged file lists nothing and is moved aside — never overwritten — by
    the next save; a file from a newer Prism is never written over at all;
  · an entry that is not a search is left out of the list, written back if it
    is an object, dropped if it is not;
  · writes are atomic, and four threads writing at once lose nothing.

No network, no Qt.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.leads import saved_searches as S                    # noqa: E402
from prospector.filters import SearchSpec                       # noqa: E402

RECORD_KEYS = {"id", "name", "filters", "settings", "created_at", "updated_at",
               "last_run_at", "last_session_id", "runs", "last_new"}

FILTERS = {"job_titles": {"include": ["Head of Automation", "Plant Head"]},
           "industries": {"include": ["Pharmaceuticals", "Chemicals"]},
           "locations": {"exclude": ["India"]},
           "seniority": {"include": ["Head"]}}
SETTINGS = {"target": 300, "limit": 25, "verify_limit": 25,
            "include_earlier": False, "offer": "Line automation retrofits"}

T1, T2, T3, T4, T5, T6, T7 = (f"2026-09-1{i}T10:00:00+05:30" for i in range(1, 8))
SESSION = "20260911-142233-a1b2c3"


def at(when):
    """Hold the store's clock at `when`."""
    return mock.patch.object(S, "_now", return_value=when)


class _Folder(unittest.TestCase):
    """A temp parent, and a folder inside it that does not exist yet — the
    first save must create it, and nothing else may."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self._tmp.name, "Leads searches")

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, name=S.FILE):
        return os.path.join(self.folder, name)

    def _read(self):
        with open(self._path(), encoding="utf-8") as f:
            return json.load(f)

    def _bytes(self, name=S.FILE):
        with open(self._path(name), "rb") as f:
            return f.read()

    def _write(self, text, name=S.FILE):
        os.makedirs(self.folder, exist_ok=True)
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        with open(self._path(name), "wb") as f:
            f.write(data)

    def _names(self):
        return [r["name"] for r in S.list_searches(self.folder)]

    def _temps(self):
        return [n for n in os.listdir(self.folder) if n.endswith(".tmp")]

    def _asides(self):
        return sorted(n for n in os.listdir(self.folder) if ".damaged-" in n)

    def _save(self, name="Pharma heads", filters=None, settings=None, **kw):
        return S.save(self.folder, name, FILTERS if filters is None else filters,
                      SETTINGS if settings is None else settings, **kw)


# ── create, read, update ──────────────────────────────────────────────────────

class CreateAndRead(_Folder):

    def test_a_new_search_is_the_full_record(self):
        with at(T1):
            record = self._save()
        self.assertEqual(set(record), RECORD_KEYS)
        self.assertRegex(record["id"], r"^ss-\d{8}-\d{6}-[0-9a-f]{6}$")
        self.assertEqual(record["name"], "Pharma heads")
        self.assertEqual(record["filters"], SearchSpec.from_dict(FILTERS).to_dict())
        self.assertEqual(record["settings"], SETTINGS)
        self.assertEqual((record["created_at"], record["updated_at"]), (T1, T1))
        self.assertEqual((record["last_run_at"], record["last_session_id"],
                          record["runs"], record["last_new"]), ("", "", 0, 0))
        self.assertEqual(S.list_searches(self.folder), [record])
        self.assertEqual(S.get(self.folder, record["id"]), record)
        self.assertEqual(self._read(), {"schema": S.SCHEMA, "searches": [record]})

    def test_real_timestamps_are_local_with_their_offset(self):
        record = self._save()
        self.assertRegex(record["created_at"],
                         r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")

    def test_ids_do_not_collide_in_the_same_second(self):
        with mock.patch.object(S, "_stamp", return_value="20260911-101500"):
            ids = {self._save(f"Search {i}")["id"] for i in range(25)}
        self.assertEqual(len(ids), 25)

    def test_get_an_id_that_is_not_there_or_not_an_id(self):
        record = self._save()
        for bad in ("ss-20260101-000000-abcdef", "../escape", "", None, 42,
                    record["id"].upper()):
            with self.subTest(search_id=bad):
                self.assertIsNone(S.get(self.folder, bad))

    def test_a_folder_that_does_not_exist_lists_nothing_and_is_not_created(self):
        self.assertEqual(S.list_searches(self.folder), [])
        self.assertIsNone(S.get(self.folder, "ss-20260101-000000-abcdef"))
        self.assertFalse(S.delete(self.folder, "ss-20260101-000000-abcdef"))
        self.assertIsNone(S.mark_run(self.folder, "ss-20260101-000000-abcdef",
                                     SESSION, new_people=3))
        self.assertFalse(os.path.exists(self.folder))

    def test_summary_is_the_spec_in_a_few_words(self):
        record = self._save()
        self.assertEqual(S.summary(record), SearchSpec.from_dict(FILTERS).summary())
        self.assertEqual(S.summary(record),
                         "2 titles · 2 industries · Anywhere except India · +1 more")
        for odd in ({}, None, {"filters": "India"}, "not a record"):
            with self.subTest(record=odd):
                self.assertEqual(S.summary(odd), "Anywhere")


class Update(_Folder):

    def test_an_update_replaces_the_search_and_keeps_its_history(self):
        with at(T1):
            first = self._save()
        with at(T2):
            S.mark_run(self.folder, first["id"], SESSION, new_people=34)
        new_filters = {"job_titles": {"include": ["COO"]},
                       "locations": {"include": ["UAE"]}}
        with at(T3):
            updated = S.save(self.folder, "Gulf COOs", new_filters,
                             {"target": 500, "offer": "Retrofits"},
                             search_id=first["id"])
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["name"], "Gulf COOs")
        self.assertEqual(updated["filters"], SearchSpec.from_dict(new_filters).to_dict())
        self.assertEqual(updated["settings"], {"target": 500, "offer": "Retrofits"})
        self.assertEqual((updated["created_at"], updated["updated_at"],
                          updated["last_run_at"]), (T1, T3, T2))
        self.assertEqual((updated["runs"], updated["last_session_id"],
                          updated["last_new"]), (1, SESSION, 34))
        self.assertEqual(S.list_searches(self.folder), [updated])

    def test_settings_none_keeps_them_and_an_empty_dict_clears_them(self):
        record = self._save()
        kept = S.save(self.folder, "Pharma heads", {"job_titles": {"include": ["CEO"]}},
                      search_id=record["id"])
        self.assertEqual(kept["settings"], SETTINGS)
        cleared = S.save(self.folder, "Pharma heads", FILTERS, {},
                         search_id=record["id"])
        self.assertEqual(cleared["settings"], {})
        self.assertEqual(S.get(self.folder, record["id"])["settings"], {})

    def test_an_update_may_keep_its_own_name_or_change_its_case(self):
        record = self._save()
        same = self._save("Pharma heads", search_id=record["id"])
        self.assertEqual(same["name"], "Pharma heads")
        louder = self._save("PHARMA  HEADS", search_id=record["id"])
        self.assertEqual(louder["name"], "PHARMA HEADS")
        self.assertEqual(self._names(), ["PHARMA HEADS"])

    def test_an_id_that_is_not_there_is_refused_and_nothing_is_written(self):
        self._save()
        before = self._bytes()
        for bad in ("ss-20260101-000000-abcdef", "nope", "", "../escape", 7):
            with self.subTest(search_id=bad):
                with self.assertRaises(S.SavedSearchError) as caught:
                    self._save("Another", search_id=bad)
                self.assertTrue(str(caught.exception)
                                .startswith("Couldn't save this search:"))
        self.assertEqual(self._bytes(), before)


# ── rename, delete, mark_run ──────────────────────────────────────────────────

class Rename(_Folder):

    def test_rename(self):
        with at(T1):
            record = self._save()
        with at(T2):
            renamed = S.rename(self.folder, record["id"], "  Pharma   plant heads ")
        self.assertEqual(renamed["name"], "Pharma plant heads")
        self.assertEqual((renamed["created_at"], renamed["updated_at"]), (T1, T2))
        self.assertEqual(renamed["filters"], record["filters"])
        self.assertEqual(renamed["settings"], record["settings"])
        self.assertEqual(S.get(self.folder, record["id"]), renamed)

    def test_renaming_to_the_name_it_has_writes_nothing(self):
        with at(T1):
            record = self._save()
        before = self._bytes()
        with at(T2):
            same = S.rename(self.folder, record["id"], " Pharma heads ")
        self.assertEqual(same, record)
        self.assertEqual(self._bytes(), before)

    def test_a_taken_name_is_refused_whatever_its_case(self):
        self._save("Pharma heads")
        other = self._save("Glass plants")
        before = self._bytes()
        with self.assertRaises(S.SavedSearchError) as caught:
            S.rename(self.folder, other["id"], "PHARMA HEADS")
        message = str(caught.exception)
        self.assertTrue(message.startswith("Couldn't rename this search:"), message)
        self.assertIn("“Pharma heads”", message)
        self.assertEqual(self._bytes(), before)

    def test_an_id_that_is_not_there_is_refused(self):
        self._save()
        for bad in ("ss-20260101-000000-abcdef", "nope", None):
            with self.subTest(search_id=bad):
                with self.assertRaises(S.SavedSearchError):
                    S.rename(self.folder, bad, "New name")


class Delete(_Folder):

    def test_delete(self):
        keep = self._save("Keep me")
        gone = self._save("Delete me")
        self.assertTrue(S.delete(self.folder, gone["id"]))
        self.assertIsNone(S.get(self.folder, gone["id"]))
        self.assertEqual(S.list_searches(self.folder), [keep])
        self.assertFalse(S.delete(self.folder, gone["id"]))           # already gone
        for bad in ("ss-20260101-000000-abcdef", "../escape", None):
            with self.subTest(search_id=bad):
                self.assertFalse(S.delete(self.folder, bad))
        self.assertEqual(S.list_searches(self.folder), [keep])

    def test_a_deleted_name_is_free_again(self):
        first = self._save("Pharma heads")
        S.delete(self.folder, first["id"])
        again = self._save("pharma heads")
        self.assertNotEqual(again["id"], first["id"])
        self.assertEqual(self._names(), ["pharma heads"])


class MarkRun(_Folder):

    def setUp(self):
        super().setUp()
        with at(T1):
            self.record = self._save()

    def test_a_run_is_recorded_and_the_edit_time_is_not_moved(self):
        with at(T2):
            ran = S.mark_run(self.folder, self.record["id"], SESSION, new_people=34)
        self.assertEqual((ran["runs"], ran["last_run_at"], ran["last_session_id"],
                          ran["last_new"]), (1, T2, SESSION, 34))
        self.assertEqual((ran["created_at"], ran["updated_at"]), (T1, T1))
        self.assertEqual(S.get(self.folder, self.record["id"]), ran)

    def test_a_second_run_counts_again(self):
        with at(T2):
            S.mark_run(self.folder, self.record["id"], SESSION, new_people=34)
        with at(T3):
            ran = S.mark_run(self.folder, self.record["id"],
                             "20260912-090000-bbbbbb", new_people=5)
        self.assertEqual((ran["runs"], ran["last_run_at"], ran["last_session_id"],
                          ran["last_new"]), (2, T3, "20260912-090000-bbbbbb", 5))

    def test_the_same_session_reported_again_is_one_run(self):
        with at(T2):
            S.mark_run(self.folder, self.record["id"], SESSION, new_people=34)
        with at(T3):
            again = S.mark_run(self.folder, self.record["id"], SESSION, new_people=31)
        self.assertEqual((again["runs"], again["last_run_at"], again["last_new"]),
                         (1, T2, 31))

    def test_an_id_that_is_not_there_is_none_and_writes_nothing(self):
        before = self._bytes()
        for bad in ("ss-20260101-000000-abcdef", "nope", None):
            with self.subTest(search_id=bad):
                self.assertIsNone(S.mark_run(self.folder, bad, SESSION, new_people=1))
        self.assertEqual(self._bytes(), before)

    def test_what_is_not_a_session_id_or_a_count_is_not_stored(self):
        for session_id, new_people, runs in ((None, -5, 1), ("../escape", True, 2),
                                             ("index", "7", 3), (42, 2.9, 4)):
            with self.subTest(session_id=session_id):
                ran = S.mark_run(self.folder, self.record["id"], session_id,
                                 new_people=new_people)
                self.assertEqual(ran["last_session_id"], "")
                self.assertEqual(ran["runs"], runs)          # every such report counts
        self.assertEqual(S.get(self.folder, self.record["id"])["last_new"], 2)
        self.assertEqual(
            [S.mark_run(self.folder, self.record["id"], None, new_people=n)["last_new"]
             for n in (-5, True, "7", "junk")], [0, 0, 7, 0])


# ── the order ─────────────────────────────────────────────────────────────────

class MostRecentlyUsedFirst(_Folder):

    def test_last_run_else_last_edit(self):
        with at(T1):
            a = self._save("A")
        with at(T2):
            b = self._save("B")
        with at(T3):
            c = self._save("C")
        self.assertEqual(self._names(), ["C", "B", "A"])
        with at(T4):
            S.mark_run(self.folder, a["id"], SESSION, new_people=1)
        self.assertEqual(self._names(), ["A", "C", "B"])
        with at(T5):
            S.rename(self.folder, b["id"], "B2")                # never run: its edit counts
        self.assertEqual(self._names(), ["B2", "A", "C"])
        with at(T6):
            S.mark_run(self.folder, c["id"], "20260916-100000-cccccc", new_people=1)
        self.assertEqual(self._names(), ["C", "B2", "A"])
        with at(T7):
            self._save("A", search_id=a["id"])       # a search that has run sorts by its run
        self.assertEqual(self._names(), ["C", "B2", "A"])
        self.assertEqual([r["name"] for r in self._read()["searches"]], ["C", "B2", "A"])

    def test_ties_keep_the_newest_first(self):
        with at(T1):
            for name in ("first", "second", "third"):
                self._save(name)
        self.assertEqual(self._names(), ["third", "second", "first"])

    def test_times_are_compared_as_moments_not_text(self):
        def entry(n, last_run_at):
            return {"id": f"ss-20260911-10000{n}-00000{n}", "name": f"S{n}",
                    "filters": {}, "last_run_at": last_run_at,
                    "created_at": "2026-09-01T10:00:00+05:30"}
        self._write(json.dumps({"schema": 1, "searches": [
            entry(1, "2026-09-11T10:00:00+05:30"),      # 04:30 UTC
            entry(2, "2026-09-11T06:00:00+00:00"),      # 06:00 UTC — later
            entry(3, "not a time"),                     # falls back to its edit time
        ]}))
        self.assertEqual(self._names(), ["S2", "S1", "S3"])


# ── names ─────────────────────────────────────────────────────────────────────

class Names(_Folder):

    def test_names_are_trimmed_and_collapsed(self):
        record = self._save("  Pharma \n\t heads  ")
        self.assertEqual(record["name"], "Pharma heads")

    def test_a_blank_or_missing_name_is_refused_before_anything_is_written(self):
        for bad in ("", "   ", "\n\t", None, 42, ["Pharma"]):
            with self.subTest(name=bad):
                with self.assertRaises(S.SavedSearchError) as caught:
                    self._save(bad)
                self.assertTrue(str(caught.exception)
                                .startswith("Couldn't save this search:"))
        self.assertFalse(os.path.exists(self.folder))

    def test_eighty_characters_is_the_limit(self):
        self.assertEqual(S.NAME_MAX, 80)
        self.assertEqual(self._save("x" * 80)["name"], "x" * 80)
        self.assertEqual(self._save("  " + "y" * 80 + "  ")["name"], "y" * 80)
        self.assertEqual(self._save("a" * 40 + "    " + "b" * 39)["name"],
                         "a" * 40 + " " + "b" * 39)
        with self.assertRaises(S.SavedSearchError) as caught:
            self._save("z" * 81)
        self.assertIn("80 characters", str(caught.exception))
        self.assertEqual(len(S.list_searches(self.folder)), 3)

    def test_names_are_unique_whatever_the_case(self):
        self._save("Pharma heads")
        for taken in ("pharma heads", "PHARMA  HEADS", " Pharma heads "):
            with self.subTest(name=taken):
                with self.assertRaisesRegex(S.SavedSearchError, "“Pharma heads”"):
                    self._save(taken)
        self.assertEqual(self._names(), ["Pharma heads"])

    def test_an_update_cannot_take_another_searchs_name(self):
        self._save("Pharma heads")
        other = self._save("Glass plants")
        with self.assertRaises(S.SavedSearchError):
            self._save("pharma HEADS", search_id=other["id"])
        self.assertEqual(sorted(self._names()), ["Glass plants", "Pharma heads"])


# ── what reaches disk ─────────────────────────────────────────────────────────

class OnlyFiltersAndWhitelistedSettingsReachDisk(_Folder):

    def test_no_secret_reaches_disk(self):
        settings = dict(SETTINGS, exa_api_key="exa-SECRET-123", api_key="gsk_SECRET",
                        cfg={"api_key": "gsk_SECRET_456"})
        filters = dict(FILTERS, exa_api_key="exa-SECRET-123",
                       cfg={"exa_api_key": "exa-SECRET"},
                       locations={"exclude": ["India"], "api_key": "exa-SECRET"})
        record = self._save(filters=filters, settings=settings)
        self.assertNotIn(b"SECRET", self._bytes())
        self.assertEqual(record["settings"], SETTINGS)
        self.assertEqual(set(record["filters"]), set(SearchSpec().to_dict()))
        self.assertEqual(record["filters"], SearchSpec.from_dict(FILTERS).to_dict())
        S.save(self.folder, "Pharma heads", filters, settings, search_id=record["id"])
        S.mark_run(self.folder, record["id"], SESSION, new_people=3)
        self.assertNotIn(b"SECRET", self._bytes())
        self.assertLessEqual(set(self._read()["searches"][0]["settings"]),
                             set(S.SETTING_KEYS))

    def test_settings_are_coerced_and_clamped(self):
        cases = [
            ("target", 5, 20), ("target", 99999, 2000), ("target", "300", 300),
            ("target", " 450 ", 450), ("target", 300.9, 300), ("target", True, None),
            ("target", "abc", None), ("target", None, None),
            ("target", float("nan"), None), ("target", float("inf"), None),
            ("limit", 0, 1), ("limit", 501, 500), ("limit", 25, 25),
            ("verify_limit", -3, 0), ("verify_limit", 250, 200), ("verify_limit", 0, 0),
            ("include_earlier", True, True), ("include_earlier", False, False),
            ("include_earlier", "yes", None), ("include_earlier", 1, None),
            ("offer", "x" * 5000, "x" * 4000), ("offer", "", ""), ("offer", 42, None),
        ]
        for i, (key, given, stored) in enumerate(cases):
            with self.subTest(key=key, given=given):
                record = self._save(f"Case {i}", settings={key: given})
                expected = {} if stored is None else {key: stored}
                self.assertEqual(record["settings"], expected)
                self.assertEqual(S.get(self.folder, record["id"])["settings"], expected)

    def test_filters_are_normalised(self):
        raw = {"seniority": {"include": ["Head", "C-suite", "nonsense"],
                             "exclude": ["intern"]},
               "locations": {"include": ["India", "UAE"], "exclude": ["india"]},
               "headcount": ["10001+", "1-10", "huge"],
               "job_titles": {"include": "Plant Head, Operations Head\nplant head"},
               "similar_titles": "no"}
        record = self._save(filters=raw)
        stored = self._read()["searches"][0]["filters"]
        self.assertEqual(stored, record["filters"])
        self.assertEqual(stored, SearchSpec.from_dict(raw).to_dict())
        self.assertEqual(stored["seniority"], {"include": ["head", "c_suite"],
                                               "exclude": ["intern"]})
        self.assertEqual(stored["locations"], {"include": ["UAE"], "exclude": ["india"]})
        self.assertEqual(stored["headcount"], ["1-10", "10001+"])
        self.assertEqual(stored["job_titles"]["include"], ["Plant Head", "Operations Head"])
        self.assertIs(stored["similar_titles"], True)
        self.assertEqual(stored["v"], 1)

    def test_revenue_bands_round_trip_and_an_older_file_has_none(self):
        raw = dict(FILTERS, revenue=["gt1b", "Under $1M", "lots"], headcount=["51-200"])
        record = self._save(filters=raw)
        self.assertEqual(record["filters"]["revenue"], ["lt1m", "gt1b"])
        self.assertEqual(self._read()["searches"][0]["filters"]["revenue"], ["lt1m", "gt1b"])
        got = S.get(self.folder, record["id"])
        self.assertEqual(SearchSpec.from_dict(got["filters"]).revenue, ["lt1m", "gt1b"])
        self.assertEqual(S.summary(got), SearchSpec.from_dict(raw).summary())
        updated = S.save(self.folder, "Pharma heads", got["filters"], SETTINGS,
                         search_id=record["id"])
        self.assertEqual(updated["filters"], record["filters"])
        # A search saved before the facet existed: no revenue filter, not an error.
        data = self._read()
        del data["searches"][0]["filters"]["revenue"]
        self._write(json.dumps(data))
        self.assertEqual(S.get(self.folder, record["id"])["filters"]["revenue"], [])

    def test_a_search_spec_is_taken_as_is(self):
        record = self._save(filters=SearchSpec.from_dict(FILTERS))
        self.assertEqual(record["filters"], SearchSpec.from_dict(FILTERS).to_dict())

    def test_filters_or_settings_that_are_not_objects_are_refused(self):
        for filters, settings in (("India", None), (None, None), (["x"], None),
                                  (FILTERS, "target=300"), (FILTERS, [("target", 1)])):
            with self.subTest(filters=filters, settings=settings):
                with self.assertRaises(S.SavedSearchError):
                    S.save(self.folder, "Pharma heads", filters, settings)
        self.assertFalse(os.path.exists(self.folder))

    def test_half_an_emoji_does_not_cost_the_search(self):
        record = self._save(settings={"offer": "Retrofits \ud83d and \U0001F525"})
        self.assertEqual(self._temps(), [])
        self.assertEqual(S.get(self.folder, record["id"])["settings"]["offer"],
                         "Retrofits � and \U0001F525")


# ── a damaged, newer or unreadable file ───────────────────────────────────────

_ASIDE = re.compile(r"^saved_searches\.damaged-\d{8}-\d{6}(-\d+)?\.json$")
_GARBAGE = ("{ not json", "", "[]", '{"schema": 1}', '{"schema": "1", "searches": []}',
            '{"schema": 0, "searches": []}', '{"searches": []}',
            '{"schema": 1, "searches": {}}')


class ADamagedFile(_Folder):

    def test_a_damaged_file_lists_nothing_and_listing_never_rewrites_it(self):
        for garbage in _GARBAGE + (b"\xff\xfe\x00binary",):
            with self.subTest(file=garbage):
                self._write(garbage)
                before = self._bytes()
                self.assertEqual(S.list_searches(self.folder), [])
                self.assertIsNone(S.get(self.folder, "ss-20260101-000000-abcdef"))
                self.assertEqual(self._bytes(), before)
                self.assertEqual(self._asides(), [])

    def test_the_next_save_moves_it_aside_first(self):
        self._write("{ not json")
        record = self._save()
        asides = self._asides()
        self.assertEqual(len(asides), 1)
        self.assertRegex(asides[0], _ASIDE)
        self.assertEqual(self._bytes(asides[0]), b"{ not json")
        self.assertEqual(S.list_searches(self.folder), [record])
        self.assertEqual(self._temps(), [])

    def test_a_second_damage_in_the_same_second_keeps_the_first_aside(self):
        with mock.patch.object(S, "_stamp", return_value="20260911-101500"):
            self._write("first damage")
            self._save("One")
            self._write("second damage")
            self._save("Two")
        self.assertEqual(self._asides(), ["saved_searches.damaged-20260911-101500-2.json",
                                          "saved_searches.damaged-20260911-101500.json"])
        self.assertEqual(self._bytes("saved_searches.damaged-20260911-101500.json"),
                         b"first damage")
        self.assertEqual(self._bytes("saved_searches.damaged-20260911-101500-2.json"),
                         b"second damage")
        self.assertEqual(self._names(), ["Two"])

    def test_changes_to_searches_it_does_not_hold_touch_nothing(self):
        self._write("{ not json")
        some_id = "ss-20260101-000000-abcdef"
        self.assertFalse(S.delete(self.folder, some_id))
        self.assertIsNone(S.mark_run(self.folder, some_id, SESSION, new_people=1))
        with self.assertRaises(S.SavedSearchError):
            S.rename(self.folder, some_id, "New")
        with self.assertRaises(S.SavedSearchError):
            self._save(search_id=some_id)
        with self.assertRaises(S.SavedSearchError):
            self._save("   ")                         # refused before it is set aside
        self.assertEqual(self._bytes(), b"{ not json")
        self.assertEqual(self._asides(), [])

    def test_a_file_that_cannot_be_set_aside_is_left_whole(self):
        self._write("{ not json")
        with mock.patch.object(S.os, "rename",
                               side_effect=PermissionError(13, "Access is denied")):
            with self.assertRaises(S.SavedSearchError) as caught:
                self._save()
        message = str(caught.exception)
        self.assertTrue(message.startswith("Couldn't save this search:"), message)
        self.assertIn("damaged", message)
        self.assertEqual(self._bytes(), b"{ not json")
        self.assertEqual(self._temps(), [])

    def test_a_file_from_a_newer_prism_is_never_written_over(self):
        newer = json.dumps({"schema": S.SCHEMA + 1, "searches": {"reshaped": True}})
        self._write(newer)
        self.assertEqual(S.list_searches(self.folder), [])
        some_id = "ss-20260101-000000-abcdef"
        for attempt in (lambda: self._save(),
                        lambda: S.rename(self.folder, some_id, "New"),
                        lambda: S.delete(self.folder, some_id),
                        lambda: S.mark_run(self.folder, some_id, SESSION, new_people=1)):
            with self.assertRaisesRegex(S.SavedSearchError, "newer version of Prism"):
                attempt()
        self.assertEqual(self._bytes(), newer.encode("utf-8"))
        self.assertEqual(self._asides(), [])

    def test_a_file_that_cannot_be_opened_is_not_replaced(self):
        os.makedirs(self._path())                  # a folder where the file should be
        self.assertEqual(S.list_searches(self.folder), [])
        with self.assertRaises(S.SavedSearchError):
            self._save()
        self.assertTrue(os.path.isdir(self._path()))
        self.assertEqual(self._asides(), [])

    def test_a_bom_from_notepad_still_reads(self):
        entry = {"id": "ss-20260911-101500-abcdef", "name": "Hand made",
                 "filters": {"locations": {"include": ["UAE"]}}}
        self._write(b"\xef\xbb\xbf" + json.dumps({"schema": 1, "searches": [entry]})
                    .encode("utf-8"))
        self.assertEqual(self._names(), ["Hand made"])


class EntriesThatAreNotSearches(_Folder):

    A = "ss-20260911-100000-aaaaaa"
    B = "ss-20260911-100000-bbbbbb"
    ODD = "ss-20260911-100000-dddddd"

    def setUp(self):
        super().setUp()
        self.full = {"id": self.A, "name": "Full", "filters": FILTERS,
                     "settings": SETTINGS, "created_at": T1, "updated_at": T1,
                     "last_run_at": T3, "last_session_id": SESSION, "runs": 2,
                     "last_new": 9}
        self.minimal = {"id": self.B, "name": "  Minimal   one ",
                        "filters": {"locations": {"include": ["UAE"]}},
                        "created_at": T2}
        self.odd = {"id": self.ODD, "name": "Odd", "filters": {}, "settings": {
                        "target": "abc", "offer": "hi", "api_key": "x"},
                    "runs": "3", "last_new": -2, "last_session_id": "../x",
                    "updated_at": T1, "pinned": True}
        self.kept = [
            {"id": "../escape", "name": "Bad id", "filters": {}},
            {"id": "ss-20260911-100000-cccccc", "filters": {}},          # no name
            {"id": "ss-20260911-100000-eeeeee", "name": "Stringy", "filters": "India"},
            {"id": "ss-20260911-100000-ffffff", "name": "Bad settings",
             "filters": {}, "settings": "target=300"},
            {"id": self.A, "name": "A second copy", "filters": {}},       # duplicate id
        ]
        self._write(json.dumps({"schema": 1, "searches": [
            "junk", self.kept[0], self.full, 42, None, self.kept[1], self.minimal,
            ["a", "list"], self.kept[2], self.odd, self.kept[3], self.kept[4]]}))

    def test_only_searches_are_listed_and_the_rest_is_forgiven(self):
        listed = S.list_searches(self.folder)
        self.assertEqual([r["id"] for r in listed], [self.A, self.B, self.ODD])
        full, minimal, odd = listed
        self.assertEqual(full["name"], "Full")
        self.assertEqual((full["runs"], full["last_new"]), (2, 9))
        self.assertEqual(minimal["name"], "Minimal one")
        self.assertEqual((minimal["settings"], minimal["updated_at"], minimal["runs"],
                          minimal["last_run_at"], minimal["last_session_id"]),
                         ({}, T2, 0, "", ""))
        self.assertEqual(minimal["filters"]["locations"], {"include": ["UAE"], "exclude": []})
        self.assertEqual((odd["settings"], odd["runs"], odd["last_new"],
                          odd["last_session_id"], odd["created_at"]),
                         ({"offer": "hi"}, 3, 0, "", ""))
        self.assertEqual(set(odd), RECORD_KEYS)
        for record in listed:
            self.assertEqual(set(record), RECORD_KEYS)

    def test_the_next_write_keeps_objects_as_they_were_and_drops_the_rest(self):
        with at(T7):
            new = self._save("New one")
        stored = self._read()["searches"]
        listed = S.list_searches(self.folder)
        self.assertEqual(stored[:4], listed)
        self.assertEqual(listed[0]["id"], new["id"])
        self.assertEqual(stored[4:], self.kept)
        self.assertNotIn("pinned", json.dumps(stored[:4]))
        self.assertNotIn(new["id"], [k.get("id") for k in self.kept])

    def test_one_entry_that_fails_unforeseen_costs_only_itself(self):
        real = S._clean_settings

        def fails_for_hi(settings):
            if isinstance(settings, dict) and settings.get("offer") == "hi":
                raise RuntimeError("nobody saw this coming")
            return real(settings)

        with mock.patch.object(S, "_clean_settings", side_effect=fails_for_hi):
            self.assertEqual([r["id"] for r in S.list_searches(self.folder)],
                             [self.A, self.B])

    def test_names_only_clash_with_searches_that_are_listed(self):
        self._save("Stringy")                      # only an unlisted entry has it
        with self.assertRaises(S.SavedSearchError):
            self._save("minimal ONE")


# ── atomic writes and threads ─────────────────────────────────────────────────

class WritesAreAtomic(_Folder):

    def test_no_temp_file_is_left_behind(self):
        a = self._save("A")
        b = self._save("B")
        S.rename(self.folder, a["id"], "A2")
        S.mark_run(self.folder, b["id"], SESSION, new_people=2)
        self._save("B", {"job_titles": {"include": ["COO"]}}, search_id=b["id"])
        S.delete(self.folder, a["id"])
        S.list_searches(self.folder)
        self.assertEqual(os.listdir(self.folder), [S.FILE])

    def test_a_failed_replace_keeps_the_previous_file(self):
        first = self._save("First")
        before = self._bytes()
        with mock.patch.object(S.os, "replace",
                               side_effect=PermissionError(13, "Access is denied")):
            with self.assertRaises(S.SavedSearchError) as caught:
                self._save("Second")
            with self.assertRaises(S.SavedSearchError):
                S.mark_run(self.folder, first["id"], SESSION, new_people=1)
        message = str(caught.exception)
        self.assertTrue(message.startswith("Couldn't save this search:"), message)
        self.assertIn("Access is denied", message)
        self.assertEqual(self._temps(), [])
        self.assertEqual(self._bytes(), before)
        self.assertEqual(S.list_searches(self.folder), [first])

    def test_a_folder_that_cannot_be_created_is_reported(self):
        with open(self.folder, "w", encoding="utf-8") as f:
            f.write("a file where the folder should be")
        with self.assertRaises(S.SavedSearchError):
            self._save()
        self.assertEqual(S.list_searches(self.folder), [])


class FourThreadsAtOnce(_Folder):

    def _run(self, work):
        start, errors = threading.Barrier(4), []

        def body(t):
            try:
                start.wait(10)
                work(t)
            except Exception as e:                          # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=body, args=(t,), name=f"saver-{t}")
                   for t in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])

    def test_concurrent_saves_keep_every_record(self):
        def work(t):
            for i in range(8):
                self._save(f"Thread {t} search {i}",
                           {"job_titles": {"include": [f"Title {t}-{i}"]}})

        self._run(work)
        records = S.list_searches(self.folder)
        self.assertEqual(sorted(r["name"] for r in records),
                         sorted(f"Thread {t} search {i}" for t in range(4) for i in range(8)))
        self.assertEqual(len({r["id"] for r in records}), 32)
        for record in records:
            t, i = record["name"].split()[1], record["name"].split()[3]
            self.assertEqual(record["filters"]["job_titles"]["include"], [f"Title {t}-{i}"])
        self.assertEqual(self._temps(), [])

    def test_concurrent_runs_are_all_counted(self):
        record = self._save()

        def work(t):
            for i in range(6):
                S.mark_run(self.folder, record["id"], f"2026091{t}-10000{i}-aaaaaa",
                           new_people=i)

        self._run(work)
        self.assertEqual(S.get(self.folder, record["id"])["runs"], 24)


if __name__ == "__main__":
    unittest.main()
