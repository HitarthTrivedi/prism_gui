"""The Leads & Outreach workspace (addons.leads.cockpit).

Pure widget behaviour — no pipeline, no workers, no network. Feeds the cockpit
qualified dossiers and checks the things it exists to get right: it shows every
lead, the fit slider and status filter hide rows, ticking rows arms the bulk bar
and the *Requested signals carry exactly the checked (visible) leads, and the
deliverability status is read correctly per lead. Then the surrounding
`LeadsWorkspace`: its six tabs, that it re-exposes the cockpit's signals and
set_dossiers, that Analytics counts this run, and that Lists scans a real folder.
Last, the workbench around it: the lead filters in the rail, what a Find-people
run hands its worker, and saved searches — save, use, delete, and a run counted.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt         # noqa: E402
from PySide6.QtGui import QMouseEvent, QShowEvent              # noqa: E402
from PySide6.QtTest import QTest                               # noqa: E402
from PySide6.QtWidgets import (                                # noqa: E402
    QAbstractItemView, QApplication, QHeaderView, QWidget,
)

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector.models import Dossier, Lead                    # noqa: E402
from addons.leads import cockpit as CK                         # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _dos(name, fit, email="", check="", signal="none", company="Acme"):
    lead = Lead(name=name, title="Founder", company=company, email=email,
                fit_score=fit, fit_reason="matches automation")
    lead.extra = {"email_check": check} if check else {}
    return Dossier(lead=lead, verdict="warm", score=int(fit),
                   signal_status=signal, opener=f"Hi {name}")


class StatusReading(unittest.TestCase):
    def test_every_status_maps(self):
        self.assertEqual(CK.status_of(_dos("A", 90, "a@x.com", "valid")), "Verified")
        self.assertEqual(CK.status_of(_dos("B", 80, "b@x.com", "")), "Guessed")
        self.assertEqual(CK.status_of(_dos("C", 70, "c@x.com", "catch-all")), "Catch-all")
        self.assertEqual(CK.status_of(_dos("D", 60, "d@x.com", "invalid")), "Invalid")
        self.assertEqual(CK.status_of(_dos("E", 50, "")), "No email")

    def test_a_sent_draft_reads_mailed(self):
        d = _dos("F", 70, "f@x.com", "valid")
        draft = type("Dr", (), {"dossier": d, "status": "sent", "body": "hi"})()
        self.assertEqual(CK.status_of(d, draft), "Mailed")


class CockpitBehaviour(unittest.TestCase):
    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.d3 = _dos("NoMail", 60, "")
        self.d4 = _dos("Bad", 40, "b@x.com", "invalid")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2, self.d3, self.d4])

    def _find(self, dos):
        for r in range(self.c._table.rowCount()):
            if self.c._dossier_at(r) is dos:
                return r
        return -1

    def test_all_leads_shown(self):
        self.assertEqual(self.c._table.rowCount(), 4)
        self.assertIn("4 of 4", self.c._count_lbl.text())

    def test_counters(self):
        self.assertEqual(self.c._c_new._num.text(), "4")    # none mailed yet
        self.assertEqual(self.c._c_fit._num.text(), "69")   # (96+80+60+40)/4 = 69

    def test_fit_slider_hides_low_rows(self):
        self.c._fit_min.setValue(70)
        vis = [r for r in range(self.c._table.rowCount())
               if not self.c._table.isRowHidden(r)]
        names = {self.c._dossier_at(r).lead.name for r in vis}
        self.assertEqual(names, {"Kunyi", "Vaibhav"})
        self.assertIn("2 of 4", self.c._count_lbl.text())

    def test_status_filter_hides(self):
        self.c._status_boxes["Invalid"].setChecked(False)
        r = self._find(self.d4)
        self.assertTrue(self.c._table.isRowHidden(r))

    def test_check_arms_bulk_and_selects(self):
        self.assertFalse(self.c._b_seq.isEnabled())
        r = self._find(self.d1)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.assertTrue(self.c._b_seq.isEnabled())
        self.assertIn("1 selected", self.c._sel_lbl.text())
        self.assertEqual(self.c.selected(), [self.d1])

    def test_sequence_signal_carries_checked(self):
        got = []
        self.c.sequenceRequested.connect(got.append)
        r = self._find(self.d2)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.c._b_seq.click()
        self.assertEqual(got, [[self.d2]])

    def test_hidden_checked_rows_are_not_selected(self):
        r = self._find(self.d4)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)   # check the invalid one
        self.c._fit_min.setValue(70)                          # now hidden (fit 40)
        self.assertEqual(self.c.selected(), [])               # excluded while hidden

    def test_drawer_renders_on_select(self):
        r = self._find(self.d1)
        self.c._table.setCurrentCell(r, 1)
        # the drawer inner layout has real content (more than just the stretch)
        self.assertGreater(self.c._drawer_lay.count(), 3)


class LayoutStates(unittest.TestCase):
    """The shapes that stop the screen crushing on a short window: an empty
    state instead of an empty grid, a drawer that only opens for a picked lead
    (and closes on ✕), and a rail slot the workbench mounts its search into."""

    def test_empty_cockpit_shows_the_empty_state_not_a_grid(self):
        c = CK.LeadsCockpit()
        self.assertEqual(c._view_stack.currentIndex(), 2)
        self.assertTrue(c._toolbar.isHidden())
        self.assertTrue(c._bulk.isHidden())

    def test_loading_leads_leaves_the_empty_state(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("A", 90, "a@x.com", "valid")])
        self.assertEqual(c._view_stack.currentIndex(), 0)
        self.assertFalse(c._toolbar.isHidden())
        # The bulk bar waits for a tick now: "0 selected" over five dead
        # buttons was the heaviest thing on the screen.
        self.assertTrue(c._bulk.isHidden())
        c._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertFalse(c._bulk.isHidden())

    def test_drawer_stays_shut_until_a_lead_is_picked(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("A", 90, "a@x.com", "valid"),
                        _dos("B", 80, "b@x.com", "")])
        self.assertTrue(c._drawer_w.isHidden())
        c._table.setCurrentCell(0, 1)
        self.assertFalse(c._drawer_w.isHidden())
        c._dismiss_drawer()
        self.assertTrue(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), -1)

    def test_search_panel_mounts_in_the_rail(self):
        c = CK.LeadsCockpit()
        panel = QWidget()
        c.set_search_panel(panel)
        self.assertIs(panel.parentWidget(), c._rail.widget())


class TableFeel(unittest.TestCase):
    """The table the owner works through, on any platform style: checkboxes it
    paints itself (row and select-all), no stray sort arrow, per-pixel
    scrolling, columns and panes that resize and keep their widths, a bulk bar
    that waits for a tick, and the keys a list needs. No event loop: events are
    sent straight to the widgets, and layouts are run by hand."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.d3 = _dos("NoMail", 60, "")
        self.d4 = _dos("Bad", 40, "b@x.com", "invalid")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2, self.d3, self.d4])

    def _row(self, dos):
        for r in range(self.c._table.rowCount()):
            if self.c._dossier_at(r) is dos:
                return r
        return -1

    @staticmethod
    def _mouse(widget, pos, kind=QEvent.MouseButtonPress):
        QApplication.sendEvent(widget, QMouseEvent(
            kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def _click_header_box(self):
        head = self.c._head
        self._mouse(head.viewport(),
                    QPoint(head.sectionSize(CK._C_TICK) // 2, CK._HEAD_H // 2))

    def _lay_out(self, width, height):
        """A real size with no event loop: resize, run each layout, then the
        splitter, all synchronously."""
        c = self.c
        c.resize(width, height)
        c.layout().activate()
        c._body.layout().activate()
        c._split.refresh()

    def test_the_header_checkbox_ticks_only_visible_rows_and_shows_partial(self):
        c = self.c
        c._fit_min.setValue(70)                       # NoMail (60) and Bad (40) hide
        self._click_header_box()
        self.assertEqual(c.selected(), [self.d1, self.d2])
        self.assertEqual(c._checked, {0, 1})          # the hidden rows stay unticked
        self.assertEqual(c._table.item(self._row(self.d3), 0).checkState(), Qt.Unchecked)
        self.assertEqual(c._head.check_state(), Qt.Checked)
        c._fit_min.setValue(0)                        # all four show, two ticked
        self.assertEqual(c._head.check_state(), Qt.PartiallyChecked)
        self._click_header_box()                      # some → all
        self.assertEqual(len(c.selected()), 4)
        self.assertEqual(c._head.check_state(), Qt.Checked)
        self._click_header_box()                      # all → none
        self.assertEqual(c.selected(), [])
        self.assertEqual(c._head.check_state(), Qt.Unchecked)

    def test_a_click_anywhere_in_the_tick_cell_ticks_without_opening_the_drawer(self):
        c = self.c
        rect = c._table.visualRect(c._table.model().index(self._row(self.d2), 0))
        # The cell's far edges, well off the box: a platform indicator only
        # answers on itself, and the owner could see no box to aim at.
        for spot, want in ((QPoint(rect.right() - 2, rect.center().y()), [self.d2]),
                           (QPoint(rect.left() + 2, rect.bottom() - 2), [])):
            self._mouse(c._table.viewport(), spot)
            self._mouse(c._table.viewport(), spot, QEvent.MouseButtonRelease)
            self.assertEqual(c.selected(), want)
            self.assertTrue(c._drawer_w.isHidden())
            self.assertEqual(c._table.currentRow(), -1)

    def test_space_ticks_the_current_row_and_esc_closes_the_drawer(self):
        c = self.c
        c._table.setCurrentCell(self._row(self.d3), 1)
        self.assertFalse(c._drawer_w.isHidden())
        QTest.keyClick(c._table, Qt.Key_Space)
        self.assertEqual(c.selected(), [self.d3])
        QTest.keyClick(c._table, Qt.Key_Space)
        self.assertEqual(c.selected(), [])
        QTest.keyClick(c._table, Qt.Key_Escape)
        self.assertTrue(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), -1)

    def test_the_sort_arrow_never_shows(self):
        c = self.c
        self.assertFalse(c._head.isSortIndicatorShown())
        self.assertFalse(c._table.isSortingEnabled())    # live sorting re-showed it
        c._sort.setCurrentIndex(1)
        c.set_dossiers([self.d2, self.d1])
        self.assertFalse(c._head.isSortIndicatorShown())
        self.assertEqual(c._dossier_at(0), self.d1)       # Name A–Z still sorts

    def test_scrolling_is_per_pixel_in_small_steps(self):
        c = self.c
        self.assertEqual(c._table.verticalScrollMode(), QAbstractItemView.ScrollPerPixel)
        self.assertEqual(c._table.horizontalScrollMode(), QAbstractItemView.ScrollPerPixel)
        self.assertEqual(c._table.verticalScrollBar().singleStep(), CK._STEP)
        self.assertEqual(c._gallery.verticalScrollBar().singleStep(), CK._STEP)
        self.assertEqual(c._table.verticalHeader().defaultSectionSize(), CK._ROW_H)

    def test_the_rail_and_the_results_share_a_splitter_within_bounds(self):
        c = self.c
        self.assertIs(c._split.widget(0), c._rail)
        self.assertIs(c._split.widget(1), c._center_w)
        self.assertEqual((c._rail.minimumWidth(), c._rail.maximumWidth()),
                         (CK._RAIL_MIN, CK._RAIL_MAX))
        self._lay_out(1700, 900)
        self.assertEqual(c._split.sizes()[0], CK._RAIL_W)
        c._split.moveSplitter(900, 1)                     # drag the rail's edge far right
        self.assertEqual(c._split.sizes()[0], CK._RAIL_MAX)
        self.assertEqual(c._rail_pref, CK._RAIL_MAX)      # remembered for a fold
        c._split.moveSplitter(100, 1)                     # and far left
        self.assertEqual(c._split.sizes()[0], CK._RAIL_MIN)
        c._split.setSizes([400, 1300])
        c.set_dossiers([self.d1, self.d2])                # a new run keeps the width
        c._split.refresh()
        self.assertEqual(c._split.sizes()[0], 400)

    def test_hide_filters_folds_the_rail_and_restores_its_width(self):
        c = self.c
        self._lay_out(1700, 900)
        c._split.setSizes([410, 1290])
        c._on_split_moved(410, 1)                         # what a drag reports
        c._filters_btn.click()
        self.assertTrue(c._rail.isHidden())
        self.assertEqual(c._filters_btn.text(), "Show filters")
        self.assertEqual(c._split.sizes()[0], 0)
        c._filters_btn.click()
        self.assertFalse(c._rail.isHidden())
        self.assertEqual(c._filters_btn.text(), "Hide filters")
        self.assertEqual(c._split.sizes()[0], 410)

    def test_the_bulk_bar_waits_for_a_tick_and_offers_select_all_and_clear(self):
        c = self.c
        self.assertTrue(c._bulk.isHidden())
        c._table.item(self._row(self.d1), 0).setCheckState(Qt.Checked)
        self.assertFalse(c._bulk.isHidden())
        self.assertEqual(c._bulk.maximumHeight(), CK._QMAX)     # landed, not mid-slide
        self.assertFalse(c._sel_all.isHidden())
        self.assertEqual(c._sel_all.text(), "Select all 4")
        c._sel_all.click()
        self.assertEqual(len(c.selected()), 4)
        self.assertTrue(c._sel_all.isHidden())                  # nothing left to add
        c._bulk_clear.click()
        self.assertEqual(c.selected(), [])
        self.assertTrue(c._bulk.isHidden())
        self.assertTrue(all(c._table.item(r, 0).checkState() == Qt.Unchecked
                            for r in range(c._table.rowCount())))

    def test_clear_and_select_all_actually_look_disabled_while_a_run_holds_them(self):
        # Live report, 22-Sep-2026: a customer pressed "Clear" while a
        # background search held the bulk bar disabled (workbench._set_running
        # disables cockpit.leads._bulk for exactly this reason) and nothing
        # happened -- correctly, the bar really was off-limits mid-run -- but
        # "Clear" and "Select all" are QPushButton#bulkLink, a MORE SPECIFIC
        # selector than the bar's plain "QPushButton:disabled" rule, so
        # without a "#bulkLink:disabled" rule of its own they kept rendering
        # in the same clickable accent-blue regardless of setEnabled(False).
        # A customer had no way to tell a dead-looking click from a real bug.
        c = self.c
        qss = c._bulk_bar_w.styleSheet()
        self.assertIn("QPushButton#bulkLink:disabled", qss)

    def test_a_narrow_bulk_bar_folds_again_every_time_it_comes_back(self):
        """The fold was measured while the bar was still hidden, so it came
        back unfolded — and at an unchanged width no Resize put it right: Qt
        crushed six buttons into the bar and cut their labels to stubs."""
        c = self.c
        # Tests never show a window, so "on screen" is the bar not being hidden.
        c._bulk.isVisible = lambda: not c._bulk.isHidden()
        tick = c._table.item(self._row(self.d1), 0)
        tick.setCheckState(Qt.Checked)
        # Room for the primary, Export and More — not for Verify and Save too.
        c._bulk_bar_w.setFixedWidth(c._bulk_need(2))
        c._fit_bulk()                                     # what the bar's first resize does
        self.assertFalse(c._b_more.isHidden())
        self.assertTrue(c._b_verify.isHidden())
        for _ in range(2):                                # clear, tick again: same width
            c._bulk_clear.click()
            self.assertTrue(c._bulk.isHidden())
            tick.setCheckState(Qt.Checked)
            self.assertFalse(c._bulk.isHidden())
            self.assertFalse(c._b_more.isHidden())
            self.assertTrue(c._b_verify.isHidden())
            self.assertTrue(c._b_save.isHidden())
            self.assertTrue(c._sel_all.isHidden())

    def test_coming_back_on_screen_refolds_the_toolbar_and_the_bulk_bar(self):
        """Off screen (another tab showing) both keep everything; a session
        opened from Sessions, or ticks changed meanwhile, unfold them there. The
        tab coming back at the same width sends Show but no Resize."""
        c = self.c
        on_screen = [True]
        c._bulk.isVisible = lambda: on_screen[0] and not c._bulk.isHidden()
        c._toolbar.isVisible = lambda: on_screen[0] and not c._toolbar.isHidden()
        c._table.item(self._row(self.d1), 0).setCheckState(Qt.Checked)
        c._toolbar.setFixedWidth(c._toolbar_need(3))      # no Avg fit, Net-new or "Sort"
        c._bulk_bar_w.setFixedWidth(c._bulk_need(2))      # Verify and Save in More
        c._fit_toolbar()                                  # what their resizes do
        c._fit_bulk()

        def folded():
            return (c._c_fit.isHidden(), c._c_new.isHidden(), c._sort_lbl.isHidden(),
                    c._b_verify.isHidden(), not c._b_more.isHidden())

        self.assertEqual(folded(), (True,) * 5)
        on_screen[0] = False                              # the Sessions tab is showing
        c._table.item(self._row(self.d2), 0).setCheckState(Qt.Checked)
        c._apply_filters()
        self.assertEqual(folded(), (False,) * 5)
        on_screen[0] = True                               # and Leads comes back
        for widget in (c._toolbar, c._bulk_bar_w):
            QApplication.sendEvent(widget, QShowEvent())
        self.assertEqual(folded(), (True,) * 5)

    def test_column_widths_survive_a_new_run(self):
        c, head = self.c, self.c._head
        self.assertEqual(head.sectionResizeMode(CK._C_TICK), QHeaderView.Fixed)
        self.assertEqual(head.sectionResizeMode(CK._C_LEAD), QHeaderView.Interactive)
        head.resizeSection(CK._C_LEAD, 340)
        head.resizeSection(CK._C_STATUS, 150)
        head.resizeSection(CK._C_FIT, 20)                 # under its minimum
        c.set_dossiers([self.d2, self.d3])
        self.assertEqual(head.sectionSize(CK._C_LEAD), 340)
        self.assertEqual(head.sectionSize(CK._C_STATUS), 150)
        self.assertEqual(head.sectionSize(CK._C_FIT), CK._COL_MIN[CK._C_FIT])

    def test_the_focus_cell_carries_the_location(self):
        lead = Lead(name="Aarti", title="Plant Head", company="Gulf Works",
                    email="a@x.com", fit_score=70)
        lead.extra = {"location": "Dubai, United Arab Emirates"}
        c = CK.LeadsCockpit()
        c.set_dossiers([], all_leads=[lead])
        focus = c._table.item(0, CK._C_FOCUS)
        self.assertEqual(focus.text(), "Plant Head")
        self.assertEqual(focus.data(CK._WHERE_ROLE), "Dubai, United Arab Emirates")
        self.assertIn("Dubai", focus.toolTip())
        c._search.setText("dubai")
        c._apply_filters()                                # the debounce, run now
        self.assertIn("1 of 1", c._count_lbl.text())

    def test_the_drawer_docks_when_wide_and_floats_when_narrow(self):
        c = self.c
        self._lay_out(1900, 900)
        c._table.setCurrentCell(0, 1)
        self.assertTrue(c._drawer_docked)
        self.assertIs(c._split.widget(2), c._drawer_w)
        self._lay_out(1000, 700)
        c._place_drawer()                                 # what the body's resize does
        self.assertFalse(c._drawer_docked)
        self.assertIs(c._drawer_w.parentWidget(), c._body)
        self.assertFalse(c._drawer_w.isHidden())


class CardGallery(unittest.TestCase):
    """The Pinterest-style card view is the same leads as the table, one
    selection model behind both: a card per lead, ticking a card selects it and
    mirrors the table row, and the filters hide cards just as they hide rows."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.d3 = _dos("NoMail", 60, "")
        self.d4 = _dos("Bad", 40, "b@x.com", "invalid")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2, self.d3, self.d4])
        self.c._set_view("cards")

    def _row(self, dos):
        for r in range(self.c._table.rowCount()):
            if self.c._dossier_at(r) is dos:
                return r
        return -1

    def test_gallery_shows_a_card_per_lead(self):
        self.assertEqual(self.c._view, "cards")
        self.assertEqual(self.c._grid.count(), 4)

    def test_ticking_a_card_selects_it_and_mirrors_the_table(self):
        self.c._card_cbs[0].setChecked(True)             # d1 is dossier index 0
        self.assertEqual(self.c.selected(), [self.d1])
        self.assertTrue(self.c._b_seq.isEnabled())
        self.assertEqual(self.c._table.item(self._row(self.d1), 0).checkState(),
                         Qt.Checked)

    def test_filter_hides_cards_like_rows(self):
        self.c._fit_min.setValue(70)                     # d3 (60), d4 (40) drop
        self.assertEqual(self.c._grid.count(), 2)

    def test_table_tick_reflects_on_the_card(self):
        r = self._row(self.d2)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.assertTrue(self.c._card_cbs[1].isChecked())  # d2 is index 1


class WorkspaceSurface(unittest.TestCase):
    """The tab strip over the five screens, and the two things the dialog leans
    on: the re-exposed signals/set_dossiers, and Analytics tracking this run."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())

    def test_six_tabs_over_six_screens(self):
        self.assertEqual(len(self.w._tabs), 6)
        self.assertEqual(self.w._stack.count(), 6)
        self.assertIs(self.w._stack.currentWidget(), self.w.leads)  # Leads default

    def test_selecting_a_tab_switches_the_stack(self):
        self.w._select(5)                                   # Analytics
        self.assertIs(self.w._stack.currentWidget(), self.w._analytics)
        self.w._select(2)                                   # Lists
        self.assertIs(self.w._stack.currentWidget(), self.w._lists)
        self.w._select(1)                                   # Sessions
        self.assertIs(self.w._stack.currentWidget(), self.w._sessions)

    def test_set_dossiers_reaches_leads_and_analytics(self):
        self.w.set_dossiers([self.d1, self.d2])
        self.assertEqual(self.w.leads._table.rowCount(), 2)
        qualified = self.w._analytics._stats.itemAt(0).widget()   # first stat card
        self.assertEqual(qualified._num.text(), "2")

    def test_reexposes_the_bulk_signals(self):
        got = []
        self.w.sequenceRequested.connect(got.append)
        self.w.set_dossiers([self.d1])
        self.w.leads._table.item(0, 0).setCheckState(Qt.Checked)
        self.w.leads._b_seq.click()
        self.assertEqual(got, [[self.d1]])

    def test_analytics_counts_mailed(self):
        draft = type("Dr", (), {"dossier": self.d1, "status": "sent", "body": "hi"})()
        self.w.set_dossiers([self.d1, self.d2], [draft])
        mailed = self.w._analytics._stats.itemAt(2).widget()      # Qualified,Drafted,Mailed
        self.assertEqual(mailed._num.text(), "1")


class ListsTab(unittest.TestCase):
    """Lists is real — it scans a folder for the sheets Prism writes."""

    def test_scans_csv_and_xlsx_newest_first(self):
        d = tempfile.mkdtemp()
        p1 = os.path.join(d, "old list.csv")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("name,email\nA,a@x.com\nB,b@x.com\n")
        p2 = os.path.join(d, "Prism leads.xlsx")
        with open(p2, "wb") as f:
            f.write(b"PK\x03\x04 fake xlsx")
        os.utime(p1, (time.time() - 100, time.time() - 100))      # make the csv older
        tab = CK._ListsTab(d)
        self.assertEqual([os.path.basename(p) for p, *_ in tab._scan()],
                         ["Prism leads.xlsx", "old list.csv"])
        self.assertEqual(tab._grid.count(), 2)                    # two cards, no empty-state

    def test_csv_row_count_excludes_header(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("h1,h2\n1,2\n3,4\n5,6\n")
        self.assertEqual(CK._csv_rows(p), 3)

    def test_empty_folder_shows_one_empty_state(self):
        tab = CK._ListsTab(tempfile.mkdtemp())
        self.assertEqual(tab._grid.count(), 1)


class _Workbench(unittest.TestCase):
    """A workbench that only ever touches temp folders — sheets, sessions and
    saved searches — plus a finished run to hand it."""

    def setUp(self):
        from addons.leads import workbench as WB
        self._WB = WB
        self._tmp = tempfile.mkdtemp()
        self._sessions = tempfile.mkdtemp()
        self._searches = tempfile.mkdtemp()
        self._orig = WB.LeadsWorkbench._autosave_dir
        self._orig_sessions = WB.LeadsWorkbench._sessions_dir
        self._orig_searches = WB.LeadsWorkbench._searches_dir
        WB.LeadsWorkbench._autosave_dir = lambda _self: self._tmp        # no real Documents
        WB.LeadsWorkbench._sessions_dir = lambda _self: self._sessions   # no real workspace
        WB.LeadsWorkbench._searches_dir = lambda _self: self._searches

    def tearDown(self):
        self._WB.LeadsWorkbench._autosave_dir = self._orig
        self._WB.LeadsWorkbench._sessions_dir = self._orig_sessions
        self._WB.LeadsWorkbench._searches_dir = self._orig_searches

    def _run(self):
        """A finished sheet run: two qualified leads, one draft already sent."""
        from prospector.engine import RunResult
        from prospector.reach import Draft
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        d2 = _dos("Vaibhav", 80, "v@x.com", "")
        res = RunResult(dossiers=[d1, d2], total_in_sheet=2, signal_source="",
                        all_leads=[d1.lead, d2.lead])
        return res, [Draft(dossier=d1, subject="Hi", body="Hello", status="sent")]

    def _finished(self, wb):
        wb._start_export = lambda *a, **k: None     # no MX lookups, no files
        wb._next_mode = "sheet"
        wb._next_params = {"mode": "sheet", "sheet_path": "leads.xlsx", "limit": 25}
        res, drafts = self._run()
        wb._jobs = 1
        wb._on_prepared(res, drafts)
        return res, drafts


class WorkbenchAndPanel(_Workbench):
    """The workbench is now the full in-window surface (no modal); the panel
    hosts it lazily. Guard the extraction: it builds, the setup folds, the
    status line hides when empty, and the panel builds the workbench on show."""

    def test_a_finished_run_is_kept_as_a_session(self):
        from addons.leads import sessions
        wb = self._WB.LeadsWorkbench({})
        self._finished(wb)
        heads = sessions.list_sessions(self._sessions)
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["id"], wb._session_id)
        self.assertEqual(heads[0]["counts"]["sent"], 1)
        self.assertEqual(wb._jobs, 0)

    def test_an_opened_session_comes_back_as_it_was(self):
        from addons.leads import sessions
        first = self._WB.LeadsWorkbench({})
        self._finished(first)
        loaded = sessions.load(self._sessions, first._session_id)
        wb = self._WB.LeadsWorkbench({})
        wb._apply_session(loaded)
        self.assertEqual(wb._cockpit.leads._table.rowCount(), 2)
        mailed = [d for d in wb._res.dossiers
                  if CK.status_of(d, wb._draft_by.get(id(d))) == "Mailed"]
        self.assertEqual(len(mailed), 1)
        self.assertFalse(wb._send_btn.isEnabled())       # nothing left unmailed
        self.assertEqual(wb._path, "leads.xlsx")

    def test_the_next_run_skips_people_already_pulled(self):
        from addons.leads.workers import _seen_index
        wb = self._WB.LeadsWorkbench({})
        res, _ = self._finished(wb)
        self.assertIsNone(_seen_index(self._sessions, include_earlier=True))
        seen = _seen_index(self._sessions, include_earlier=False)
        self.assertIn(res.dossiers[0].lead, seen)
        stranger = _dos("Someone Else", 70, "else@y.com", "")
        self.assertNotIn(stranger.lead, seen)

    def test_a_running_job_blocks_a_second_send(self):
        wb = self._WB.LeadsWorkbench({})
        _res, drafts = self._run()
        drafts[0].status = "draft"
        wb._drafts, wb._jobs = drafts, 1
        wb._on_send()                                     # must not start a worker
        self.assertIsNone(wb._send_worker)

    def test_pending_leaves_out_mailed_drafts(self):
        _res, drafts = self._run()
        from prospector.reach import Draft
        fresh = Draft(dossier=drafts[0].dossier, subject="s", body="b")
        self.assertEqual(self._WB.LeadsWorkbench._pending(drafts + [fresh]), [fresh])

    def test_workbench_builds_with_the_cockpit(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertIsNotNone(wb._cockpit)
        self.assertEqual(len(wb._cockpit._tabs), 6)

    def test_status_line_hides_until_it_has_text(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertTrue(wb._status.isHidden())          # empty → no grey band
        wb._status.setText("Sending…")
        self.assertFalse(wb._status.isHidden())
        wb._status.setText("")
        self.assertTrue(wb._status.isHidden())

    def test_setup_folds_and_summarises(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertFalse(wb._setup_details.isHidden())  # open before a run
        self.assertTrue(wb._setup_toggle.isHidden())    # nothing to fold to yet
        wb._fold_setup(False)
        self.assertTrue(wb._setup_details.isHidden())
        self.assertFalse(wb._setup_toggle.isHidden())
        self.assertIn("qualify", wb._setup_line())

    def test_search_lives_in_the_leads_rail(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        self.assertIs(wb._setup_panel.parentWidget(), wb._cockpit.leads._rail.widget())
        self.assertEqual(len(wb.action_buttons()), 2)
        self.assertTrue(wb._keys_box.isHidden())         # key saved → keys folded

    def test_keys_open_when_the_exa_key_is_missing(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertFalse(wb._keys_box.isHidden())

    def test_panel_lazy_builds_workbench(self):
        from addons.leads.panel import LeadsPanel
        p = LeadsPanel({})
        self.assertIsNone(p._workbench)                 # nothing built at rest
        p._build()                                       # what showEvent triggers
        self.assertIsNotNone(p._workbench)
        self.assertEqual(p.header.actions_row.count(), 4)  # ?, AI tools, Export, Send all
        self.assertTrue(all(hasattr(p, s)
                            for s in ("opened", "navigate", "open_run", "refresh")))



class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _FakeSourceWorker:
    """Stands in for SourceWorker: records what it was handed; start() only
    records that it was started — no thread, no network."""
    made: list = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs, self.started = args, kwargs, False
        self.progress, self.done, self.failed = _FakeSignal(), _FakeSignal(), _FakeSignal()
        self.blocked = _FakeSignal()        # Apollo's plan/scope refusal
        _FakeSourceWorker.made.append(self)

    def start(self):
        self.started = True


class LeadFiltersInTheWorkbench(_Workbench):
    """The rail's lead filters, end to end on the UI side: a Find-people run
    hands the worker the filters (not a line of location text), an old
    session's "Global except india" comes back as an exclusion, and saved
    searches save, load, delete and count their runs."""

    def _spec(self):
        from prospector.filters import SearchSpec
        return SearchSpec.from_dict({
            "locations": {"exclude": ["India"]},
            "job_titles": {"include": ["Plant Head", "Head of Manufacturing"]},
            "industries": {"include": ["Tyre", "Steel Manufacturing"]},
            "seniority": {"include": ["head", "director"]}})

    def test_find_people_is_the_default_with_the_default_filters(self):
        wb = self._WB.LeadsWorkbench({})
        spec = wb._filters.spec()
        self.assertEqual(wb._mode, "icp")
        self.assertEqual(len(spec.job_titles.include), 6)
        self.assertEqual(len(spec.industries.include), 10)
        self.assertEqual(spec.location_label(), "Anywhere")
        self.assertTrue(wb._prepare.isEnabled())
        # The folded line names the database the run will ask — with no Apollo
        # key that is Exa.
        self.assertTrue(wb._setup_line().startswith("Exa · 6 titles"))

    def test_place_suggestions_lead_with_places_and_fall_back_to_the_starters(self):
        from unittest import mock
        got = self._WB._suggest("locations", "ger")
        self.assertEqual(got[0], "Germany")
        self.assertNotIn("Nigeria", got)            # no mid-word matches beside places
        with mock.patch("prospector.places.suggest", side_effect=RuntimeError("gone")):
            self.assertIn("Germany", self._WB._suggest("company_hq", "ger"))
        self.assertEqual(self._WB._suggest("job_titles", "plant"), ["Plant Head"])

    def test_prepare_needs_someone_to_look_for(self):
        from prospector.filters import SearchSpec
        wb = self._WB.LeadsWorkbench({})
        wb._filters.set_spec(SearchSpec.from_dict({"locations": {"exclude": ["India"]}}))
        self.assertFalse(wb._prepare.isEnabled())
        wb._filters.set_spec(SearchSpec.from_dict({"functions": {"include": ["operations"]}}))
        self.assertTrue(wb._prepare.isEnabled())

    def test_a_legacy_global_except_india_session_restores_as_an_exclusion(self):
        wb = self._WB.LeadsWorkbench({})
        wb._restore_inputs({"mode": "icp", "industries": ["Tyre", "Mining"],
                            "roles": ["Plant Head"], "location": "Global except india",
                            "target": 400, "include_earlier": True})
        spec = wb._filters.spec()
        self.assertEqual(spec.locations.exclude, ["India"])
        self.assertEqual(spec.locations.include, [])
        self.assertEqual(spec.job_titles.include, ["Plant Head"])
        self.assertEqual(spec.industries.include, ["Tyre", "Mining"])
        self.assertEqual((wb._target.value(), wb._skip_seen.isChecked()), (400, False))

    def test_a_find_people_run_hands_the_worker_the_filters(self):
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})   # same key: no config write
            spec = self._spec()
            wb._filters.set_spec(spec)
            wb._on_prepare()
        finally:
            self._WB.SourceWorker = orig
        self.assertEqual(len(_FakeSourceWorker.made), 1)
        worker = _FakeSourceWorker.made[0]
        self.assertTrue(worker.started)
        self.assertEqual(worker.kwargs["spec"], spec.to_dict())
        self.assertEqual(worker.args[0], ["Tyre", "Steel Manufacturing"])
        self.assertEqual(worker.args[1], ["Plant Head", "Head of Manufacturing"])
        self.assertEqual(worker.kwargs["location"], "Anywhere except India")
        # The primary button is the cheap run: the people, and nothing else.
        self.assertEqual((worker.kwargs["emails"], worker.kwargs["leads_only"]),
                         ("later", True))
        params = wb._next_params
        self.assertEqual(params["mode"], "icp_leads_only")
        self.assertEqual(params["filters"], spec.to_dict())
        self.assertEqual(params["location"], "Anywhere except India")
        self.assertEqual(wb._jobs, 1)

    def test_the_two_run_buttons_are_the_cheap_run_and_the_whole_pipeline(self):
        """"Find people" costs its searches and stops; "Find and prepare" is
        today's run — addresses, Groq, drafts — in one press."""
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
            self.assertEqual(wb._prepare.text(), "Find people")
            self.assertEqual(wb._prepare_all.text(), "Find and prepare")
            wb._prepare.click()
            wb._jobs = 0                                  # the run "finished"
            wb._set_running(False)
            wb._prepare_all.click()
        finally:
            self._WB.SourceWorker = orig
        cheap, whole = _FakeSourceWorker.made
        self.assertEqual((cheap.kwargs["emails"], cheap.kwargs["leads_only"]),
                         ("later", True))
        self.assertEqual((whole.kwargs["emails"], whole.kwargs["leads_only"]),
                         ("now", False))
        self.assertEqual(wb._next_params["mode"], "icp")

    def test_a_sheet_is_loaded_without_groq_and_never_cut_as_already_pulled(self):
        """The sheet the owner brings back is usually the one Prism exported
        last run, so "Net new only" — a rule about a SEARCH not re-finding
        people — must not empty it. The switch is not even shown here."""
        made = []

        class _FakeProspectorWorker(_FakeSourceWorker):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                made.append(self)

        orig = self._WB.ProspectorWorker
        self._WB.ProspectorWorker = _FakeProspectorWorker
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
            wb._set_mode("sheet")
            self.assertEqual(wb._prepare.text(), "Load the sheet")
            self.assertTrue(wb._skip_seen.isHidden())
            wb._path = os.path.join(self._tmp, "Prism leads.xlsx")
            wb._refresh_prepare()
            wb._prepare.click()
        finally:
            self._WB.ProspectorWorker = orig
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].kwargs["limit"], 0)      # read and rank only
        self.assertNotIn("sessions_dir", made[0].kwargs)  # no seen-index at all

    def test_the_run_summary_says_who_the_filters_left_out(self):
        wb = self._WB.LeadsWorkbench({})
        res, drafts = self._run()
        res.filtered_out = {"location": 380, "job_title": 32}
        self.assertIn("412 outside your filters (location)", wb._run_summary(res, drafts))
        res.filtered_out = {}
        self.assertNotIn("outside your filters", wb._run_summary(res, drafts))

    def test_nobody_left_names_the_filters_and_the_reasons(self):
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {"location": 380, "job_title": 32})
        self.assertIn("412 were outside them (380 location, 32 job title)", text)
        self.assertIn("Net new only", _nobody_left(12, {}))

    def test_every_search_failing_names_the_key_not_the_filters(self):
        # 22-Sep-2026: reported live three times on a sheet with well-known
        # companies that should have been easy to find someone for.
        # _exa_people distinguishes "the call failed" (None) from "it
        # answered with nothing" ([]) and source.py counts both, but
        # nothing downstream read query_errors before this — every one of
        # these calls failing (a bad key, no balance) produced the exact
        # same "widen the filters" text as a genuine zero-match search.
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "exa", query_errors=100, queries_used=100)
        self.assertIn("Every one of the 100 searches to Exa failed", text)
        self.assertIn("key or balance", text)
        self.assertNotIn("widen the filters", text)   # not a filters problem

    def test_some_searches_failing_gets_a_note_not_a_false_certainty(self):
        # A few failures do not prove the account is broken — the rest may
        # genuinely have found nobody. Named, not hidden, but not claimed
        # as the definite cause the all-failed case is.
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "exa", query_errors=3, queries_used=100)
        self.assertIn("No people came back", text)
        self.assertIn("3 of 100 searches to Exa failed", text)

    def test_zero_query_errors_is_unchanged(self):
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "exa", query_errors=0, queries_used=100)
        self.assertEqual(text,
                         "No people came back — widen the filters, or check your Exa balance.")
        # And the default (no stats passed at all) behaves the same way.
        self.assertEqual(_nobody_left(0, {}, "exa"), text)

    def test_apollo_names_apollo_not_exa_when_every_search_fails(self):
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "apollo", query_errors=10, queries_used=10)
        self.assertIn("Every one of the 10 searches to Apollo failed", text)
        self.assertNotIn("Exa", text)

    def test_save_search_keeps_the_filters_and_shows_a_card(self):
        from addons.leads import saved_searches
        wb = self._WB.LeadsWorkbench({})
        spec = self._spec()
        wb._filters.set_spec(spec)
        wb._target.setValue(500)
        wb._ask_search_name = lambda suggested="": ("Global plants, not India", True)
        wb._filters._save_btn.click()
        records = saved_searches.list_searches(self._searches)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Global plants, not India")
        self.assertEqual(records[0]["filters"], spec.to_dict())
        self.assertEqual(records[0]["settings"]["target"], 500)
        self.assertEqual(wb._cockpit._saved.cards(), 1)
        self.assertIn("Saved", wb._status.text())

    def test_a_cancelled_or_taken_name_saves_nothing_new(self):
        from addons.leads import saved_searches
        wb = self._WB.LeadsWorkbench({})
        wb._ask_search_name = lambda suggested="": ("", False)
        wb._save_search()
        self.assertEqual(saved_searches.list_searches(self._searches), [])
        saved_searches.save(self._searches, "Taken", self._spec().to_dict())
        wb._ask_search_name = lambda suggested="": ("taken", True)
        wb._save_search()
        self.assertEqual(len(saved_searches.list_searches(self._searches)), 1)
        self.assertIn("Couldn't save this search", wb._status.text())

    def test_use_search_loads_its_filters_and_settings(self):
        from addons.leads import saved_searches
        spec = self._spec()
        record = saved_searches.save(
            self._searches, "Plants", spec.to_dict(),
            settings={"target": 700, "limit": 40, "verify_limit": 5,
                      "include_earlier": True, "offer": "Line retrofits"})
        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("sheet")
        wb._cockpit.refresh_searches()
        wb._cockpit._select(3)
        card = wb._cockpit._saved._grid.itemAt(0).widget()
        card._use.click()
        self.assertEqual(wb._filters.spec(), spec)
        self.assertEqual((wb._target.value(), wb._limit.value(),
                          wb._verify_limit.value()), (700, 40, 5))
        self.assertFalse(wb._skip_seen.isChecked())
        self.assertEqual(wb._offer.toPlainText(), "Line retrofits")
        self.assertEqual(wb._mode, "icp")
        self.assertIs(wb._cockpit._stack.currentWidget(), wb._cockpit.leads)
        self.assertEqual(wb._active_search_id, record["id"])
        self.assertIn("Find people", wb._status.text())

    def test_use_search_waits_while_a_job_runs(self):
        from addons.leads import saved_searches
        record = saved_searches.save(self._searches, "Plants", self._spec().to_dict())
        wb = self._WB.LeadsWorkbench({})
        before = wb._filters.spec()
        wb._jobs = 1
        wb.use_saved_search(record["id"])
        self.assertEqual(wb._filters.spec(), before)
        self.assertIn("Wait", wb._status.text())

    def test_delete_asks_first_then_removes_the_search(self):
        from addons.leads import saved_searches
        saved_searches.save(self._searches, "Plants", self._spec().to_dict())
        wb = self._WB.LeadsWorkbench({})
        wb._cockpit.refresh_searches()
        wb._confirm_delete = lambda name: False
        wb._cockpit._saved._grid.itemAt(0).widget()._delete.click()
        self.assertEqual(len(saved_searches.list_searches(self._searches)), 1)
        wb._confirm_delete = lambda name: True
        wb._cockpit._saved._grid.itemAt(0).widget()._delete.click()
        self.assertEqual(saved_searches.list_searches(self._searches), [])
        self.assertEqual(wb._cockpit._saved.cards(), 0)
        self.assertFalse(wb._cockpit._saved._empty.isHidden())

    def test_a_finished_run_of_the_search_on_the_rail_is_counted(self):
        from addons.leads import saved_searches
        spec = self._spec()
        record = saved_searches.save(self._searches, "Plants", spec.to_dict())
        wb = self._WB.LeadsWorkbench({})
        wb.use_saved_search(record["id"])
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "filters": spec.to_dict()}
        res, _ = self._run()
        wb._jobs = 1
        wb._on_prepared(res, [])
        after = saved_searches.get(self._searches, record["id"])
        self.assertEqual((after["runs"], after["last_new"]), (1, 2))
        self.assertEqual(after["last_session_id"], wb._session_id)
        # Filters edited after Use are a different search: not counted.
        wb._next_params = {"mode": "icp",
                           "filters": dict(spec.to_dict(), similar_titles=False)}
        wb._jobs = 1
        wb._on_prepared(res, [])
        self.assertEqual(saved_searches.get(self._searches, record["id"])["runs"], 1)



