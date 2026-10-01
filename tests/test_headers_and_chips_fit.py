"""Two layout defects found by walking every screen of the real app at its
default width (1 Oct 2026), pinned here.

  · PageHeader's subtitle did not wrap, so on Inquiry, Email, Gerber, STEP, BOM
    and Leads it was cut mid-word ("...not gue") and the buttons beside it were
    squeezed ("Export shee").
  · FilterChips was a one-line row. AI tools gives it eleven categories, which
    reported a 742 px minimum width, forced the page's scroll content wider than
    its viewport and clipped the right-hand column of cards (horizontal scroll
    is off by design).
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import widgets.controls as C  # noqa: E402

_app = QApplication.instance() or QApplication([])


class PageHeaderSubtitle(unittest.TestCase):
    def test_a_long_subtitle_wraps_instead_of_forcing_its_whole_width(self):
        long = ("Find, qualify and reach the right people — Prism drafts, "
                "you send. " * 4)
        header = C.PageHeader("Leads & Outreach", long, [C.button("Export sheets")])
        self.assertTrue(header.subtitle.wordWrap())
        # The minimum width must not be the whole sentence.
        self.assertLess(header.minimumSizeHint().width(), 600)


class FilterChipsFit(unittest.TestCase):
    def test_many_chips_do_not_demand_one_long_row(self):
        names = ["All", "Research", "Leads", "Reasoning", "Writing", "Audio",
                 "Images", "Video", "Apps", "Decks", "Final summary"]
        chips = C.FilterChips([(n.lower(), n) for n in names], "all")
        self.assertLess(chips.minimumSizeHint().width(), 400,
                        "eleven chips must wrap, not set a 700px minimum")

    def test_selection_still_works_after_wrapping(self):
        chips = C.FilterChips([("a", "A"), ("b", "B"), ("c", "C")], "a")
        seen = []
        chips.changed.connect(seen.append)
        chips._buttons["b"].click()
        self.assertEqual(chips.current(), "b")
        self.assertEqual(seen, ["b"])


if __name__ == "__main__":
    unittest.main()
