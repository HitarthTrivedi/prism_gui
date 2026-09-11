"""Leads & Outreach — the lead-filter panel (addons.leads.filter_panel).

Pure widget behaviour, no network, no disk: every edit a person can make —
include or exclude from a suggestion row, Enter, flip a chip, remove it, pick
seniority and function by label, tick bands (headcount, annual revenue, years
in the role), the similar-titles box and the changed-jobs switch — lands in
the SearchSpec the panel hands out, `changed` fires exactly once per edit, a
value is never on both sides, and a spec put in (the owner's "Global except
india" session) comes back out unchanged. Never shows a window and never runs
an event loop.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel              # noqa: E402

from prospector.filters import SearchSpec                       # noqa: E402
from addons.leads import filter_panel as FP                     # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

# The workbench's pre-filled ICP (addons/leads/workbench.py).
_INDUSTRIES = ["Automobile", "Auto Components", "Tyre", "Steel Manufacturing",
               "Die Casting", "Aerospace & MRO", "Defense",
               "Electrical & Electronics", "Warehousing & Logistics", "Mining"]
_ROLES = ["Head of Digital Transformation / Industry 4.0 / IIoT",
          "Automation Head / Smart Manufacturing",
          "Manufacturing Excellence / Operations / Production Head",
          "Business Excellence & Continuous Improvement",
          "Plant Head / Head of Manufacturing",
          "Supply Chain / Warehouse / Materials Head"]


def _owner_spec() -> SearchSpec:
    spec = SearchSpec.from_legacy({"industries": _INDUSTRIES, "roles": _ROLES,
                                   "location": "Global except india"})
    spec.seniority.include = ["head", "director"]
    spec.seniority.exclude = ["intern"]
    spec.headcount = ["1001-5000", "5001-10000"]
    return spec


class _Count:
    def __init__(self, signal):
        self.n = 0
        signal.connect(self._hit)

    def _hit(self, *_args):
        self.n += 1


class _PanelCase(unittest.TestCase):
    def setUp(self):
        self.p = FP.FilterPanel()
        self.changes = _Count(self.p.changed)

    def section(self, name):
        return self.p._sections[name]

    def editor(self, name):
        return self.section(name).editor

    def type_in(self, name, text):
        ed = self.editor(name)
        ed.input.setText(text)
        return ed

    def rows(self, name):
        return [(r.value, r.label) for r in self.editor(name).rows if not r.isHidden()]

    def chips(self, name):
        return self.section(name).chips.active()

    def chip_view(self, name):
        return [(c.label(), c.side) for c in self.chips(name)]


class IncludeExclude(_PanelCase):
    def test_exclude_from_a_suggestion_row(self):
        ed = self.type_in("locations", "India")
        self.assertEqual(self.rows("locations")[0], ("India", "India"))
        ed.rows[0].exclude_btn.click()
        spec = self.p.spec()
        self.assertEqual(spec.locations.exclude, ["India"])
        self.assertEqual(spec.locations.include, [])
        self.assertEqual(self.changes.n, 1)
        self.assertEqual(ed.input.text(), "")
        [chip] = self.chips("locations")
        self.assertEqual(chip.objectName(), "fchipExc")
        self.assertEqual(chip.toolTip(), "Excluded — click to include")

    def test_include_from_a_suggestion_row(self):
        ed = self.type_in("locations", "germ")
        rows = self.rows("locations")
        # "germ" is no place, so it is not offered as one: a raw chip would be
        # pasted into the Exa query and match nobody's location.
        self.assertNotIn(("germ", "germ"), rows)
        self.assertEqual(rows[0], ("Germany", "Germany"))
        ed.rows[rows.index(("Germany", "Germany"))].include_btn.click()
        self.assertEqual(self.p.spec().locations.include, ["Germany"])
        self.assertEqual(self.chip_view("locations"), [("Germany", "include")])
        self.assertEqual(self.chips("locations")[0].objectName(), "fchipInc")
        self.assertEqual(self.changes.n, 1)

    def test_typed_text_takes_the_listed_spelling(self):
        self.type_in("locations", "india")
        rows = self.rows("locations")
        self.assertEqual(rows[0], ("India", "India"))
        self.assertEqual([v for v, _ in rows if v.casefold() == "india"], ["India"])

    def test_enter_includes_the_first_row(self):
        ed = self.editor("job_titles")
        QTest.keyClicks(ed.input, "Plant Head")
        self.assertEqual(self.changes.n, 0)                   # typing is not an edit
        QTest.keyClick(ed.input, Qt.Key_Return)
        self.assertEqual(self.p.spec().job_titles.include, ["Plant Head"])
        self.assertEqual(self.changes.n, 1)
        self.assertEqual(ed.input.text(), "")

    def test_enter_on_an_empty_input_adds_nothing(self):
        for name in ("locations", "seniority"):
            QTest.keyClick(self.editor(name).input, Qt.Key_Return)
        self.assertEqual(self.p.active_count(), 0)
        self.assertEqual(self.changes.n, 0)


class PlacesAreRead(_PanelCase):
    """Location and Company HQ read what is typed. The owner's old habit —
    "Global except india" + Enter — used to become an INCLUDE chip of that
    sentence: India pasted back into the query, and nobody's location matched."""

    def enter(self, name, text):
        ed = self.type_in(name, text)
        QTest.keyClick(ed.input, Qt.Key_Return)
        return ed

    def test_global_except_india_and_enter_is_an_india_exclusion(self):
        ed = self.type_in("locations", "Global except india")
        self.assertEqual(self.rows("locations"), [])
        self.assertEqual(ed.hint.text(), "Press Enter for: Anywhere except India")
        QTest.keyClick(ed.input, Qt.Key_Return)
        spec = self.p.spec()
        self.assertEqual(spec.locations.to_dict(), {"include": [], "exclude": ["India"]})
        self.assertEqual(self.chip_view("locations"), [("India", "exclude")])
        self.assertEqual(self.changes.n, 1)
        self.assertEqual(ed.input.text(), "")
        # What a run then does with it: India is never asked for, and Dubai passes.
        from prospector import filters
        spec.job_titles.include = ["Plant Head"]
        spec.industries.include = ["Automobile"]
        queries = [q for _, q in filters.plan(spec)]
        self.assertTrue(queries)
        self.assertFalse([q for q in queries if "india" in q.casefold()])
        person = type("P", (), {"title": "Plant Head", "company": "Gulf Motors",
                                "extra": {"location": "Dubai, United Arab Emirates"}})()
        self.assertEqual(filters.match_person(spec, person), "")

    def test_other_ways_of_saying_it(self):
        for text in ("Anywhere but India", "Global (except India)", "Non-India",
                     "Global ex-India", "-india"):
            with self.subTest(text=text):
                self.p.clear()
                self.enter("company_hq", text)
                self.assertEqual(self.p.spec().company_hq.to_dict(),
                                 {"include": [], "exclude": ["India"]})

    def test_a_half_typed_place_takes_the_first_suggestion(self):
        self.enter("locations", "ger")
        self.assertEqual(self.p.spec().locations.include, ["Germany"])

    def test_a_known_place_leads_in_the_gazetteer_spelling(self):
        self.type_in("locations", "bombay")
        self.assertEqual(self.rows("locations")[0], ("Mumbai", "Mumbai"))

    def test_anywhere_adds_no_chip(self):
        for text in ("Anywhere", "Worldwide", "Global"):
            with self.subTest(text=text):
                ed = self.enter("locations", text)
                self.assertEqual(self.p.active_count(), 0)
                self.assertEqual(ed.input.text(), "")
        self.assertEqual(self.changes.n, 0)

    def test_text_that_is_no_place_adds_nothing_and_says_so(self):
        ed = self.enter("locations", "Xqzzy")
        self.assertEqual(self.p.active_count(), 0)
        self.assertEqual(self.changes.n, 0)
        self.assertEqual(ed.input.text(), "Xqzzy")               # left to correct
        self.assertEqual(ed.hint.text(), "Not a place Prism knows: Xqzzy")
        self.assertFalse(ed.hint.isHidden())

    def test_a_sentence_moves_an_included_place_to_excluded(self):
        self.p.set_spec({"locations": {"include": ["India", "Germany"]}})
        self.changes.n = 0
        self.enter("locations", "Germany except India")
        self.assertEqual(self.p.spec().locations.to_dict(),
                         {"include": ["Germany"], "exclude": ["India"]})
        self.assertEqual(self.changes.n, 1)                       # one edit, not two