class ApolloIsTheOtherDatabase(_Workbench):
    """The same filters, asked of Apollo instead of Exa: the key is entered
    once and saved on Prepare, the switch picks the source (Exa by default even
    with an Apollo key — Apollo's search is not in its free plan), the run
    setting says what that source charges, and what a run cost in credits is on
    the summary."""

    def _spec(self):
        from prospector.filters import SearchSpec
        return SearchSpec.from_dict({
            "job_titles": {"include": ["Plant Head"]},
            "seniority": {"include": ["owner"]}})

    def _prepared(self, wb):
        """Press Prepare with the worker stubbed out; return it, or None."""
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        try:
            wb._on_prepare()
        finally:
            self._WB.SourceWorker = orig
        return _FakeSourceWorker.made[0] if _FakeSourceWorker.made else None

    def test_exa_is_the_default_even_when_an_apollo_key_is_set(self):
        """Apollo's people search is not in its FREE plan (its own API Keys
        page), so leading with it sends most owners into a 403. It is there to
        be picked, with a tooltip saying what it needs."""
        plain = self._WB.LeadsWorkbench({})
        self.assertEqual(plain._source, "exa")
        self.assertTrue(plain._src_exa.isChecked())
        self.assertFalse(plain._keys_box.isHidden())        # no key at all: open
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k"})
        self.assertEqual(wb._source, "exa")
        self.assertTrue(wb._src_exa.isChecked())
        self.assertFalse(wb._src_apollo.isChecked())
        self.assertTrue(wb._src_apollo.isEnabled())
        self.assertIn("PAID Apollo plan", wb._src_apollo.toolTip())
        self.assertTrue(wb._keys_box.isHidden())            # either key folds it
        self.assertTrue(wb._setup_line().startswith("Exa · 6 titles"))
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")

    def test_the_apollo_key_is_saved_and_nothing_else_in_the_config_is(self):
        """The rail saves the key it was given by loading the config fresh and
        writing back only that key — self.cfg can predate an account saved
        elsewhere, and the real config is never touched by a test."""
        from unittest import mock
        wb = self._WB.LeadsWorkbench({"exa_api_key": "exa-k"})
        wb._apollo.setText("ap-secret")
        saved = []
        with mock.patch("core_bridge.config.load",
                        return_value={"api_key": "gsk_kept"}), \
                mock.patch("core_bridge.config.save", side_effect=saved.append):
            worker = self._prepared(wb)
        self.assertIsNotNone(worker)
        self.assertEqual(saved, [{"api_key": "gsk_kept",
                                  "apollo_api_key": "ap-secret"}])
        self.assertEqual(wb.cfg["apollo_api_key"], "ap-secret")

    def test_an_apollo_run_hands_the_worker_the_source_and_the_filters(self):
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k"})
        wb._src_apollo.click()                          # Exa is the default now
        spec = self._spec()
        wb._filters.set_spec(spec)
        worker = self._prepared(wb)
        self.assertTrue(worker.started)
        self.assertEqual(worker.kwargs["source"], "apollo")
        self.assertEqual(worker.kwargs["spec"], spec.to_dict())
        self.assertEqual(wb._next_params["source"], "apollo")
        self.assertEqual(wb._jobs, 1)

    def test_either_source_can_be_picked_and_the_session_brings_it_back(self):
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k"})
        wb._src_exa.click()
        self.assertEqual(self._prepared(wb).kwargs["source"], "exa")
        wb._restore_inputs({"mode": "icp", "source": "apollo", "target": 400})
        self.assertEqual(wb._source, "apollo")
        self.assertTrue(wb._src_apollo.isChecked())

    def test_a_session_that_names_no_source_reopens_on_exa(self):
        """Every session saved before Prism could ask Apollo — and every sheet
        run — carries no source, so it can only have been an Exa run; reopening
        one must not re-point it at the database that bills per person."""
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k"})
        wb._src_apollo.click()                           # pick Apollo, then reopen
        self.assertEqual(wb._source, "apollo")
        wb._restore_inputs({"mode": "icp", "target": 400})
        self.assertEqual(wb._source, "exa")
        self.assertTrue(wb._src_exa.isChecked())
        self.assertEqual(wb._target_row.name.text(), "Source up to")
        self.assertEqual(self._prepared(wb).kwargs["source"], "exa")

    def test_prepare_says_which_key_is_missing(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "exa-k"})
        wb._src_apollo.click()
        self.assertIsNone(self._prepared(wb))
        self.assertIn("Apollo API key", wb._status.text())
        self.assertFalse(wb._keys_box.isHidden())    # opened at the missing key
        self.assertEqual(wb._jobs, 0)
        wb._src_exa.click()
        self.assertIsNotNone(self._prepared(wb))

    def test_the_run_setting_says_what_the_source_charges(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertEqual(wb._target_row.name.text(), "Source up to")
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")
        self.assertEqual(wb._target_row.name.text(), "Reveal up to")
        self.assertIn("one Apollo credit", wb._target.toolTip())
        wb._src_exa.click()
        self.assertEqual(wb._target_row.name.text(), "Source up to")

    def test_the_summary_counts_what_the_run_cost_in_credits(self):
        wb = self._WB.LeadsWorkbench({})
        res, drafts = self._run()
        res.apollo_stats = {"searched": 240, "revealed": 25, "reveal_calls": 3}
        self.assertIn("Apollo: 240 found · 25 revealed (about 25 credits)",
                      wb._run_summary(res, drafts))
        res.apollo_stats = {}                       # an Exa run says nothing
        self.assertNotIn("Apollo", wb._run_summary(res, drafts))


def _apollo_module():
    """prospector.apollo — the Apollo client the worker calls — or a stand-in
    registered under that name while it is being written beside these tests.
    Either way the tests patch the same two functions on the same module, so
    they say the same thing about the worker once the real client lands."""
    import types

    import prospector
    try:
        from prospector import apollo
        return apollo
    except ImportError:
        apollo = types.ModuleType("prospector.apollo")

        class ApolloError(Exception):
            pass

        apollo.ApolloError = ApolloError
        apollo.api_key = lambda cfg: (cfg.get("apollo_api_key") or "").strip()
        apollo.search_people = lambda spec, key, **kw: []
        apollo.find_email = lambda lead, key: ("", "")
        sys.modules["prospector.apollo"] = apollo
        prospector.apollo = apollo
        return apollo


class SourceWorkerSearchesApollo(unittest.TestCase):
    """SourceWorker.run() with source="apollo", called inline (no thread, no
    network): the filters go to Apollo and never to Exa, only the people Apollo
    had no address for are enriched, what the run cost rides home on the
    result, and an ApolloError is what the failure says."""

    def _worker(self, cfg=None, **kw):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["owner"]},
                                     "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits",
                         {"apollo_api_key": "ap-test"} if cfg is None else cfg,
                         source="apollo", target=25, verify_limit=0,
                         spec=spec.to_dict(), **kw)
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(got["progress"].append)
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        return w, spec, got

    def _people(self):
        """What Apollo hands back: one person it had an address for, one it
        did not."""
        known = Lead(name="Ana Ruiz", company="Acme", title="Owner",
                     email="ana@acme.com")
        known.extra = {"apollo_id": "a1", "email_check": "valid"}
        unknown = Lead(name="Bo Lund", company="Globex", title="Owner")
        unknown.extra = {"apollo_id": "a2"}
        return known, unknown

    def _patched(self, search, enriched=None):
        """Every seam the Apollo path touches, stubbed. prospector.source is
        stubbed to raise: asking Exa on an Apollo run would be the bug."""
        from unittest import mock
        from prospector.engine import RunResult
        apollo = _apollo_module()

        def fake_run_leads(leads, offer, cfg, **kw):
            return RunResult(dossiers=[Dossier(lead=l) for l in leads],
                             total_in_sheet=len(leads), signal_source="",
                             all_leads=list(leads))

        return [
            mock.patch.object(apollo, "api_key", return_value="ap-test"),
            mock.patch.object(apollo, "search_people", side_effect=search),
            mock.patch("prospector.source.source",
                       side_effect=AssertionError("Exa must not be asked")),
            mock.patch("prospector.signals.exa_key", return_value=""),
            mock.patch("prospector.signals.make_provider", return_value=None),
            mock.patch("prospector.enrich.enrich",
                       side_effect=lambda leads, key="", **kw: (
                           enriched.append(list(leads)) if enriched is not None
                           else None)),
            mock.patch("prospector.engine.run_leads", side_effect=fake_run_leads),
            mock.patch("prospector.verify.collect_keys", return_value={}),
            mock.patch("prospector.reach.draft_batch", return_value=[]),
        ]

    @staticmethod
    def _run(worker, patches):
        for patch in patches:
            patch.start()
        try:
            worker.run()
        finally:
            for patch in patches:
                patch.stop()

    def test_the_filters_go_to_apollo_and_the_credits_come_back(self):
        from prospector.filters import SearchSpec
        known, unknown = self._people()
        calls, enriched = {}, []

        def fake_search(spec, key, **kw):
            calls.update(spec=spec, key=key, **kw)
            kw["stats"].update(searched=240, revealed=2, reveal_calls=1,
                               filtered={"location": 40}, skipped_seen=3)
            kw["on_progress"]("search", 3, 0, 240)
            kw["on_progress"]("reveal", 12, 25, 0)
            return [known, unknown]

        w, spec, got = self._worker()
        self._run(w, self._patched(fake_search, enriched))
        self.assertEqual(got["failed"], [])
        self.assertIsInstance(calls["spec"], SearchSpec)
        self.assertEqual(calls["spec"], spec)
        self.assertEqual((calls["key"], calls["target"]), ("ap-test", 25))
        self.assertIsNone(calls["skip"])                 # no sessions folder
        # Only the person Apollo had no address for is guessed an address.
        self.assertEqual(enriched, [[unknown]])
        res, _drafts = got["done"][0]
        self.assertEqual(res.apollo_stats["revealed"], 2)
        self.assertEqual(res.filtered_out, {"location": 40})
        self.assertEqual(res.skipped_seen, 3)
        self.assertIn("Searching Apollo — page 3 · 240 found", got["progress"])
        self.assertIn("Revealing 12 of 25 (Apollo credits)", got["progress"])

    def test_an_apollo_error_is_what_the_failure_says(self):
        apollo = _apollo_module()

        def boom(spec, key, **kw):
            raise apollo.ApolloError("Apollo refused that key (401).")

        w, _spec, got = self._worker()
        self._run(w, self._patched(boom))
        self.assertEqual(got["done"], [])
        self.assertEqual(got["failed"], ["Apollo refused that key (401)."])

    def test_nobody_left_names_apollo(self):
        from addons.leads.workers import _nobody_left
        w, _spec, got = self._worker()
        self._run(w, self._patched(lambda spec, key, **kw: []))
        self.assertEqual(got["done"], [])
        self.assertIn("Apollo", got["failed"][0])
        self.assertIn("Exa balance", _nobody_left(0, {}))     # unchanged for Exa

    def test_without_a_key_apollo_is_never_asked(self):
        from unittest import mock
        apollo = _apollo_module()
        w, _spec, got = self._worker(cfg={})
        asked = []
        patches = self._patched(lambda spec, key, **kw: asked.append(kw) or [])
        patches[0] = mock.patch.object(apollo, "api_key", return_value="")
        self._run(w, patches)
        self.assertEqual(asked, [])
        self.assertIn("Apollo API key", got["failed"][0])


