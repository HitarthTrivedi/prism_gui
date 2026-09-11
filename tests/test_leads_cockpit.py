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
        self.assertEqual(p.header.actions_row.count(), 3)  # AI tools, Export, Send all
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
        self.assertTrue(wb._setup_line().startswith("Find people · 6 titles"))

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
        params = wb._next_params
        self.assertEqual(params["mode"], "icp")
        self.assertEqual(params["filters"], spec.to_dict())
        self.assertEqual(params["location"], "Anywhere except India")
        self.assertEqual(wb._jobs, 1)

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
        self.assertIn("Prepare outreach", wb._status.text())

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


if __name__ == "__main__":
    unittest.main()