class Chips(_PanelCase):
    def test_clicking_a_chip_flips_its_side(self):
        self.type_in("locations", "India")
        self.editor("locations").rows[0].include_btn.click()
        [chip] = self.chips("locations")
        self.assertEqual((chip.objectName(), chip.toolTip()),
                         ("fchipInc", "Included — click to exclude"))
        chip.click()
        self.assertEqual(self.p.spec().locations.to_dict(),
                         {"include": [], "exclude": ["India"]})
        self.assertEqual((chip.objectName(), chip.toolTip()),
                         ("fchipExc", "Excluded — click to include"))
        chip.click()
        self.assertEqual(self.p.spec().locations.to_dict(),
                         {"include": ["India"], "exclude": []})
        self.assertEqual(self.changes.n, 3)

    def test_the_x_removes_a_chip(self):
        self.p.set_spec({"locations": {"include": ["UAE"], "exclude": ["India"]}})
        self.changes.n = 0
        chips = self.chips("locations")
        self.assertEqual(self.chip_view("locations"),
                         [("UAE", "include"), ("India", "exclude")])
        chips[1]._x.click()
        self.assertEqual(self.p.spec().locations.to_dict(),
                         {"include": ["UAE"], "exclude": []})
        self.chips("locations")[0]._x.click()
        self.assertEqual(self.p.active_count(), 0)
        self.assertTrue(self.section("locations").chips.isHidden())
        self.assertEqual(self.changes.n, 2)

    def test_delete_on_a_chip_removes_it(self):
        self.p.set_spec({"keywords": {"exclude": ["recruiter"]}})
        QTest.keyClick(self.chips("keywords")[0], Qt.Key_Delete)
        self.assertEqual(self.p.spec().keywords.to_dict(), {"include": [], "exclude": []})
        self.assertEqual(self.changes.n, 2)

    def test_a_value_is_never_on_both_sides(self):
        self.p.set_spec({"locations": {"include": ["India", "UAE"], "exclude": ["india"]}})
        self.assertEqual(self.p.spec().locations.to_dict(),
                         {"include": ["UAE"], "exclude": ["india"]})
        self.changes.n = 0
        # A chosen value is not offered again, in any case, and Enter on it
        # adds nothing — least of all the next suggestion down.
        ed = self.type_in("locations", "INDIA")
        self.assertNotIn("india", [v.casefold() for v, _ in self.rows("locations")])
        QTest.keyClick(ed.input, Qt.Key_Return)
        self.assertEqual(self.changes.n, 0)
        self.chips("locations")[0].click()                     # UAE over to exclude
        loc = self.p.spec().locations
        self.assertEqual(loc.include, [])
        self.assertEqual(sorted(loc.exclude), ["UAE", "india"])

    def test_long_values_elide_instead_of_widening_the_rail(self):
        long = ("Head of Digital Transformation, Industry 4.0, IIoT and Smart "
                "Manufacturing Excellence Programmes")
        raw = _owner_spec().to_dict()
        raw["companies"] = {"include": [long]}
        self.p.set_spec(raw)
        [chip] = self.chips("companies")
        self.assertLessEqual(chip.sizeHint().width(), FP._RAIL_CONTENT)
        self.assertIn(long, chip.toolTip())
        # FlowLayout's minimum width is its widest item's minimum, and that
        # becomes the rail's — so neither a chip row nor a suggestion row may
        # ask for a long value's full width. (The panel's own minimum depends
        # on the fonts; the real-stylesheet render checks that.)
        for name in ("companies", "job_titles"):
            self.assertLessEqual(self.section(name).chips.minimumSizeHint().width(), 64, name)
        ed = self.type_in("keywords", long)
        row = ed.rows[0]
        self.assertLess(row._text.minimumSizeHint().width(), row._text.sizeHint().width())
        self.assertLessEqual(row._text.minimumSizeHint().width(), 24)