class SourceWorkerHandsOnTheFilters(unittest.TestCase):
    """SourceWorker.run(), called inline (no thread, no network): the filters
    reach source.source as a SearchSpec, the roles it ranks by are the
    filters' role terms, and who the filters turned away rides on the result —
    or, when nobody is left, is said in the failure."""

    def _worker(self, **kw):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({
            "locations": {"exclude": ["India"]},
            "seniority": {"include": ["head"]},
            "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits", {}, leads_only=True,
                         spec=spec.to_dict(), **kw)
        got = {"done": [], "failed": []}
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        return w, spec, got

    def _patched(self, found, filtered):
        from unittest import mock
        calls = {}

        def fake_source(industries, roles, key, **kw):
            calls.update(roles=roles, spec=kw.get("spec"))
            kw["stats"].update(filtered=dict(filtered), company_unverified=3)
            return list(found)

        return calls, [
            mock.patch("prospector.signals.exa_key", return_value="exa-test"),
            mock.patch("prospector.source.source", side_effect=fake_source),
            mock.patch("prospector.enrich.enrich", return_value=None),
            mock.patch("prospector.triage.rank",
                       side_effect=lambda leads, offer, roles=None: list(leads)),
        ]

    def _run(self, worker, patches):
        for patch in patches:
            patch.start()
        try:
            worker.run()
        finally:
            for patch in patches:
                patch.stop()

    def test_the_spec_reaches_the_source_and_the_counts_come_back(self):
        from prospector.filters import SearchSpec
        w, spec, got = self._worker()
        people = [Lead(name="Ana Ruiz", company="Acme", title="Head Operations")]
        calls, patches = self._patched(people, {"location": 40, "seniority": 2})
        self._run(w, patches)
        self.assertEqual(got["failed"], [])
        self.assertIsInstance(calls["spec"], SearchSpec)
        self.assertEqual(calls["spec"], spec)
        self.assertEqual(calls["roles"], spec.role_terms())
        res, drafts = got["done"][0]
        self.assertEqual(res.filtered_out, {"location": 40, "seniority": 2})
        self.assertEqual(res.company_unverified, 3)
        self.assertEqual(len(res.all_leads), 1)

    def test_nobody_inside_the_filters_says_why(self):
        w, _spec, got = self._worker()
        _calls, patches = self._patched([], {"location": 380, "job_title": 32})
        self._run(w, patches)
        self.assertEqual(got["done"], [])
        self.assertIn("Nobody who came back matched your filters", got["failed"][0])
        self.assertIn("(380 location, 32 job title)", got["failed"][0])


class EverySourcedPersonIsListed(unittest.TestCase):
    """A leads-sheet-only run sources people and qualifies none; a full run
    qualifies only the top slice of what it sourced. Both used to leave the
    unqualified off the table — the owner opened a 100-lead session to an empty
    screen. Now every sourced person is a row: a qualified one keeps its
    dossier, the rest read "Not qualified", and Analytics still counts only
    the qualified."""

    def _lead(self, name, fit, location=""):
        lead = Lead(name=name, title="Plant Head", company=f"{name} Works",
                    email=f"{name.lower()}@x.com", fit_score=fit)
        lead.extra = {"location": location} if location else {}
        return lead

    def test_a_leads_only_run_fills_the_table(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([], all_leads=[self._lead(f"P{i}", 50 + i) for i in range(5)])
        self.assertEqual(c._table.rowCount(), 5)
        self.assertNotEqual(c._view_stack.currentIndex(), 2)   # not the empty state
        self.assertFalse(c._toolbar.isHidden())
        self.assertEqual({c._table.item(r, 5).text() for r in range(5)},
                         {"Not qualified"})
        self.assertTrue(all(d.status == CK.UNQUALIFIED for d in c._dossiers))

    def test_a_qualified_lead_is_listed_once_with_its_dossier(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        other = self._lead("Vaibhav", 40)
        c = CK.LeadsCockpit()
        c.set_dossiers([d1], all_leads=[d1.lead, other])
        self.assertEqual(c._table.rowCount(), 2)
        self.assertIs(c._dossiers[0], d1)
        self.assertEqual([d.lead for d in c._dossiers], [d1.lead, other])

    def test_qualified_only_hides_the_rest(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        c = CK.LeadsCockpit()
        c.set_dossiers([d1], all_leads=[d1.lead, self._lead("A", 60),
                                        self._lead("B", 70)])
        c._only_qualified.setChecked(True)
        shown = [c._dossier_at(r) for r in range(c._table.rowCount())
                 if not c._table.isRowHidden(r)]
        self.assertEqual(shown, [d1])
        self.assertIn("1 of 3", c._count_lbl.text())

    def test_an_unqualified_lead_can_be_picked_exported_and_opened(self):
        from PySide6.QtWidgets import QLabel
        lead = self._lead("Aarti", 80, "Dubai, United Arab Emirates")
        c = CK.LeadsCockpit()
        c.set_dossiers([], all_leads=[lead])
        got = []
        c.exportRequested.connect(got.append)
        c._table.item(0, 0).setCheckState(Qt.Checked)
        c._b_export.click()
        self.assertEqual([d.lead for d in got[0]], [lead])
        c._table.setCurrentCell(0, 1)
        texts = [w.text() for w in c._drawer_w.findChildren(QLabel)]
        self.assertTrue(any("Not qualified yet" in t for t in texts))
        self.assertTrue(any("Dubai" in t for t in texts))

    def test_analytics_counts_only_the_qualified(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        w = CK.LeadsWorkspace(leads_folder=folder.name)
        w.set_dossiers([d1], [], all_leads=[d1.lead, self._lead("A", 60)])
        self.assertEqual(w.leads._table.rowCount(), 2)
        self.assertEqual(len(w._analytics._dossiers), 1)


class ALeadsOnlyRunShowsItsPeople(_Workbench):

    def test_opening_a_leads_only_run_lists_every_person(self):
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i}", title="Plant Head", company=f"Co {i}",
                      email=f"p{i}@x.com", fit_score=60 + i) for i in range(4)]
        res = RunResult(dossiers=[], total_in_sheet=4, signal_source="",
                        all_leads=leads)
        wb = self._WB.LeadsWorkbench({})
        wb._show_result(res, [])
        self.assertEqual(wb._cockpit.leads._table.rowCount(), 4)
        self.assertTrue(wb._export_btn.isEnabled())


class ASheetImportThatFoundNobody(_Workbench):
    """22-Sep-2026: a company-research export (Company Name, Industry, City…,
    never a person) went into Import a sheet and came back with nothing — a
    real, successful run, since sheet.py correctly skips a row with no name
    column. On screen that read as the button doing nothing: "0 ready to
    send" before the click, "0 ready to send" after. The empty state now
    says which of the two things happened."""

    def _empty_run(self):
        from prospector.engine import RunResult
        return RunResult(dossiers=[], total_in_sheet=0, signal_source="",
                         all_leads=[])

    def test_a_sheet_with_no_contact_signal_says_so(self):
        import openpyxl
        path = os.path.join(self._tmp, "companies.xlsx")
        wb_file = openpyxl.Workbook()
        wb_file.active.append(["Company Name", "Industry Category", "City"])
        wb_file.active.append(["Acme Tooling", "Packaging Machinery", "Vadodara"])
        wb_file.save(path)

        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("sheet")
        wb._path = path
        wb._show_result(self._empty_run(), [])

        empty = wb._cockpit.leads._empty
        self.assertIn("no name, e-mail or LinkedIn column", empty.title.text())
        self.assertIn("name", empty.body.text().lower())
        self.assertTrue(empty.body.text().strip())

    def test_a_real_leads_sheet_that_just_has_nobody_new_keeps_the_default(self):
        # Same empty RunResult, but the FILE itself has a name column — the
        # sheet is fine, this run simply found nobody (everyone in it was
        # filtered or already seen). Must not claim the sheet is the problem.
        import openpyxl
        path = os.path.join(self._tmp, "leads.xlsx")
        wb_file = openpyxl.Workbook()
        wb_file.active.append(["Name", "Company", "Email"])
        wb_file.save(path)   # header only — genuinely nobody in it

        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("sheet")
        wb._path = path
        wb._show_result(self._empty_run(), [])

        empty = wb._cockpit.leads._empty
        self.assertNotIn("no name, e-mail or LinkedIn column", empty.title.text())
        self.assertEqual(empty.title.text(), self._WB.i18n.t("No leads yet"))

    def test_icp_mode_is_never_told_it_needs_a_contact_signal(self):
        # An empty Find-people run has nothing to do with a sheet at all;
        # the sheet-specific message must only ever fire in sheet mode.
        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("icp")
        wb._show_result(self._empty_run(), [])
        self.assertNotIn("no name, e-mail or LinkedIn column",
                         wb._cockpit.leads._empty.title.text())

    def test_a_missing_or_unreadable_file_does_not_crash_the_message(self):
        # has_name_column() itself can raise (a deleted file, a locked one);
        # _show_result must still put something sane on screen rather than
        # let the exception through.
        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("sheet")
        wb._path = os.path.join(self._tmp, "does-not-exist.xlsx")
        wb._show_result(self._empty_run(), [])   # must not raise
        self.assertTrue(wb._cockpit.leads._empty.title.text())


class ACompanyOnlySheetLoadsIntoFindPeoplesFilters(_Workbench):
    """22-Sep-2026, twice over. First: rather than tell the owner a
    company-only sheet needs a different screen, its companies were made to
    go straight into a real Find-people SEARCH, MAX_FACET_VALUES (the same
    real cap a person pasting a list into the filter panel hits) at a time.
    Second, the same day: that ran the search on its own, unasked — an
    owner who only picked a company list did not thereby ask Prism to spend
    Exa credits on it. Importing this kind of sheet now only ever LOADS —
    its companies (and a suggested decision-maker seniority) land as
    ordinary, visible, editable chips on the Find people tab, exactly as if
    the owner had pasted the list in by hand, and nothing is searched until
    Find people is pressed on its own, as a separate, informed decision."""

    def _sheet(self, name, companies, header="Company Name"):
        import openpyxl
        path = os.path.join(self._tmp, name)
        wbf = openpyxl.Workbook()
        wbf.active.append([header, "Industry"])
        for c in companies:
            wbf.active.append([c, "Packaging Machinery"])
        wbf.save(path)
        return path

    def _workbench(self, path, cfg=None):
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self.addCleanup(setattr, self._WB, "SourceWorker", orig)
        self._WB.SourceWorker = _FakeSourceWorker
        wb = self._WB.LeadsWorkbench(cfg if cfg is not None else {"exa_api_key": "k"})
        wb._set_mode("sheet")
        wb._path = path
        return wb

    def test_choosing_a_company_only_sheet_relabels_the_button(self):
        # 22-09-2026, the follow-up to the follow-up: a customer pressed a
        # button that said "Load the sheet" and was startled to watch it go
        # off and run a live, paid Exa search instead. _choose_file must
        # relabel the button the moment it can tell which kind of file this
        # is — and, since this press only ever loads now, not promise a
        # search either. The secondary button has nothing to do yet.
        path = self._sheet("companies.xlsx", ["Acme Tooling", "Beta Corp"])
        wb = self._workbench(path)                 # sets wb._path directly
        self.assertEqual(wb._prepare.text(), "Load the sheet")  # not yet told
        wb._update_prepare_labels()                 # what _choose_file calls
        self.assertEqual(wb._prepare.text(), "Add companies to Find people")
        self.assertTrue(wb._prepare_all.isHidden())

    def test_a_real_contacts_sheet_keeps_load_the_sheet(self):
        path = os.path.join(self._tmp, "contacts.xlsx")
        import openpyxl
        wbf = openpyxl.Workbook()
        wbf.active.append(["Name", "Company", "Email"])
        wbf.active.append(["Jane Doe", "Acme Tooling", "jane@acme.example"])
        wbf.save(path)
        wb = self._workbench(path)
        wb._update_prepare_labels()
        self.assertEqual(wb._prepare.text(), "Load the sheet")
        self.assertEqual(wb._prepare_all.text(), "Load and prepare")
        self.assertFalse(wb._prepare_all.isHidden())

    def test_a_small_sheet_loads_every_company_in_one_press_and_never_searches(self):
        path = self._sheet("small.xlsx", [f"Company {i}" for i in range(1, 6)])
        wb = self._workbench(path)
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(_FakeSourceWorker.made, [])       # nothing searched
        self.assertEqual(wb._filters.spec().companies.include,
                         [f"Company {i}" for i in range(1, 6)])
        self.assertEqual(wb._sheet_company_offset, 5)
        self.assertEqual(wb._mode, "icp")                   # switched to review
        self.assertTrue(wb._status.text())

    def test_pressing_find_people_afterwards_is_the_real_search(self):
        # The whole point: loading is one press, searching is a separate,
        # deliberate one — the exact same button an ordinary ICP search
        # already uses, now sitting in front of the owner with the sheet's
        # companies already in its filters.
        path = self._sheet("small.xlsx", ["Acme Tooling", "Beta Corp"])
        wb = self._workbench(path)
        wb._on_prepare(leads_only=True, emails="later")     # load
        self.assertEqual(_FakeSourceWorker.made, [])
        wb._on_prepare(leads_only=True, emails="later")     # now in icp mode
        self.assertEqual(len(_FakeSourceWorker.made), 1)
        spec = _FakeSourceWorker.made[0].kwargs["spec"]
        self.assertEqual(spec["companies"]["include"], ["Acme Tooling", "Beta Corp"])

    def test_a_big_sheet_is_loaded_max_facet_values_at_a_time(self):
        from prospector.filters import MAX_FACET_VALUES
        n = MAX_FACET_VALUES * 2 + 10          # three uneven batches
        path = self._sheet("big.xlsx", [f"Company {i}" for i in range(1, n + 1)])
        wb = self._workbench(path)
        seen = []
        sizes = []
        for _ in range(3):
            wb._set_mode("sheet")               # back to Import a sheet, as a
                                                 # customer would between batches
            wb._on_prepare(leads_only=True, emails="later")
            batch = wb._filters.spec().companies.include
            sizes.append(len(batch))
            seen.extend(batch)
        self.assertEqual(sizes, [MAX_FACET_VALUES, MAX_FACET_VALUES, 10])
        # Every company covered exactly once across the three presses —
        # no gaps, no repeats.
        self.assertEqual(seen, [f"Company {i}" for i in range(1, n + 1)])
        self.assertEqual(wb._sheet_company_offset, n)
        self.assertEqual(_FakeSourceWorker.made, [])        # still never searched

    def test_a_fourth_press_once_the_sheet_is_exhausted_loads_nothing(self):
        from prospector.filters import MAX_FACET_VALUES
        path = self._sheet("exact.xlsx",
                           [f"Company {i}" for i in range(1, MAX_FACET_VALUES + 1)])
        wb = self._workbench(path)
        wb._on_prepare(leads_only=True, emails="later")
        wb._set_mode("sheet")
        wb._on_prepare(leads_only=True, emails="later")    # nothing left
        self.assertIn("already", wb._status.text())

    def test_choosing_a_different_sheet_restarts_the_batch_from_zero(self):
        path_a = self._sheet("a.xlsx", ["A1", "A2", "A3"])
        wb = self._workbench(path_a)
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(wb._sheet_company_offset, 3)
        path_b = self._sheet("b.xlsx", ["B1", "B2"])
        wb._set_mode("sheet")
        wb._path = path_b
        wb._sheet_company_offset = 0            # what _choose_file does
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(wb._filters.spec().companies.include, ["B1", "B2"])

    def test_forward_filled_company_blocks_are_read_like_a_contacts_sheet(self):
        # sheet.py's own reason to forward-fill Company down a block applies
        # here too — a company-research export grouped under one heading,
        # blank on every row after the first, is a common export shape.
        path = os.path.join(self._tmp, "blocked.xlsx")
        import openpyxl
        wbf = openpyxl.Workbook()
        wbf.active.append(["Company", "Note"])
        wbf.active.append(["Acme Tooling", "primary contact unlisted"])
        wbf.active.append(["", "secondary site"])
        wbf.active.append(["Beta Corp", "new lead"])
        wbf.save(path)
        wb = self._workbench(path)
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(wb._filters.spec().companies.include,
                         ["Acme Tooling", "Beta Corp"])

    def test_a_sheet_that_has_names_is_not_treated_as_companies(self):
        # The ordinary sheet-import path (workers.ProspectorWorker) must be
        # completely unaffected by any of this.
        import openpyxl
        path = os.path.join(self._tmp, "has_names.xlsx")
        wbf = openpyxl.Workbook()
        wbf.active.append(["Name", "Company"])
        wbf.active.append(["Jane Doe", "Acme Tooling"])
        wbf.save(path)
        wb = self._workbench(path)
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(_FakeSourceWorker.made, [])   # SourceWorker never ran
        self.assertIsInstance(wb._worker, self._WB.ProspectorWorker)

    def test_no_key_is_needed_just_to_load_companies_into_filters(self):
        # Loading costs nothing — only the search the owner presses
        # separately, afterwards, does — so no key is asked for here.
        path = self._sheet("needs_key.xlsx", ["Only Co"])
        wb = self._workbench(path, cfg={})            # no exa_api_key
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(_FakeSourceWorker.made, [])
        self.assertEqual(wb._filters.spec().companies.include, ["Only Co"])
        self.assertEqual(wb._sheet_company_offset, 1)
        self.assertNotIn("Exa API key", wb._status.text())

    def test_untouched_default_filters_load_broad_seniority_not_one_vertical(self):
        # Live report, 22-Sep-2026: a real 193-company run came back with
        # "No people came back" on every batch — not because Exa found
        # nobody, but because a fresh workbench's default job titles are
        # ONE vertical ("Head of Digital Transformation", automation heads
        # at automobile/steel/mining companies), silently reused for
        # companies that are none of those. A small Vadodara pharma-
        # machinery manufacturer has an owner; it does not have a "Head of
        # Digital Transformation", and asking for exactly that title found
        # nobody at any of them.
        path = self._sheet("default_filters.xlsx", ["Only Co"])
        wb = self._workbench(path)            # untouched: still _default_spec()
        wb._on_prepare(leads_only=True, emails="later")
        spec = wb._filters.spec()
        self.assertEqual(spec.job_titles.include, [])
        self.assertEqual(spec.industries.include, [])
        self.assertEqual(spec.seniority.include,
                         list(self._WB._COMPANY_SEARCH_SENIORITY))

    def test_filters_the_owner_actually_set_are_respected(self):
        # The opposite case: the owner switched to Find people, set their
        # own titles, then went back to Import a sheet. That choice is
        # deliberate and must not be silently overridden.
        path = self._sheet("custom_filters.xlsx", ["Only Co"])
        wb = self._workbench(path)
        wb._filters.set_spec(self._WB.SearchSpec.from_dict(
            {"job_titles": {"include": ["Purchase Head"]}}))
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(wb._filters.spec().job_titles.include, ["Purchase Head"])

    def test_stale_titles_are_overridden_even_if_something_else_touched_the_spec(self):
        # The actual bug behind the live report even after the seniority
        # fix landed: the original gate compared the WHOLE spec against
        # _default_spec() byte-for-byte, so ANY other field differing —
        # here, a location someone typed into Find people at some earlier
        # point the same session — silently kept the stale automation-
        # vertical job titles with no sign anything had gone wrong. The
        # only thing that should matter is whether the TITLES are still
        # the ones this path must not use.
        path = self._sheet("touched_elsewhere.xlsx", ["Only Co"])
        wb = self._workbench(path)
        spec = wb._filters.spec()
        spec.locations.exclude = ["India"]   # unrelated field, touched
        wb._filters.set_spec(spec)
        wb._on_prepare(leads_only=True, emails="later")
        got = wb._filters.spec()
        self.assertEqual(got.job_titles.include, [])
        self.assertEqual(got.seniority.include,
                         list(self._WB._COMPANY_SEARCH_SENIORITY))

    def test_empty_titles_with_the_owners_own_seniority_keeps_that_seniority(self):
        # Empty job titles (not the stale default, just nothing) with the
        # owner's OWN seniority choice already set must not be clobbered
        # by the company-search default.
        path = self._sheet("own_seniority.xlsx", ["Only Co"])
        wb = self._workbench(path)
        wb._filters.set_spec(self._WB.SearchSpec.from_dict(
            {"seniority": {"include": ["vp"]}}))
        wb._on_prepare(leads_only=True, emails="later")
        self.assertEqual(wb._filters.spec().seniority.include, ["vp"])

    def test_a_managing_director_ceo_or_founder_is_not_filtered_out(self):
        # Live report, 22-Sep-2026: a real 50-company batch came back with
        # 2199 people found and 2162 of them thrown out as "outside your
        # filters (seniority)" — only 37 survived. filters.seniority_of()
        # reads "Managing Director", "CEO", "Chairman" and "President" as
        # c_suite, and "Founder"/"Co-Founder" as founder, never as director
        # or owner (its own docstring says so) — exactly the titles a real
        # Indian SME's decision-maker carries. The original two-term list
        # ("owner", "director") asked Exa for those roles AND rejected
        # anyone whose actual title wasn't literally "Owner" or "Director",
        # discarding almost everyone a company-sheet search exists to find.
        from prospector.filters import match_person
        path = self._sheet("titles.xlsx", ["Only Co"])
        wb = self._workbench(path)
        wb._on_prepare(leads_only=True, emails="later")
        spec = wb._filters.spec()
        for title in ("Managing Director", "CEO", "Chairman", "President",
                      "Founder", "Co-Founder", "Founder & CEO",
                      "Director", "Owner"):
            lead = Lead(name="P", title=title, company="Only Co")
            self.assertEqual(match_person(spec, lead), "", title)
        # Still not a decision-maker: an ordinary manager or engineer must
        # keep being rejected — this widens who counts, not everyone.
        for title in ("Quality Engineer", "Assistant Manager", "Intern"):
            lead = Lead(name="P", title=title, company="Only Co")
            self.assertEqual(match_person(spec, lead), "seniority", title)


class _FakeQualifyWorker(_FakeSourceWorker):
    """Stands in for LeadsQualifyWorker: records the leads it was handed."""
    made: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _FakeQualifyWorker.made.append(self)


class QualifySelected(_Workbench):
    """Tick people a run sourced but never qualified and press Qualify & draft:
    the qualify pass runs on exactly them, their rows turn into real outcomes,
    their drafts join Send, and the session is saved with them."""

    def _leads_only_run(self, wb, n=4):
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i}", title="Plant Head", company=f"Co {i}",
                      email=f"p{i}@x.com", fit_score=60 + i) for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="",
                        all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "roles": ["Plant Head"],
                           "offer": "Automation retrofits"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return leads

    def _tick(self, cockpit, leads):
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead in leads:
                cockpit._table.item(r, 0).setCheckState(Qt.Checked)

    def test_the_button_arms_only_for_unqualified_rows(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        other = Lead(name="Vaibhav", title="Plant Head", company="Globex", fit_score=50)
        c = CK.LeadsCockpit()
        c.set_dossiers([d1], all_leads=[d1.lead, other])
        self.assertFalse(c._b_qualify.isHidden())
        self._tick(c, [d1.lead])
        self.assertFalse(c._b_qualify.isEnabled())       # already qualified
        self._tick(c, [other])
        self.assertTrue(c._b_qualify.isEnabled())
        got = []
        c.qualifyRequested.connect(got.append)
        c._b_qualify.click()
        self.assertEqual({d.lead.name for d in got[0]}, {"Kunyi", "Vaibhav"})

    def test_the_button_hides_when_everyone_is_qualified(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("Kunyi", 96, "k@x.com", "valid")])
        self.assertTrue(c._b_qualify.isHidden())

    def test_only_the_unqualified_people_go_to_the_worker(self):
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        wb._confirm_qualify = lambda n: True
        _FakeQualifyWorker.made = []
        orig = self._WB.LeadsQualifyWorker
        self._WB.LeadsQualifyWorker = _FakeQualifyWorker
        try:
            self._tick(wb._cockpit.leads, leads[:2])
            wb._qualify_selected(wb._cockpit.leads.selected())
        finally:
            self._WB.LeadsQualifyWorker = orig
        self.assertEqual(len(_FakeQualifyWorker.made), 1)
        worker = _FakeQualifyWorker.made[0]
        self.assertTrue(worker.started)
        self.assertEqual({l.name for l in worker.args[0]}, {"P0", "P1"})
        self.assertEqual(worker.kwargs["roles"], ["Plant Head"])
        self.assertEqual(wb._jobs, 1)

    def test_a_big_batch_asks_first_and_a_no_starts_nothing(self):
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb, n=12)
        wb._confirm_qualify = lambda n: False
        _FakeQualifyWorker.made = []
        orig = self._WB.LeadsQualifyWorker
        self._WB.LeadsQualifyWorker = _FakeQualifyWorker
        try:
            self._tick(wb._cockpit.leads, leads)
            wb._qualify_selected(wb._cockpit.leads.selected())
        finally:
            self._WB.LeadsQualifyWorker = orig
        self.assertEqual(_FakeQualifyWorker.made, [])
        self.assertEqual(wb._jobs, 0)

    def test_results_fold_into_the_run_and_the_session(self):
        from addons.leads import sessions
        from prospector.engine import RunResult
        from prospector.reach import Draft
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        hot = Dossier(lead=leads[0], verdict="hot", score=90, opener="Hi P0")
        cold = Dossier(lead=leads[1], verdict="cold", score=20)
        wb._jobs = 1
        wb._on_qualified(RunResult(dossiers=[hot, cold], total_in_sheet=2,
                                   signal_source="", all_leads=[leads[0], leads[1]]),
                         [Draft(dossier=hot, subject="Hi", body="Hello P0")])
        cockpit = wb._cockpit.leads
        self.assertEqual(cockpit._table.rowCount(), 4)            # nobody listed twice
        still = {cockpit._dossier_at(r).lead.name for r in range(4)
                 if cockpit._dossier_at(r).status == CK.UNQUALIFIED}
        self.assertEqual(still, {"P2", "P3"})
        self.assertTrue(wb._send_btn.isEnabled())
        self.assertEqual(wb._jobs, 0)
        head = sessions.list_sessions(self._sessions)[0]
        self.assertEqual((head["counts"]["qualified"], head["counts"]["drafted"]), (2, 1))
        self.assertEqual(head["mode"], "icp")        # no longer a leads-sheet-only run

    def _patched_worker(self):
        _FakeQualifyWorker.made = []
        orig = self._WB.LeadsQualifyWorker
        self._WB.LeadsQualifyWorker = _FakeQualifyWorker
        self.addCleanup(setattr, self._WB, "LeadsQualifyWorker", orig)

    def test_without_a_groq_key_nothing_starts_and_it_says_so(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._leads_only_run(wb)
        wb._confirm_qualify = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads[:1])
        wb._qualify_selected(wb._cockpit.leads.selected())
        self.assertEqual(_FakeQualifyWorker.made, [])
        self.assertIn("Groq key", wb._status.text())
        self.assertEqual(wb._jobs, 0)

    def test_a_failed_pass_is_not_stored_as_qualified_and_stays_retryable(self):
        from addons.leads import sessions
        from prospector.engine import RunResult
        from prospector.models import NO_MODEL
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        failed = [Dossier(lead=l, status=NO_MODEL, note="No Groq API key configured.")
                  for l in leads[:2]]
        wb._jobs = 1
        wb._on_qualified(RunResult(dossiers=failed, total_in_sheet=2,
                                   signal_source="", all_leads=leads[:2]), [])
        cockpit = wb._cockpit.leads
        self.assertEqual(cockpit._table.rowCount(), 4)
        self.assertTrue(all(cockpit._dossier_at(r).status == CK.UNQUALIFIED
                            for r in range(4)))
        self.assertIn("couldn't be qualified", wb._status.text())
        head = sessions.list_sessions(self._sessions)[0]
        self.assertEqual((head["mode"], head["counts"]["qualified"]),
                         ("icp_leads_only", 0))
        self._tick(cockpit, leads[:2])
        self.assertTrue(cockpit._b_qualify.isEnabled())       # try again

    def test_a_retry_that_works_replaces_the_failed_dossier(self):
        from prospector.engine import RunResult
        from prospector.models import QUALIFY_ERROR
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        good = _dos("Kunyi", 96, "k@x.com", "valid")
        broken = _dos("Vaibhav", 80, "v@x.com", "")
        broken.status, broken.note = QUALIFY_ERROR, "Groq rate limit"
        wb._start_export = lambda *a, **k: None
        wb._next_mode, wb._next_params = "icp", {"mode": "icp", "roles": ["Founder"]}
        wb._jobs = 1
        wb._on_prepared(RunResult(dossiers=[good, broken], total_in_sheet=2,
                                  signal_source="", all_leads=[good.lead, broken.lead]), [])
        cockpit = wb._cockpit.leads
        self._tick(cockpit, [broken.lead])
        self.assertTrue(cockpit._b_qualify.isEnabled())
        wb._confirm_qualify = lambda n: True
        self._patched_worker()
        wb._qualify_selected(cockpit.selected())
        self.assertEqual([l.name for l in _FakeQualifyWorker.made[0].args[0]], ["Vaibhav"])
        redone = Dossier(lead=broken.lead, verdict="warm", score=70)
        wb._on_qualified(RunResult(dossiers=[redone], total_in_sheet=1,
                                   signal_source="", all_leads=[broken.lead]), [])
        self.assertEqual(cockpit._table.rowCount(), 2)
        self.assertEqual(len(wb._res.dossiers), 2)
        self.assertIn(redone, wb._res.dossiers)
        self.assertNotIn(broken, wb._res.dossiers)
        self.assertTrue(cockpit._b_qualify.isHidden())        # nothing left to qualify

    def test_a_sheet_run_keeps_its_own_scoring(self):
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        wb._session_mode = "sheet"
        wb._run_params = {"mode": "sheet", "roles": ["Plant Head"]}
        wb._confirm_qualify = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads[:1])
        wb._qualify_selected(wb._cockpit.leads.selected())
        self.assertEqual(_FakeQualifyWorker.made[0].kwargs["roles"], [])

    def test_the_worker_spends_the_pass_on_exactly_those_leads(self):
        from unittest import mock
        from prospector.engine import RunResult
        from addons.leads.workers import LeadsQualifyWorker
        leads = [Lead(name=f"P{i}", company=f"Co {i}", fit_score=50) for i in range(3)]
        calls = []

        def fake_run_leads(passed, offer, cfg, **kw):
            calls.append((passed, kw))
            return RunResult(dossiers=[Dossier(lead=l) for l in passed],
                             total_in_sheet=len(passed), signal_source="",
                             all_leads=list(passed))

        w = LeadsQualifyWorker(leads, "Automation", {}, roles=["Plant Head"],
                               verify_limit=0)
        done = []
        w.done.connect(lambda res, drafts: done.append((res, drafts)))
        with mock.patch("prospector.signals.make_provider", return_value=None), \
                mock.patch("prospector.engine.run_leads", side_effect=fake_run_leads), \
                mock.patch("prospector.verify.collect_keys", return_value={}), \
                mock.patch("prospector.reach.draft_batch", return_value=[]):
            w.run()                                  # inline: no thread
        self.assertEqual(len(calls), 1)
        passed, kw = calls[0]
        self.assertEqual(passed, leads)
        self.assertEqual(kw["limit"], 3)
        self.assertIsNone(kw.get("skip"))            # they belong to this session
        self.assertEqual(kw["roles"], ["Plant Head"])
        self.assertEqual(len(done[0][0].dossiers), 3)


