"""The Leads & Outreach screen.

The whole workbench, in the window — not a launcher for a modal. The rail shows
this panel; the panel IS the surface: a page header (title + the run's batch
actions) over the tabbed cockpit (addons/leads/workbench.py), whose left rail
carries the search and whose results fill the rest. The heavy widget is built
the first time the screen is shown, so it costs nothing at startup (MainWindow
builds every screen up front).

`opened`, `navigate` and `open_run` stay as signals because MainWindow wires
them for every add-on panel; this one only ever emits `navigate` (the "AI tools"
shortcut). It never opens a modal.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

import i18n
from widgets import controls as C


class LeadsPanel(QWidget):
    TITLE = "Leads & Outreach"
    # One line, on purpose: PageHeader's subtitle does not wrap, so a long one
    # sets the window's minimum width and pushes a 1366px laptop sideways.
    BLURB = "Find, qualify and reach the right people — Prism drafts, you send."

    opened = Signal()               # kept for MainWindow's generic wiring
    navigate = Signal(str)          # "AI tools" → the agents screen
    open_run = Signal(str)          # kept for MainWindow's generic wiring

    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._workbench = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = C.PageHeader(
            i18n.t(self.TITLE), i18n.t(self.BLURB), [
                C.button(i18n.t("AI tools"), "tertiary", icon_name="grid",
                         on_click=lambda: self.navigate.emit("agents"))])
        root.addWidget(self.header)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(0)
        root.addWidget(self._body, stretch=1)

    # -- lifecycle --------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        # Re-read settings on every show. MainWindow swaps its cfg dict (first-run
        # wizard, Email → Change account, inquiry setup) without telling this
        # panel, which it built once at startup; a stale copy would miss the Groq
        # key and the sending account — and, saved back, would wipe them.
        try:
            import core_bridge as CB
            self.cfg = CB.config.load()
        except Exception:                                   # noqa: BLE001
            pass
        if self._workbench is None:
            self._build()
            # Land on the last run instead of an empty screen (loaded off the UI
            # thread; dropped if the user starts something first).
            self._workbench.restore_latest()
        else:
            self._workbench.cfg = self.cfg
            self._workbench.refresh_lists()

    def _build(self):
        # Imported lazily so the (prospector-adjacent) workbench never loads on a
        # startup where the screen is not opened.
        from addons.leads.workbench import LeadsWorkbench
        self._workbench = LeadsWorkbench(self.cfg, self)
        self._body_lay.addWidget(self._workbench)
        # Export sheets + Send all act on the whole run: page-level actions,
        # so they sit in the header, primary last.
        for button in self._workbench.action_buttons():
            self.header.add_action(button)

    def refresh(self):
        """A run or a saved list elsewhere should show here — re-scan on show."""
        if self._workbench is not None:
            self._workbench.refresh_lists()