class ClosedFacets(_PanelCase):
    def test_an_empty_input_lists_the_options_by_label(self):
        ed = self.editor("seniority")
        rows = self.rows("seniority")
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0], ("owner", "Owner"))
        self.assertEqual(rows[2], ("c_suite", "C-suite"))
        self.assertFalse(ed.hint.isHidden())
        self.assertEqual(ed.hint.text(), "Type to filter")

    def test_typing_filters_prefix_first_and_the_spec_stores_keys(self):
        ed = self.type_in("functions", "man")
        labels = [label for _, label in self.rows("functions")]
        self.assertEqual(labels[0], "Manufacturing & Production")
        self.assertEqual(set(labels[1:]),
                         {"Human Resources", "Strategy & General Management"})
        ed.rows[0].include_btn.click()
        self.assertEqual(self.p.spec().functions.include, ["manufacturing"])
        self.assertEqual(self.chip_view("functions"),
                         [("Manufacturing & Production", "include")])

    def test_enter_picks_the_best_match_and_chosen_options_leave_the_list(self):
        ed = self.editor("seniority")
        QTest.keyClicks(ed.input, "dir")
        QTest.keyClick(ed.input, Qt.Key_Return)
        self.assertEqual(self.p.spec().seniority.include, ["director"])
        self.assertNotIn("director", [v for v, _ in self.rows("seniority")])
        self.type_in("seniority", "intern")
        ed.rows[0].exclude_btn.click()
        self.assertEqual(self.p.spec().seniority.exclude, ["intern"])
        self.assertEqual(self.chip_view("seniority"),
                         [("Director", "include"), ("Intern / Trainee", "exclude")])
        self.assertEqual(self.changes.n, 2)

    def test_no_match_says_so(self):
        ed = self.type_in("seniority", "zzz")
        self.assertEqual(self.rows("seniority"), [])
        self.assertEqual(ed.hint.text(), "No match")

    def test_closed_facets_never_ask_the_lookup(self):
        calls = []
        p = FP.FilterPanel(suggest=lambda facet, text: calls.append(facet) or ["Nonsense"])
        p._sections["seniority"].editor.input.setText("dir")
        p._sections["functions"].editor.input.setText("sales")
        self.assertEqual(calls, [])
        self.assertEqual(p._sections["seniority"].editor.values, ["director"])