class _FakeEmailWorker(_FakeSourceWorker):
    """Stands in for LeadsEmailWorker: records the leads it was handed."""
    made: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _FakeEmailWorker.made.append(self)


class FindEmailsOnTheRowsYouPick(_Workbench):
    """The other half of "find people first": the bulk bar's Find e-mails. It
    arms for rows without a confirmed address, hands the worker exactly those
    leads, and what comes back re-renders the rows and is saved."""

    def _people(self, wb, n=3, email=""):
        """A finished Find-people run: n people, none with an address."""
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i} Singh", title="Plant Head", company=f"Co {i}",
                      email=email, fit_score=60 + i) for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="",
                        all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "offer": "Automation"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return leads

    def _tick(self, cockpit, leads):
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead in leads:
                cockpit._table.item(r, 0).setCheckState(Qt.Checked)

    def _patched_worker(self):
        _FakeEmailWorker.made = []
        orig = self._WB.LeadsEmailWorker
        self._WB.LeadsEmailWorker = _FakeEmailWorker
        self.addCleanup(setattr, self._WB, "LeadsEmailWorker", orig)

    def _status_at(self, cockpit, lead) -> str:
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead is lead:
                return cockpit._table.item(r, CK._C_STATUS).text()
        return ""

    def test_the_bulk_bar_arms_for_rows_without_a_confirmed_address(self):
        c = CK.LeadsCockpit()
        good = _dos("Kunyi", 96, "k@x.com", "valid")
        guess = _dos("Vaibhav", 80, "v@x.com", "")
        none = _dos("NoMail", 60, "")
        c.set_dossiers([good, guess, none])
        self.assertFalse(c._b_emails.isHidden())
        self._tick(c, [good.lead])
        self.assertFalse(c._b_emails.isEnabled())         # already verified
        self._tick(c, [guess.lead, none.lead])
        self.assertTrue(c._b_emails.isEnabled())
        got = []
        c.emailsRequested.connect(got.append)
        c._b_emails.click()
        self.assertEqual({d.lead.name for d in got[0]},
                         {"Kunyi", "Vaibhav", "NoMail"})

    def test_the_button_goes_away_once_every_address_is_confirmed(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("Kunyi", 96, "k@x.com", "valid")])
        self.assertTrue(c._b_emails.isHidden())

    def test_the_workspace_re_exposes_the_signal(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        w = CK.LeadsWorkspace(leads_folder=folder.name)
        d = _dos("Kunyi", 96, "", "")
        w.set_dossiers([d], [])
        got = []
        w.emailsRequested.connect(got.append)
        w.leads._table.item(0, 0).setCheckState(Qt.Checked)
        w.leads._b_emails.click()
        self.assertEqual(got, [[d]])

    def test_exactly_the_ticked_leads_go_to_the_worker(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads[:2])
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual(len(_FakeEmailWorker.made), 1)
        worker = _FakeEmailWorker.made[0]
        self.assertTrue(worker.started)
        self.assertEqual([l.name for l in worker.args[0]], ["P0 Singh", "P1 Singh"])
        self.assertEqual(wb._jobs, 1)

    def test_the_rails_verify_setting_does_not_cap_this_action(self):
        """Verify is a budget for a RUN, whose top slice the run picks. These
        rows were ticked by hand, so none of them is left as an unchecked
        guess — not even with the rail wound down to nobody."""
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        wb._verify_limit.setValue(0)
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        worker = _FakeEmailWorker.made[0]
        self.assertNotIn("verify_limit", worker.kwargs)
        self.assertEqual(len(worker.args[0]), 3)

    def test_what_comes_back_re_renders_the_rows_and_is_saved(self):
        from addons.leads import sessions
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        cockpit = wb._cockpit.leads
        self.assertEqual(self._status_at(cockpit, leads[0]), "No email")
        # What the worker does on its thread: an address each, one confirmed.
        leads[0].email, leads[1].email = "p0@co0.com", "p1@co1.com"
        leads[0].extra["email_check"] = "valid"
        wb._jobs = 1
        wb._on_emails_found(2, 1)
        self.assertEqual(self._status_at(cockpit, leads[0]), "Verified")
        self.assertEqual(self._status_at(cockpit, leads[1]), "Guessed")
        self.assertEqual(self._status_at(cockpit, leads[2]), "No email")
        self.assertIn("2 new address", wb._status.text())
        self.assertIn("1 verified", wb._status.text())
        self.assertEqual(wb._jobs, 0)
        loaded = sessions.load(self._sessions, wb._session_id)
        self.assertEqual([l.email for l in loaded["all_leads"]][:2],
                         ["p0@co0.com", "p1@co1.com"])

    def test_a_second_one_cannot_start_while_a_job_runs(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        picked = wb._cockpit.leads.selected()
        wb._find_emails(picked)
        wb._find_emails(picked)                      # the job counter holds it
        self.assertEqual(len(_FakeEmailWorker.made), 1)
        self.assertEqual(wb._jobs, 1)

    def test_a_big_batch_asks_first_and_a_no_starts_nothing(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb, n=12)
        wb._confirm_emails = lambda n: False
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual(_FakeEmailWorker.made, [])
        self.assertEqual(wb._jobs, 0)

    def test_leads_that_are_already_verified_are_left_alone(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb, n=2, email="p@x.com")
        for lead in leads:
            lead.extra["email_check"] = "valid"
        self._patched_worker()
        wb._cockpit.set_dossiers([], [], leads)      # re-render with the statuses
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual(_FakeEmailWorker.made, [])
        self.assertIn("already have a verified address", wb._status.text())

    def test_an_imported_sheet_can_have_its_emails_found_too(self):
        """The sheet the owner exported from Prism comes back with names and
        no addresses — the whole point of bringing it back is to find them."""
        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("sheet")
        leads = self._people(wb)
        wb._session_mode = "sheet"
        wb._run_params = {"mode": "sheet", "sheet_path": "Prism leads.xlsx"}
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual([l.name for l in _FakeEmailWorker.made[0].args[0]],
                         [l.name for l in leads])


class ApolloIsNotOfferedOnceItsPlanRefuses(_Workbench):
    """Apollo's search endpoints are not in its free plan, so a 403 is the end
    of Apollo for this key: the rail goes back to Exa, the switch is off with
    Apollo's own words on it, and the config remembers — a flag, never a key."""

    def _refusal(self) -> str:
        from prospector import apollo
        return apollo.SCOPED_KEY.format(path="/mixed_people/api_search")

    def _blocked(self, wb, saved=None):
        from unittest import mock
        with mock.patch("core_bridge.config.load",
                        return_value={"apollo_api_key": "ap-k"}), \
                mock.patch("core_bridge.config.save",
                           side_effect=(saved if saved is not None else []).append):
            wb._jobs = 1
            wb._on_source_blocked(self._refusal())

    def test_a_403_run_disables_apollo_and_flips_the_source_to_exa(self):
        saved = []
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k"})
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")
        self._blocked(wb, saved)
        self.assertEqual(wb._source, "exa")
        self.assertTrue(wb._src_exa.isChecked())
        self.assertFalse(wb._src_apollo.isEnabled())
        self.assertIn("Apollo would not let this key", wb._src_apollo.toolTip())
        self.assertIn("paid Apollo plan", wb._status.text())
        self.assertEqual(wb._jobs, 0)
        # The flag is a flag: a switch the next launch reads, not the key.
        self.assertIs(saved[-1]["apollo_api_blocked"], True)
        self.assertIs(wb.cfg["apollo_api_blocked"], True)
        # And it cannot be picked again by a click or by an old session.
        wb._src_apollo.click()
        wb._restore_inputs({"mode": "icp", "source": "apollo"})
        self.assertEqual(wb._source, "exa")

    def test_the_next_launch_does_not_offer_it_at_all(self):
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k",
                                      "apollo_api_blocked": True})
        self.assertEqual(wb._source, "exa")
        self.assertFalse(wb._src_apollo.isEnabled())
        self.assertIn("free Apollo plan", wb._src_apollo.toolTip())
        wb._set_running(True)                    # a run, then the run finishing
        wb._set_running(False)
        self.assertFalse(wb._src_apollo.isEnabled())

    def test_a_different_key_lifts_the_block(self):
        from unittest import mock
        saved = []
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k"})
        self._blocked(wb)
        with mock.patch("core_bridge.config.load",
                        return_value={"apollo_api_key": "ap-k"}), \
                mock.patch("core_bridge.config.save", side_effect=saved.append):
            wb._apollo.setText("ap-new")
            wb._apollo.textEdited.emit("ap-new")      # what typing one does
        self.assertTrue(wb._src_apollo.isEnabled())
        self.assertIn("PAID Apollo plan", wb._src_apollo.toolTip())
        self.assertIs(saved[-1]["apollo_api_blocked"], False)
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")

    def test_only_a_plan_refusal_counts_as_blocked(self):
        from prospector import apollo
        from addons.leads.workers import _plan_refusal
        self.assertEqual(_plan_refusal(apollo.ApolloError(self._refusal()), apollo),
                         self._refusal())
        self.assertEqual(
            _plan_refusal(apollo.ApolloError(apollo.BAD_KEY), apollo), "")
        self.assertEqual(
            _plan_refusal(apollo.ApolloError(apollo.RATE_LIMITED), apollo), "")


