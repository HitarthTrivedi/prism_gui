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


class RoomForTheLumiLauncher(unittest.TestCase):
    """The floating Ask-Lumi widget (a 56 px pill with the mascot on top) sat on
    top of "Discard" and half of "Start the work", which are pinned to the foot
    of the workbench, and on the last row of scrolling pages. Measured in the
    real window at max scroll, 1 Oct 2026."""

    def test_the_clearance_covers_the_pill_and_the_mascot(self):
        import theme
        self.assertGreaterEqual(theme.LAUNCHER_CLEARANCE, 56 + 36)

    def test_pages_leave_that_room_under_their_last_row(self):
        import theme
        from widgets.panel_base import Page

        class _P(Page):
            TITLE = "t"
            def build(self):
                pass
        page = _P({})
        margins = page._scroll.widget().layout().contentsMargins()
        self.assertGreaterEqual(margins.bottom(),
                                theme.PAGE_PAD + theme.LAUNCHER_CLEARANCE)


if __name__ == "__main__":
    unittest.main()