class Bands(_PanelCase):
    def test_band_buttons_toggle_in_canonical_order(self):
        buttons = self.editor("headcount").buttons
        buttons["5001-10000"].click()
        buttons["1001-5000"].click()
        self.assertEqual(self.p.spec().headcount, ["1001-5000", "5001-10000"])
        self.assertTrue(buttons["1001-5000"].isChecked())
        self.assertEqual(buttons["1001-5000"].objectName(), "fband")
        self.assertEqual(buttons["1001-5000"].text(), "1,001-5,000")
        buttons["5001-10000"].click()
        self.assertEqual(self.p.spec().headcount, ["1001-5000"])
        self.assertFalse(buttons["5001-10000"].isChecked())
        self.assertEqual(self.changes.n, 3)

    def test_band_chips_show_labels_remove_but_never_flip(self):
        self.p.set_spec({"years_in_role": ["gt10", "lt1"]})
        self.changes.n = 0
        section = self.section("years_in_role")
        self.assertFalse(section.is_open())
        self.assertEqual(self.chip_view("years_in_role"),
                         [("Less than 1 year", "include"), ("More than 10 years", "include")])
        chip = self.chips("years_in_role")[0]
        chip.click()
        self.assertEqual(self.changes.n, 0)
        self.assertEqual(chip.toolTip(), "")
        chip._x.click()
        self.assertEqual(self.p.spec().years_in_role, ["gt10"])
        self.assertFalse(section.editor.buttons["lt1"].isChecked())
        self.assertTrue(section.editor.buttons["gt10"].isChecked())
        self.assertEqual(self.changes.n, 1)
        # Open, the checked buttons carry the choice, so the chips step aside.
        section.head.click()
        self.assertTrue(section.chips.isHidden())
        section.head.click()
        self.assertFalse(section.chips.isHidden())