class ExportsStayHonestWithoutAddresses(_Workbench):
    """A lead with no address exports as a BLANK e-mail — never the guess the
    old flow used to make on the way past."""

    def test_the_sheet_and_the_csv_leave_a_missing_address_empty(self):
        import csv as _csv
        from prospector import exports
        lead = Lead(name="Ana Ruiz", company="Acme", title="Owner")
        self.assertEqual(exports.build_email_checks([lead]), {})   # nothing to look up
        self.assertEqual(exports.check_of(lead, {}), "no-domain")
        wb = self._WB.LeadsWorkbench({})
        path = os.path.join(self._tmp, "selected.csv")
        wb._write_leads_csv(CK.unqualified_rows([], [lead]), path)
        with open(path, encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
        self.assertEqual(rows[0]["email"], "")
        self.assertEqual(rows[0]["status"], "No email")

    def test_the_whole_run_sheet_is_written_for_a_run_with_no_addresses(self):
        """"Export sheets" writes the leads sheet and the hot list. With no
        addresses there is nothing to look up (no network) and the E-mail
        column stays empty — never the guess the old flow made on the way."""
        import openpyxl
        from prospector import exports
        leads = [Lead(name=f"P{i} Singh", company=f"Co {i}", title="Plant Head",
                      industry="Steel") for i in range(3)]
        path = exports.leads_xlsx(leads, os.path.join(self._tmp, "Prism leads.xlsx"))
        ws = openpyxl.load_workbook(path).worksheets[0]
        head = [c.value for c in ws[1]]
        col = head.index("E-mail") + 1
        self.assertEqual([ws.cell(r, col).value for r in range(2, 5)],
                         [None, None, None])
        self.assertEqual({ws.cell(r, head.index("Email check") + 1).value
                          for r in range(2, 5)}, {"no-domain"})
        exports.hotlist_xlsx([], os.path.join(self._tmp, "Prism hot list.xlsx"))


class FindPeopleFirstEmailsLater(unittest.TestCase):
    """SourceWorker with emails="later", called inline (no thread, no network):
    a run finds the PEOPLE and spends nothing on their addresses — no domain
    lookups, no verifier — and still lists everyone it found."""

    def _worker(self, emails="later", **kw):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["head"]},
                                     "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits", {}, leads_only=True,
                         spec=spec.to_dict(), emails=emails, **kw)
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(got["progress"].append)
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        return w, got

    @staticmethod
    def _people(n=3):
        return [Lead(name=f"P{i} Singh", company=f"Co {i}", title="Head Operations")
                for i in range(n)]

    def test_a_find_people_run_never_looks_up_an_address(self):
        from unittest import mock
        people = self._people()
        w, got = self._worker()
        with mock.patch("prospector.signals.exa_key", return_value="exa-test"), \
                mock.patch("prospector.source.source",
                           side_effect=lambda i, r, k, **kw: list(people)), \
                mock.patch("prospector.enrich.enrich") as enriched, \
                mock.patch("prospector.verify.collect_keys") as keys, \
                mock.patch("prospector.verify.find_and_verify") as checked:
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_not_called()
        keys.assert_not_called()
        checked.assert_not_called()
        res, drafts = got["done"][0]
        self.assertEqual(len(res.all_leads), 3)          # everyone is listed
        self.assertEqual(drafts, [])
        self.assertTrue(all(not l.email for l in res.all_leads))
        self.assertTrue(any("left for later" in p for p in got["progress"]))

    def test_emails_now_is_still_the_old_run(self):
        from unittest import mock
        people = self._people()
        w, got = self._worker(emails="now")
        with mock.patch("prospector.signals.exa_key", return_value="exa-test"), \
                mock.patch("prospector.source.source",
                           side_effect=lambda i, r, k, **kw: list(people)), \
                mock.patch("prospector.enrich.enrich") as enriched:
            w.run()
        self.assertEqual(got["failed"], [])
        self.assertEqual(list(enriched.call_args[0][0]), people)


