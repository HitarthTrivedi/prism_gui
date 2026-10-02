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
        self.assertGreaterEqual(theme.LAUNCHER_CLEARANCE, 56 + 64)

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


    def test_home_leaves_that_room_too(self):
        """Home built its own scroll column with `PAGE_PAD + 40`, so at maximum
        scroll "Browse Add-ons" and "Explore all" sat under the mascot (seen in
        the real window, 2 Oct 2026). Built against a temporary home so the
        panel cannot read the developer's own runs."""
        import tempfile
        from unittest import mock
        import paths
        import theme
        from widgets.home_panel import HomePanel
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(paths, "user_dir", lambda *a, **k: tmp):
            panel = HomePanel({})
            margins = panel._col.contentsMargins()
            self.assertGreaterEqual(margins.bottom(),
                                    theme.PAGE_PAD + theme.LAUNCHER_CLEARANCE)
            panel.deleteLater()


class EmailSetupFieldsAreTallEnough(unittest.TestCase):
    """The Email account dialog clipped the bottom of every field's text
    (22 px fields for 18 px text with 6 px padding): it has no explicit size,
    so it was sized before the stylesheet padding applied. Seen in the real
    window, 1 Oct 2026."""

    def test_each_field_has_a_real_minimum_height(self):
        import theme
        from addons.email.dialog import EmailSetupDialog
        dlg = EmailSetupDialog({"email": {}}, None)
        for edit in (dlg.addr_edit, dlg.pass_edit, dlg.host_edit, dlg.port_edit):
            self.assertGreaterEqual(edit.minimumHeight(), theme.BTN_HEIGHT_MD)
        dlg.reject()


class InquiryTablesShareTheSlack(unittest.TestCase):
    """The to-quote table sized "Qty" to its longest value
    ("5000 nos (monthly, ongoing)") and left Customer cut to "Shreeji A…".
    Seen in the real window, 1 Oct 2026."""

    def test_several_columns_stretch_and_a_long_one_is_capped(self):
        from PySide6.QtWidgets import QHeaderView
        from addons.inquiry.dialog import InquiryDialog
        t = InquiryDialog._make_table(["No", "Customer", "What", "Qty"],
                                      stretch=(1, 2), fit=(0,), fixed={3: 120})
        head = t.horizontalHeader()
        self.assertEqual(head.sectionResizeMode(1), QHeaderView.Stretch)
        self.assertEqual(head.sectionResizeMode(2), QHeaderView.Stretch)
        self.assertEqual(head.sectionResizeMode(0), QHeaderView.ResizeToContents)
        self.assertEqual(head.sectionResizeMode(3), QHeaderView.Interactive)
        self.assertEqual(head.sectionSize(3), 120)

    def test_a_single_stretch_column_still_works(self):
        from PySide6.QtWidgets import QHeaderView
        from addons.inquiry.dialog import InquiryDialog
        t = InquiryDialog._make_table(["a", "b"], stretch=1)
        self.assertEqual(t.horizontalHeader().sectionResizeMode(1), QHeaderView.Stretch)


if __name__ == "__main__":
    unittest.main()