class Revenue(_PanelCase):
    """Annual revenue, Sales Navigator's bands, right after Company headcount."""

    _KEYS = ["lt1m", "1m-10m", "10m-50m", "50m-100m", "100m-500m", "500m-1b", "gt1b"]
    _LABELS = ["Under $1M", "$1M-10M", "$10M-50M", "$50M-100M", "$100M-500M",
               "$500M-1B", "$1B+"]

    def test_the_section_follows_headcount_with_every_band(self):
        names = list(self.p._sections)
        self.assertEqual(names.index("revenue"), names.index("headcount") + 1)
        section = self.section("revenue")
        self.assertEqual(section.head._title.text(), "Annual revenue")
        self.assertFalse(section.is_open())
        self.assertTrue(section.head.badge.isHidden())
        buttons = self.editor("revenue").buttons
        self.assertEqual(list(buttons), self._KEYS)
        self.assertEqual([b.text() for b in buttons.values()], self._LABELS)
        for btn in buttons.values():
            self.assertEqual(btn.objectName(), "fband")
            self.assertTrue(btn.isCheckable())
            self.assertFalse(btn.isChecked())

    def test_toggling_bands_updates_the_spec_badges_and_chips(self):
        buttons = self.editor("revenue").buttons
        buttons["gt1b"].click()
        buttons["10m-50m"].click()
        spec = self.p.spec()
        self.assertEqual(spec.revenue, ["10m-50m", "gt1b"])          # canonical order
        self.assertEqual(spec.headcount, [])                         # its own facet
        self.assertEqual(self.changes.n, 2)
        self.assertEqual(self.section("revenue").head.badge.text(), "2")
        self.assertEqual(self.p._badge.text(), "2")
        self.assertFalse(self.p._clear_btn.isHidden())
        self.assertEqual(self.chip_view("revenue"),
                         [("$10M-50M", "include"), ("$1B+", "include")])
        buttons["gt1b"].click()
        self.assertEqual(self.p.spec().revenue, ["10m-50m"])
        self.assertFalse(buttons["gt1b"].isChecked())
        chip = self.chips("revenue")[0]
        chip.click()                                                 # a band never flips
        self.assertEqual(self.changes.n, 3)
        chip._x.click()
        self.assertEqual(self.p.spec().revenue, [])
        self.assertFalse(buttons["10m-50m"].isChecked())
        self.assertTrue(self.section("revenue").chips.isHidden())
        self.assertEqual(self.changes.n, 4)

    def test_set_spec_round_trips_and_clear_empties_it(self):
        raw = _owner_spec().to_dict()
        raw["revenue"] = ["gt1b", "$100M-500M", "nonsense"]
        self.p.set_spec(raw)
        self.assertEqual(self.p.spec().revenue, ["100m-500m", "gt1b"])
        buttons = self.editor("revenue").buttons
        self.assertEqual({k for k, b in buttons.items() if b.isChecked()},
                         {"100m-500m", "gt1b"})
        self.assertEqual(self.chip_view("revenue"),
                         [("$100M-500M", "include"), ("$1B+", "include")])
        self.assertEqual(self.chip_view("headcount"),
                         [("1,001-5,000", "include"), ("5,001-10,000", "include")])
        self.assertEqual(self.p.active_count(), 24)
        other = FP.FilterPanel()
        other.set_spec(self.p.spec())
        self.assertEqual(other.spec().to_dict(), self.p.spec().to_dict())
        self.assertEqual(other.spec().revenue, ["100m-500m", "gt1b"])
        # A spec saved before the facet existed opens with nothing chosen.
        legacy = _owner_spec().to_dict()
        del legacy["revenue"]
        other.set_spec(legacy)
        self.assertEqual(other.spec().revenue, [])
        self.assertEqual(other._sections["revenue"].chips.active(), [])
        self.p.clear()
        self.assertEqual(self.p.spec().revenue, [])
        self.assertFalse(any(b.isChecked() for b in buttons.values()))
        self.assertEqual(self.chips("revenue"), [])
        self.assertTrue(self.section("revenue").head.badge.isHidden())
        self.assertEqual(self.changes.n, 2)

    def test_size_bands_say_unknown_sizes_are_not_dropped(self):
        note = "Checked against the company's record · unknown sizes aren't dropped"
        for name in ("headcount", "revenue"):
            ed = self.editor(name)
            self.assertIsNotNone(ed.note, name)
            self.assertEqual(ed.note.text(), note, name)
            self.assertTrue(ed.note.wordWrap(), name)
        self.assertIsNone(self.editor("years_in_role").note)
        section = self.section("revenue")
        section.head.click()
        self.assertFalse(section.editor.isHidden())
        self.assertFalse(section.editor.note.isHidden())
        # The rail is ~280px of content: neither the bands nor the note may ask
        # for more.
        for name in ("headcount", "revenue"):
            self.assertLessEqual(self.editor(name).minimumSizeHint().width(),
                                 FP._RAIL_CONTENT, name)