class TheEmailWorkerSpendsOnTheChosenPeople(unittest.TestCase):
    """LeadsEmailWorker, called inline: blank addresses are enriched once,
    every lead goes through the free-first waterfall, and what came back is
    counted — found, and of those confirmed."""

    def _worker(self, leads, cfg=None):
        from addons.leads.workers import LeadsEmailWorker
        w = LeadsEmailWorker(leads, cfg or {})
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(lambda i, n, l: got["progress"].append((i, n, l)))
        w.done.connect(lambda f, v: got["done"].append((f, v)))
        w.failed.connect(got["failed"].append)
        return w, got

    def test_blanks_are_enriched_then_everyone_is_verified(self):
        from unittest import mock
        blank = Lead(name="Ana Ruiz", company="Acme", title="Owner")
        held = Lead(name="Bo Lund", company="Globex", title="Owner",
                    email="bo@globex.com")
        seen = []

        def fake_enrich(leads, key="", **kw):
            for l in leads:
                l.email = f"{l.name.split()[0].lower()}@acme.com"

        def fake_verify(lead, keys=None):
            seen.append((lead, dict(keys or {})))
            lead.extra["email_check"] = "valid" if "@acme" in lead.email else "catch-all"

        w, got = self._worker([blank, held], cfg={"reoon_api_key": "r"})
        with mock.patch("prospector.signals.exa_key", return_value="exa-k"), \
                mock.patch("prospector.enrich.enrich", side_effect=fake_enrich), \
                mock.patch("prospector.verify.find_and_verify", side_effect=fake_verify):
            w.run()
        self.assertEqual(got["failed"], [])
        self.assertEqual(blank.email, "ana@acme.com")
        self.assertEqual([l for l, _k in seen], [blank, held])
        self.assertEqual(got["done"], [(1, 1)])          # one found, one verified
        self.assertEqual(seen[0][1], {"reoon_api_key": "r"})

    def test_a_refused_apollo_plan_is_not_asked_to_find_either(self):
        from unittest import mock
        lead = Lead(name="Ana Ruiz", company="Acme", title="Owner",
                    email="ana@acme.com")
        keys = []
        w, _got = self._worker([lead], cfg={"apollo_api_key": "ap-k",
                                            "reoon_api_key": "r",
                                            "apollo_api_blocked": True})
        with mock.patch("prospector.signals.exa_key", return_value=""), \
                mock.patch("prospector.enrich.enrich"), \
                mock.patch("prospector.verify.find_and_verify",
                           side_effect=lambda l, k=None: keys.append(dict(k or {}))):
            w.run()
        self.assertNotIn("apollo_api_key", keys[0])
        self.assertIn("reoon_api_key", keys[0])

    def test_everyone_it_guessed_an_address_for_is_also_checked(self):
        """The regression: enrich wrote a pattern address for every blank lead
        while the verifier saw only the first `verify_limit` of them, so the
        rest reached the table and the exported sheet as guesses that read like
        findings. A guessed address only verifies safe about one time in twenty
        — an unchecked one is the expensive half of this button."""
        from unittest import mock
        leads = [Lead(name=f"P{i} Singh", company="Acme", title="Owner")
                 for i in range(30)]
        checked = []
        w, got = self._worker(leads)
        with mock.patch("prospector.signals.exa_key", return_value="exa-k"), \
                mock.patch("prospector.enrich.enrich",
                           side_effect=lambda ls, key="", **kw: [
                               setattr(l, "email", f"p{i}@acme.com")
                               for i, l in enumerate(ls)]), \
                mock.patch("prospector.verify.find_and_verify",
                           side_effect=lambda l, k=None: checked.append(l)):
            w.run()
        self.assertEqual(got["failed"], [])
        self.assertEqual(len(checked), len(leads))
        self.assertEqual(got["done"], [(30, 0)])


