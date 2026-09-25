"""The Leads & Outreach help panel (addons.leads.help).

The Alphakore team could not tell which buttons on the Leads screen spend
money, so the "?" in the page header exists to say so. These tests hold that
promise to the copy and to the panel: every section has a heading and prose
under it, the cost section names Groq, Exa and the Apollo credit by name, the
header's "?" opens the panel and it closes again, the body scrolls rather than
growing, and the whole thing fits inside the owner's 1536x830 window at 125%
scaling — checked on the size hints, because a test must never show a window.

Reading it was not enough on its own, so the panel now leads with "Show me on
screen": the walkthrough in addons/leads/tour.py, which rings each control in
turn. Those tests are here too — the button shuts the panel before it asks,
because the tour would otherwise open behind it.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                  # noqa: E402
from PySide6.QtGui import QKeySequence, QShortcut              # noqa: E402
from PySide6.QtWidgets import (                                # noqa: E402
    QApplication, QLabel, QScrollArea,
)

from addons.leads import help as H                             # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

# The owner's own window: 1536x830 at 125% display scaling. The hints are
# checked WITH the scale applied, which is stricter than the window really is —
# a panel that fits under that has room left at every size he runs.
SCALE = 1.25
SCREEN_W, SCREEN_H = 1536, 830


def _labels(widget) -> list:
    return [w.text() for w in widget.findChildren(QLabel)]


class TheCopy(unittest.TestCase):
    def test_every_section_has_a_title_and_a_body(self):
        self.assertGreaterEqual(len(H.SECTIONS), 5)
        for entry in H.SECTIONS:
            self.assertEqual(len(entry), 2, entry)
            title, body = entry
            self.assertTrue(title.strip(), entry)
            self.assertLess(len(title), 40, title)      # a heading, not a line
            self.assertGreater(len(body.strip()), 60, title)

    def test_the_page_names_import_and_the_one_button_that_spends(self):
        body = dict(H.SECTIONS)["The page"]
        self.assertIn("Import", body)
        self.assertIn("Nothing is searched", body)      # an import never spends
        self.assertIn("Find new people", body)
        self.assertIn("the one button that spends", body)

    def test_the_costs_are_in_credits_and_name_no_vendor(self):
        """Leads runs on the Prism credit pool (23-Sep-2026): the customer
        holds no Exa, Groq, Apollo or Hunter key, so the section that says
        what each thing costs speaks in credits and names none of them. It
        says what a search, an address and a qualify each cost, and where the
        balance and the price list are."""
        body = dict(H.SECTIONS)["What each thing costs"]
        self.assertIn("credit", body)
        for vendor in ("Groq", "Exa", "Apollo", "Hunter"):
            self.assertNotIn(vendor, body, vendor)
        for thing in ("Find new people", "Find e-mails", "Qualify and draft"):
            self.assertIn(thing, body, thing)
        self.assertIn("per search", body)
        self.assertIn("finds nobody is not charged", body)
        self.assertIn("Click your balance", body)
        self.assertIn("ask Alphakore for a plan or a top-up", " ".join(body.split()))

    def test_a_paid_thing_is_never_called_free(self):
        """The panel that exists to stop an accidental spend once said "Find
        people is free on Apollo" — one press could bill 300 credits while
        the help said nothing. Any line that says free must be about what
        really is free here: filtering, sorting, paging, Import, Save, Send."""
        body = dict(H.SECTIONS)["What each thing costs"]
        for line in body.split("\n"):
            if "free" in line.lower():
                for paid in ("Find new people", "Find e-mails", "Qualify"):
                    self.assertNotIn(paid, line.split("free")[0], line)

    def test_the_filters_separate_steering_from_enforcing(self):
        body = dict(H.SECTIONS)["The filters"]
        self.assertIn("steer", body)
        self.assertIn("Only find people no earlier search found", body)
        for facet in ("Industry", "Keywords", "Location", "Job title",
                      "Seniority", "Function", "Company headcount",
                      "Annual revenue", "Current company",
                      "Company HQ location", "Years in current role",
                      "Contact CSV import",
                      "Account CSV import"):
            self.assertIn(facet, body, facet)
        for tab in ("Total", "Net New", "Saved"):
            self.assertIn(tab, body, tab)

    def test_a_day_is_listed_in_order(self):
        body = dict(H.SECTIONS)["How a day goes"]
        where = [body.index(step) for step in
                 ("Import a sheet", "Find new people", "Tick", "Find e-mails",
                  "Qualify and draft", "Read every draft", "Send.")]
        self.assertEqual(where, sorted(where))

    def test_the_copy_survives_the_string_extractor(self):
        # _is_copy() drops anything that looks like a stylesheet or markup, and
        # a dropped body ships untranslatable. Cheaper to assert than to debug.
        for title, body in H.SECTIONS:
            for text in (title, body):
                self.assertNotIn(";", text, text[:40])
                self.assertNotIn("<", text, text[:40])
                self.assertNotIn("{", text, text[:40])

    def test_a_bullet_line_splits_into_marker_and_sentence(self):
        self.assertEqual(H._marker("• Lists holds the sheets"),
                         ("•", "Lists holds the sheets"))
        self.assertEqual(H._marker("3. Tick the ones you want"),
                         ("3.", "Tick the ones you want"))
        self.assertEqual(H._marker("A plain sentence"), ("", "A plain sentence"))


class ThePanel(unittest.TestCase):
    def setUp(self):
        self.h = H.LeadsHelp()

    def test_it_builds_every_section_onto_the_screen(self):
        drawn = "\n".join(_labels(self.h))
        for title, body in H.SECTIONS:
            self.assertIn(title, drawn)
            # A marker is drawn in its own label, so the sentence after it is
            # what the section's first line becomes on screen.
            for line in body.split("\n"):
                self.assertIn(H._marker(line)[1], drawn)

    def test_it_starts_shut(self):
        self.assertFalse(self.h.is_open())

    def test_open_and_close(self):
        self.h.open_panel()
        self.assertTrue(self.h.is_open())
        seen = []
        self.h.closed.connect(lambda: seen.append(1))
        self.h.close_panel()
        self.assertFalse(self.h.is_open())
        self.assertEqual(seen, [1])              # the opener gets its focus back

    def test_toggle_goes_both_ways(self):
        self.h.toggle()
        self.assertTrue(self.h.is_open())
        self.h.toggle()
        self.assertFalse(self.h.is_open())

    def test_escape_closes_it(self):
        keys = [s.key() for s in self.h.findChildren(QShortcut)]
        self.assertIn(QKeySequence(Qt.Key_Escape), keys)

    def test_the_body_scrolls(self):
        scrolls = self.h.findChildren(QScrollArea)
        self.assertEqual(len(scrolls), 1)
        scroll = scrolls[0]
        self.assertTrue(scroll.widgetResizable())
        self.assertEqual(scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        # There is more copy than panel — which is the point of the scroll area.
        inner = scroll.widget()
        inner.resize(self.h.WIDTH, inner.sizeHint().height())
        self.assertGreater(inner.sizeHint().height(), self.h.sizeHint().height())

    def test_it_fits_the_owners_window_at_125_percent(self):
        for hint in (self.h.sizeHint(), self.h.minimumSizeHint()):
            self.assertLessEqual(hint.width() * SCALE, SCREEN_W, hint)
            self.assertLessEqual(hint.height() * SCALE, SCREEN_H, hint)
        # And it leaves the table behind it worth looking at: under half the
        # logical width of that window.
        self.assertLess(self.h.WIDTH, (SCREEN_W / SCALE) / 2)

    def test_place_pins_it_to_the_right_edge_of_its_parent(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.resize(1200, 600)
        panel = H.LeadsHelp(host)
        panel.open_panel()
        self.assertEqual(panel.geometry().right(), host.width() - 1)
        self.assertEqual(panel.height(), host.height())
        self.assertEqual(panel.width(), panel.WIDTH)

    def test_it_leads_with_show_me_on_screen(self):
        self.assertTrue(self.h.tour_btn.text())
        self.assertEqual(self.h.tour_btn.objectName(), "primaryBtn")

    def test_the_button_shuts_the_panel_and_asks_for_the_tour(self):
        asked = []
        self.h.tourRequested.connect(lambda: asked.append(self.h.is_open()))
        self.h.open_panel()
        self.h.tour_btn.click()
        self.assertEqual(asked, [False])     # shut BEFORE the tour is started
        self.assertFalse(self.h.is_open())

    def test_a_narrow_parent_never_makes_it_wider_than_the_parent(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.resize(340, 400)
        panel = H.LeadsHelp(host)
        panel.place()
        self.assertLessEqual(panel.width(), host.width())


class FromTheHeader(unittest.TestCase):
    """The "?" in the page header — the only way anyone will find this."""

    def _panel(self):
        from addons.leads.panel import LeadsPanel
        return LeadsPanel({})

    def test_the_help_action_is_first_and_labelled(self):
        p = self._panel()
        self.assertIs(p.header.actions_row.itemAt(0).widget(), p.help_btn)
        self.assertTrue(p.help_btn.accessibleName())     # not a mystery glyph
        self.assertIn("F1", p.help_btn.toolTip())
        self.assertEqual(p.help_btn.focusPolicy(), Qt.StrongFocus)

    def test_the_other_header_actions_are_still_there(self):
        p = self._panel()
        p._build()                                        # what showEvent does
        # "?", then the workbench's own Export sheets and Send all. (The "AI tools"
        # button that used to sit between them was dropped from the header, 788c29a.)
        self.assertEqual(p.header.actions_row.count(), 3)

    def test_clicking_it_opens_the_panel_and_clicking_again_shuts_it(self):
        p = self._panel()
        self.assertIsNone(p._help)                        # nothing built at rest
        p.help_btn.click()
        self.assertTrue(p._help.is_open())
        self.assertIs(p._help.parentWidget(), p._body)     # over the workbench
        p.help_btn.click()
        self.assertFalse(p._help.is_open())

    def test_f1_opens_it_too(self):
        p = self._panel()
        keys = [s.key() for s in p.findChildren(QShortcut)]
        self.assertIn(QKeySequence(Qt.Key_F1), keys)

    def test_a_resize_re_places_an_open_panel(self):
        p = self._panel()
        p.resize(1228, 664)
        p.toggle_help()
        p.resize(900, 600)
        self.assertEqual(p._help.geometry().right(), p._body.width() - 1)

    def test_nothing_is_built_until_it_is_asked_for(self):
        p = self._panel()
        self.assertIsNone(p._tour)

    def test_show_me_on_screen_starts_the_walkthrough(self):
        from addons.leads.tour import Tour
        p = self._panel()
        p.resize(1228, 664)
        p.help_btn.click()                       # the panel is open over the body
        p.help_panel().tour_btn.click()
        self.assertFalse(p._help.is_open())      # ...and out of the way
        self.assertIsInstance(p._tour, Tour)
        self.assertIs(p._tour.parentWidget(), p._body)
        p._tour.leave()

    def test_start_tour_can_be_called_before_the_screen_is_ever_shown(self):
        # It builds the workbench itself: a tour with nothing to point at
        # would end on its first step.
        p = self._panel()
        p.resize(1228, 664)
        p.start_tour()
        self.assertIsNotNone(p._workbench)
        p._tour.leave()

    def test_starting_it_twice_does_not_stack_two_overlays(self):
        from addons.leads.tour import Tour
        p = self._panel()
        p.resize(1228, 664)
        p.start_tour()
        p.start_tour()
        self.assertEqual(len(p._body.findChildren(Tour)), 1)
        p._tour.leave()


if __name__ == "__main__":
    unittest.main()