class Switches(_PanelCase):
    def test_similar_titles_checkbox(self):
        box = self.p._similar
        self.assertTrue(box.isChecked())
        self.assertEqual(box.text(), "Include similar titles")
        self.assertIn("title must contain", box.toolTip())
        box.click()
        self.assertFalse(self.p.spec().similar_titles)
        self.assertEqual(self.changes.n, 1)
        self.assertEqual(self.p.active_count(), 0)            # a setting, not a value
        self.p.set_spec({"similar_titles": True})
        self.assertTrue(box.isChecked())

    def test_changed_jobs_switch_and_its_row(self):
        row = self.p._jobs
        self.assertIsInstance(row.switch, FP.C.ToggleSwitch)
        row.switch.click()
        self.assertTrue(self.p.spec().changed_jobs_90d)
        self.assertEqual(self.p.active_count(), 1)
        self.assertEqual(self.p._badge.text(), "1")
        self.assertFalse(self.p._badge.isHidden())
        row.click()                                           # the sentence is a target too
        self.assertFalse(self.p.spec().changed_jobs_90d)
        self.assertFalse(row.switch.isChecked())
        self.assertEqual(self.changes.n, 2)


class SpecInOut(_PanelCase):
    def test_the_owner_case_round_trips(self):
        spec = _owner_spec()
        self.p.set_spec(spec)
        self.assertEqual(self.changes.n, 1)
        self.assertEqual(self.p.spec().to_dict(), spec.to_dict())
        self.assertEqual(self.chip_view("locations"), [("India", "exclude")])
        self.assertEqual(len(self.chips("job_titles")), 6)
        self.assertEqual(len(self.chips("industries")), 10)
        self.assertEqual(self.chip_view("seniority"),
                         [("Head", "include"), ("Director", "include"),
                          ("Intern / Trainee", "exclude")])
        self.assertEqual(self.chip_view("headcount"),
                         [("1,001-5,000", "include"), ("5,001-10,000", "include")])
        self.assertEqual(self.section("industries").head.badge.text(), "10")
        self.assertEqual(self.p.active_count(), 22)
        self.assertEqual(self.p._badge.text(), "22")
        self.assertFalse(self.p._clear_btn.isHidden())
        # A dict goes in the same way, and what comes out is a copy.
        other = FP.FilterPanel()
        other.set_spec(spec.to_dict())
        self.assertEqual(other.spec().to_dict(), spec.to_dict())
        out = self.p.spec()
        out.locations.exclude.clear()
        self.assertEqual(self.p.spec().locations.exclude, ["India"])

    def test_set_spec_clears_half_typed_text(self):
        ed = self.type_in("locations", "ind")
        self.p.set_spec(_owner_spec())
        self.assertEqual(ed.input.text(), "")
        self.assertEqual(self.rows("locations"), [])
        self.assertEqual(self.changes.n, 1)

    def test_rubbish_in_is_an_empty_spec(self):
        self.p.set_spec(None)
        self.assertEqual(self.p.spec().to_dict(), SearchSpec().to_dict())
        self.assertEqual(self.changes.n, 1)

    def test_set_spec_and_clear_keep_what_is_open(self):
        self.section("locations").head.click()                # close
        self.section("seniority").head.click()                # open
        self.p.set_spec(_owner_spec())
        self.p.clear()
        self.assertFalse(self.section("locations").is_open())
        self.assertTrue(self.section("locations").editor.isHidden())
        self.assertTrue(self.section("seniority").is_open())
        self.assertTrue(self.section("job_titles").is_open())
        self.assertEqual(self.changes.n, 2)                   # opening is not an edit

    def test_clear_all_empties_everything(self):
        self.p.set_spec(_owner_spec())
        self.p._jobs.switch.click()
        self.p._similar.click()
        self.changes.n = 0
        self.p._clear_btn.click()
        self.assertEqual(self.changes.n, 1)
        self.assertEqual(self.p.spec().to_dict(), SearchSpec().to_dict())
        self.assertEqual(self.p.active_count(), 0)
        self.assertTrue(self.p._badge.isHidden())
        self.assertTrue(self.p._clear_btn.isHidden())
        for name, section in self.p._sections.items():
            self.assertEqual(section.chips.active(), [], name)
            self.assertTrue(section.head.badge.isHidden(), name)
        self.assertFalse(self.p._jobs.switch.isChecked())
        self.assertTrue(self.p._similar.isChecked())
        self.p.clear()                                        # the contract: once, always
        self.assertEqual(self.changes.n, 2)