class TriageScoresThePersonNotTheFlow(unittest.TestCase):
    """An e-mail is worth points only where having one says something about the
    LEAD. A run that has not fetched addresses yet leaves everyone blank, so
    the old +15 (and "no email" on all of them) scored the flow."""

    def _lead(self, name, email=""):
        return Lead(name=name, title="Plant Head", company="Acme",
                    industry="Steel Manufacturing", email=email)

    def test_an_address_less_batch_is_not_marked_down_for_it(self):
        from prospector import triage
        leads = [self._lead("A"), self._lead("B")]
        triage.rank(leads, "steel plant automation", ["Plant Head"])
        self.assertTrue(all("no email" not in l.fit_reason for l in leads))
        with_email = self._lead("C")
        scored, _why = triage.score_lead(with_email, "steel plant automation",
                                         ["Plant Head"], False)
        self.assertEqual(leads[0].fit_score, scored)

    def test_a_batch_that_carries_addresses_still_scores_them(self):
        from prospector import triage
        has, hasnt = self._lead("A", "a@acme.com"), self._lead("B")
        triage.rank([has, hasnt], "steel plant automation", ["Plant Head"])
        self.assertEqual(has.fit_score - hasnt.fit_score, 15)
        self.assertIn("no email", hasnt.fit_reason)


# Every key the "?" walkthrough asks this screen for. Spelled out so renaming a
# widget the tour points at fails here rather than on the owner's screen.
_COCKPIT_KEYS = ("hide_filters", "toolbar_count", "view_toggle", "sort",
                 "refine_search", "refine_fit", "refine_qualified_only",
                 "refine_deliverability", "table", "select_all", "col_lead",
                 "col_focus", "col_fit", "col_status", "col_signal")
_BULK_KEYS = ("bulk_bar", "bulk_verify", "bulk_emails", "bulk_save",
              "bulk_export", "bulk_qualify", "bulk_sequence")
_TAB_KEYS = ("tab_leads", "tab_sessions", "tab_lists", "tab_saved",
             "tab_sequences", "tab_analytics")
_SEARCH_KEYS = ("source_switch", "mode_switch", "run_target", "run_qualify",
                "run_verify", "offer", "net_new", "btn_find", "btn_prepare",
                "keys_box")


def _descends(widget, root) -> bool:
    while widget is not None:
        if widget is root:
            return True
        widget = widget.parentWidget()
    return False