class Layout(_PanelCase):
    def test_starts_empty_with_location_and_job_title_open(self):
        self.assertEqual(self.p.active_count(), 0)
        self.assertTrue(self.p._badge.isHidden())
        self.assertTrue(self.p._clear_btn.isHidden())
        self.assertEqual(list(self.p._sections),
                         ["locations", "job_titles", "seniority", "functions",
                          "industries", "headcount", "revenue", "companies", "company_hq",
                          "years_in_role", "keywords"])
        opened = {n for n, s in self.p._sections.items() if s.is_open()}
        self.assertEqual(opened, {"locations", "job_titles"})
        self.assertFalse(self.editor("locations").isHidden())
        self.assertTrue(self.editor("industries").isHidden())

    def test_a_header_click_opens_and_closes_without_an_edit(self):
        section = self.section("industries")
        section.head.click()
        self.assertFalse(section.editor.isHidden())
        section.head.click()
        self.assertTrue(section.editor.isHidden())
        self.assertEqual(self.changes.n, 0)

    def test_facet_badges_count_both_sides(self):
        self.p.set_spec({"locations": {"include": ["UAE", "Qatar"], "exclude": ["India"]}})
        self.assertEqual(self.section("locations").head.badge.text(), "3")
        self.assertFalse(self.section("locations").head.badge.isHidden())
        self.assertTrue(self.section("job_titles").head.badge.isHidden())
        self.assertEqual(self.p._badge.text(), "3")

    def test_chips_stay_visible_on_a_closed_facet(self):
        self.p.set_spec({"industries": {"include": ["Mining"]}})
        section = self.section("industries")
        self.assertFalse(section.is_open())
        self.assertFalse(section.chips.isHidden())
        self.assertEqual(self.chip_view("industries"), [("Mining", "include")])

    def test_copy_on_the_editors(self):
        self.assertEqual(self.editor("locations").input.placeholderText(),
                         "Add a country, region or city")
        self.assertEqual(self.editor("job_titles").input.placeholderText(),
                         "Add a job title")
        for name in ("industries", "keywords"):
            texts = [lab.text() for lab in self.editor(name).findChildren(QLabel)]
            self.assertIn("Include guides the search · Exclude is enforced", texts, name)
        texts = [lab.text() for lab in self.editor("locations").findChildren(QLabel)]
        self.assertNotIn("Include guides the search · Exclude is enforced", texts)