class PointAtMeCockpit(unittest.TestCase):
    """The guided walkthrough asks the cockpit where each part IS
    (help_targets) and to make it reachable (help_reveal). Every key answers
    with a real widget of this screen — or a region of one, for a column the
    header paints itself — and a reveal never ticks a row, never touches a
    filter and never starts anything."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2])

    def test_every_key_points_at_something_on_this_screen(self):
        targets = self.c.help_targets()
        # No row is ticked and no lead open, so the bulk bar and the drawer are
        # not on screen to be pointed at.
        self.assertEqual(sorted(targets), sorted(_COCKPIT_KEYS))
        for key, target in targets.items():
            widget, rect = target if isinstance(target, tuple) else (target, None)
            self.assertTrue(_descends(widget, self.c), key)
            if rect is not None:
                self.assertFalse(rect.isEmpty(), key)

    def test_the_targets_are_the_real_controls(self):
        t = self.c.help_targets()
        self.assertIs(t["hide_filters"], self.c._filters_btn)
        self.assertIs(t["toolbar_count"], self.c._count_lbl)
        self.assertIs(t["view_toggle"], self.c._seg)
        self.assertIs(t["sort"], self.c._sort)
        self.assertIs(t["refine_search"], self.c._search)
        self.assertIs(t["refine_fit"], self.c._fit_min)
        self.assertIs(t["refine_qualified_only"], self.c._only_qualified)
        self.assertIs(t["table"], self.c._table)
        host, rect = t["refine_deliverability"]
        for box in self.c._status_boxes.values():
            self.assertIs(box.parentWidget(), host)
            self.assertTrue(rect.contains(box.geometry()))

    def test_a_column_key_rings_its_own_header_section(self):
        head = self.c._head
        cols = (("select_all", 0), ("col_lead", 1), ("col_focus", 2),
                ("col_fit", 3), ("col_status", 4), ("col_signal", 5))
        for key, col in cols:
            widget, rect = self.c.help_targets()[key]
            self.assertIs(widget, head)
            at = head.viewport().mapTo(head, QPoint(head.sectionViewportPosition(col), 0))
            self.assertEqual((rect.x(), rect.y()), (at.x(), at.y()), key)
            self.assertEqual(rect.width(), head.sectionSize(col), key)
            self.assertEqual(rect.height(), head.viewport().height(), key)

    def test_the_bulk_keys_arrive_with_the_first_tick(self):
        for key in _BULK_KEYS:
            self.assertNotIn(key, self.c.help_targets())
        for key in _BULK_KEYS:
            self.c.help_reveal(key)                 # must not tick a row to show off
        self.assertEqual(self.c.selected(), [])
        self.assertNotIn("bulk_bar", self.c.help_targets())
        self.c._table.item(0, 0).setCheckState(Qt.Checked)
        t = self.c.help_targets()
        self.assertIs(t["bulk_bar"], self.c._bulk_bar_w)
        self.assertIs(t["bulk_verify"], self.c._b_verify)
        self.assertIs(t["bulk_emails"], self.c._b_emails)
        self.assertIs(t["bulk_save"], self.c._b_save)
        self.assertIs(t["bulk_export"], self.c._b_export)
        self.assertIs(t["bulk_sequence"], self.c._b_seq)

    def test_qualify_is_there_while_someone_is_still_unqualified(self):
        # It leaves the bar once every lead is qualified, so the step goes too.
        self.c._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertNotIn("bulk_qualify", self.c.help_targets())
        raw = Lead(name="Sourced", title="Head", company="Acme", fit_score=50)
        self.c.set_dossiers([self.d1], all_leads=[self.d1.lead, raw])
        self.c._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertIs(self.c.help_targets()["bulk_qualify"], self.c._b_qualify)

    def test_a_folded_rail_comes_back_for_a_refine_step(self):
        self.c.set_filters_shown(False)
        self.assertNotIn("refine_fit", self.c.help_targets())
        self.c.help_reveal("refine_fit")
        self.assertFalse(self.c._rail.isHidden())
        self.assertIs(self.c.help_targets()["refine_fit"], self.c._fit_min)

    def test_the_drawer_step_opens_it_on_a_lead_and_ticks_nobody(self):
        self.assertNotIn("drawer", self.c.help_targets())
        self.c.help_reveal("drawer")
        self.assertIs(self.c.help_targets()["drawer"], self.c._drawer_panel)
        self.assertEqual(self.c._table.currentRow(), 0)
        self.assertEqual(self.c.selected(), [])

    def test_no_reveal_ticks_filters_or_starts_anything(self):
        fired = []
        for signal in (self.c.verifyRequested, self.c.emailsRequested,
                       self.c.exportRequested, self.c.saveListRequested,
                       self.c.sequenceRequested, self.c.qualifyRequested):
            signal.connect(fired.append)

        def state():
            return (self.c._search.text(), self.c._fit_min.value(),
                    self.c._only_qualified.isChecked(), self.c._sort.currentIndex(),
                    {n: b.isChecked() for n, b in self.c._status_boxes.items()},
                    self.c._view, sorted(self.c._checked), sorted(self.c._hidden))

        before = state()
        for key in _COCKPIT_KEYS + _BULK_KEYS + ("drawer", "nonsense"):
            self.c.help_reveal(key)
        self.assertEqual(state(), before)
        self.assertEqual(fired, [])
        self.assertEqual(self.c.selected(), [])

    def test_deliverability_scrolls_the_whole_grid_into_the_rail(self):
        """Aimed at the first box alone, the rail stopped with Invalid, No
        email and Mailed below its bottom edge, and the ring ran off the rail.
        The last box is brought into view first, then the first box."""
        asked = []
        self.c._rail.ensureWidgetVisible = lambda w, *a: asked.append(w)
        self.c.help_reveal("refine_deliverability")
        boxes = self.c._status_boxes
        self.assertEqual(asked, [boxes["Mailed"], boxes["Verified"]])

    def test_the_snapshot_puts_back_what_the_reveals_moved(self):
        """The walk unfolds the rail, opens the drawer on the first lead and
        scrolls the table; closing it must leave the screen as the owner had
        it — and must not untick, filter or reopen anything doing so."""
        c = self.c
        c._table.item(1, 0).setCheckState(Qt.Checked)
        c.set_filters_shown(False)
        snap = c.help_snapshot()
        for key in ("refine_fit", "refine_deliverability", "col_signal", "drawer"):
            c.help_reveal(key)
        self.assertFalse(c._rail.isHidden())
        self.assertFalse(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), 0)
        for _ in (0, 1):                            # the walk restores twice
            c.help_restore(snap)
        self.assertTrue(c._rail.isHidden())
        self.assertTrue(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), -1)
        self.assertEqual(c._table.selectedItems(), [])
        self.assertEqual(sorted(c._checked), [1])

    def test_a_drawer_the_owner_had_open_stays_open_on_his_lead(self):
        c = self.c
        c._table.setCurrentCell(1, CK._C_LEAD)
        snap = c.help_snapshot()
        c.help_reveal("refine_search")
        c._table.setCurrentCell(0, CK._C_LEAD)     # anything that moved the row
        c.help_restore(snap)
        self.assertEqual(c._table.currentRow(), 1)
        self.assertFalse(c._drawer_w.isHidden())

    def test_an_empty_screen_offers_only_what_is_on_it(self):
        empty = CK.LeadsCockpit()
        targets = empty.help_targets()
        for gone in ("table", "select_all", "col_lead", "toolbar_count",
                     "hide_filters", "drawer"):
            self.assertNotIn(gone, targets)
        self.assertIn("refine_search", targets)     # the rail is still there


class PointAtMeWorkspace(unittest.TestCase):
    """The tab strip's keys are the workspace's own; everything else it lends
    from the Leads tab, and revealing one comes back to that tab first."""

    def setUp(self):
        self.ws = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        self.ws.set_dossiers([_dos("Kunyi", 96, "k@x.com", "valid")])

    def test_the_tabs_are_its_own_keys_and_the_cockpit_lends_the_rest(self):
        t = self.ws.help_targets()
        for i, key in enumerate(_TAB_KEYS):
            self.assertIs(t[key], self.ws._tabs[i])
        self.assertIs(t["table"], self.ws.leads._table)
        self.assertIs(t["col_fit"][0], self.ws.leads._head)
        self.assertEqual(sorted(t), sorted(_COCKPIT_KEYS + _TAB_KEYS))

    def test_reveal_switches_the_tab_and_comes_back_for_the_leads(self):
        self.ws.help_reveal("tab_sessions")
        self.assertIs(self.ws._stack.currentWidget(), self.ws._sessions)
        self.ws.help_reveal("refine_search")
        self.assertIs(self.ws._stack.currentWidget(), self.ws.leads)
        self.assertFalse(self.ws.leads._rail.isHidden())

    def test_an_unknown_key_moves_nothing(self):
        self.ws.help_reveal("tab_analytics")
        self.ws.help_reveal("nonsense")
        self.assertIs(self.ws._stack.currentWidget(), self.ws._analytics)

    def test_the_snapshot_brings_back_the_tab_the_walk_started_on(self):
        # Not always Leads: an owner who pressed "?" on Sessions ends there.
        self.ws.help_reveal("tab_sessions")
        snap = self.ws.help_snapshot()
        self.ws.help_reveal("refine_search")
        self.ws.help_reveal("tab_saved")
        self.ws.help_restore(snap)
        self.assertIs(self.ws._stack.currentWidget(), self.ws._sessions)


class PointAtMeWorkbench(_Workbench):
    """The search half of the walkthrough: the widgets in the rail, unfolded
    and scrolled to, without a run being started or a setting moved."""

    def test_every_key_is_a_widget_of_the_search(self):
        wb = self._WB.LeadsWorkbench({})
        targets = wb.help_targets()
        # The notice line has nothing to say until a run does.
        self.assertEqual(sorted(targets), sorted(_SEARCH_KEYS))
        for key, widget in targets.items():
            self.assertTrue(_descends(widget, wb), key)
        self.assertIs(targets["run_target"], wb._target_row)
        self.assertIs(targets["run_qualify"], wb._qualify_row)
        self.assertIs(targets["run_verify"], wb._verify_row)
        self.assertIs(targets["mode_switch"], wb._mode_seg)
        self.assertIs(targets["source_switch"], wb._source_row)
        self.assertIs(targets["offer"], wb._offer)
        self.assertIs(targets["net_new"], wb._skip_seen)
        self.assertIs(targets["btn_find"], wb._prepare)
        self.assertIs(targets["btn_prepare"], wb._prepare_all)

    def test_the_notice_joins_once_it_says_something(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertNotIn("notice", wb.help_targets())
        wb._status.setText("Qualifying 3 of 25…")
        self.assertIs(wb.help_targets()["notice"], wb._notice)

    def test_importing_a_sheet_has_no_source_switch_to_point_at(self):
        wb = self._WB.LeadsWorkbench({})
        wb._set_mode("sheet")
        targets = wb.help_targets()
        for gone in ("source_switch", "run_target", "net_new"):
            self.assertNotIn(gone, targets)
        self.assertIn("mode_switch", targets)
        wb.help_reveal("source_switch")             # never switches the mode back
        self.assertEqual(wb._mode, "sheet")

    def test_reveal_unfolds_the_search_and_opens_the_keys(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "already-set"})
        self.assertTrue(wb._keys_box.isHidden())
        self.assertIs(wb.help_targets()["keys_box"], wb._keys_toggle)
        wb._fold_setup(False)                       # as a finished run leaves it
        self.assertEqual(wb.help_targets(), {})
        wb.help_reveal("keys_box")
        self.assertFalse(wb._setup_details.isHidden())
        self.assertIs(wb.help_targets()["keys_box"], wb._keys_box)

    def test_a_hidden_rail_comes_back_for_every_step_inside_it(self):
        """Hide filters folded the rail away, and only the refine steps brought
        it back — so every facet, run setting and run button was skipped and
        the walk opened on the run line. The filter panel's keys are unfolded
        here too, because the filter panel cannot reach the rail."""
        from addons.leads import tour as T
        wb = self._WB.LeadsWorkbench({})
        rail = wb._cockpit.leads._rail
        for key, target in (("facet_locations", lambda: wb._filters.help_targets()["facet_locations"]),
                            ("similar_titles", lambda: wb._filters._similar),
                            ("btn_find", lambda: wb._prepare)):
            wb._cockpit.leads.set_filters_shown(False)
            self.assertFalse(T._drawn(target()), key)
            wb.help_reveal(key)
            wb._filters.help_reveal(key)
            self.assertFalse(rail.isHidden(), key)
            self.assertTrue(T._drawn(target()), key)
        wb._cockpit.leads.set_filters_shown(False)
        wb.help_reveal("notice")                     # not in the rail: left folded
        self.assertTrue(rail.isHidden())

    def test_the_whole_walk_leaves_the_screen_as_it_found_it(self):
        """Hide filters on, the Sessions tab up, two facets open, the setup
        folded over a run: walked to the end, or left with Esc halfway, the
        tour gives every one of those back, and the facets were still walked."""
        from addons.leads import tour as T
        wb = self._WB.LeadsWorkbench({})
        self._finished(wb)
        ws, ck, fp = wb._cockpit, wb._cockpit.leads, wb._filters

        def state():
            return (ws._stack.currentIndex(), ck._rail.isHidden(),
                    ck._table.currentRow(), ck._drawer_w.isHidden(),
                    sorted(n for n, s in fp._sections.items() if s.is_open()),
                    wb._setup_details.isHidden(), wb._keys_box.isHidden(),
                    fp.spec().to_dict(), wb._mode, sorted(ck._checked))

        ck.set_filters_shown(False)
        ws._select(1)
        before = state()
        walk = T.Tour(T.Guide(wb), wb)
        walk.start()
        seen = []
        while walk.is_open() and len(seen) < 80:
            seen.append(walk.key())
            walk.next_step()
        self.assertIn("facet_locations", seen)
        self.assertEqual(seen[0], "mode_switch")
        self.assertEqual(state(), before)

        walk.start()
        for _ in range(80):
            if walk.key() == "tab_saved" or not walk.is_open():
                break
            walk.next_step()
        self.assertEqual((walk.key(), walk.is_open()), ("tab_saved", True))
        walk.leave()
        self.assertEqual(state(), before)

    def test_the_snapshot_folds_the_setup_and_the_keys_back(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "already-set"})
        wb._fold_setup(False)
        snap = wb.help_snapshot()
        wb.help_reveal("keys_box")
        self.assertFalse(wb._keys_box.isHidden())
        wb.help_restore(snap)
        self.assertTrue(wb._setup_details.isHidden())
        self.assertTrue(wb._keys_box.isHidden())

    def test_no_reveal_starts_a_run_or_moves_a_setting(self):
        wb = self._WB.LeadsWorkbench({})

        def state():
            return (wb._filters.spec().to_dict(), wb._mode, wb._source,
                    wb._target.value(), wb._limit.value(), wb._verify_limit.value(),
                    wb._offer.toPlainText(), wb._skip_seen.isChecked(), dict(wb.cfg))

        before = state()
        for key in _SEARCH_KEYS + ("notice", "nonsense"):
            wb.help_reveal(key)
        self.assertEqual(state(), before)
        self.assertIsNone(wb._worker)
        self.assertEqual(wb._jobs, 0)


if __name__ == "__main__":
    unittest.main()