class Suggestions(unittest.TestCase):
    def test_a_custom_lookup_is_asked_and_chosen_values_are_filtered(self):
        calls = []

        def lookup(facet, text):
            calls.append((facet, text))
            return ["Acme Steel", "Acme Tyres", "acme steel", "", None]
        p = FP.FilterPanel(suggest=lookup)
        changes = _Count(p.changed)
        ed = p._sections["companies"].editor
        ed.input.setText("Acme Steel")
        self.assertEqual(ed.values[0], "Acme Steel")
        ed.rows[0].include_btn.click()
        ed.input.setText("acme")
        self.assertIn(("companies", "acme"), calls)
        self.assertEqual([r.value for r in ed.rows if not r.isHidden()], ["acme", "Acme Tyres"])
        self.assertEqual(changes.n, 1)

    def test_a_failing_lookup_still_offers_the_typed_text(self):
        def broken(facet, text):
            raise RuntimeError("offline")
        p = FP.FilterPanel(suggest=broken)
        ed = p._sections["keywords"].editor
        ed.input.setText("MES")
        self.assertEqual(ed.values, ["MES"])

    def test_set_suggest_swaps_the_lookup_and_redraws(self):
        p = FP.FilterPanel()
        ed = p._sections["industries"].editor
        ed.input.setText("ste")
        self.assertIn("Steel Manufacturing", ed.values)
        p.set_suggest(lambda facet, text: ["Stellantis supplier"])
        self.assertEqual(ed.values, ["ste", "Stellantis supplier"])
        p.set_suggest(None)
        self.assertIn("Steel Manufacturing", ed.values)

    def test_at_most_six_rows(self):
        p = FP.FilterPanel(suggest=lambda facet, text: [f"{text} {i}" for i in range(20)])
        ed = p._sections["keywords"].editor
        ed.input.setText("x")
        self.assertEqual(len([r for r in ed.rows if not r.isHidden()]), 6)
        self.assertEqual(ed.values[0], "x")

    def test_the_static_lists_prefix_first(self):
        self.assertEqual(FP.static_suggest("locations", "ind")[:2], ["India", "Indonesia"])
        heads = FP.static_suggest("job_titles", "head")
        self.assertTrue(heads[0].startswith("Head"))
        self.assertIn("Plant Head", heads)
        self.assertEqual(FP.static_suggest("company_hq", "ger")[:2], ["Germany", "Nigeria"])
        self.assertEqual(FP.static_suggest("companies", "acme"), [])

    def test_save_search_asks_and_is_not_an_edit(self):
        p = FP.FilterPanel()
        saves, changes = _Count(p.saveRequested), _Count(p.changed)
        p._save_btn.click()
        self.assertEqual((saves.n, changes.n), (1, 0))
        self.assertEqual(p._save_btn.objectName(), "fsave")


if __name__ == "__main__":
    unittest.main()
