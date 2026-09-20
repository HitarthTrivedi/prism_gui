"""The WhatsApp screen.

The whole workspace, in the window — not a launcher for a modal. The rail shows
this panel; the panel IS the surface: a page header over the tabbed workbench
(addons/whatsapp/workbench.py). The heavy widget is built the first time the
screen is shown, so it costs nothing at startup (MainWindow builds every screen
up front).

`opened` and `open_run` stay as signals because MainWindow wires them for every
add-on panel; this one only ever emits `navigate` (the "AI tools" shortcut).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

import i18n
from widgets import controls as C


class WhatsAppPanel(QWidget):
    TITLE = "WhatsApp"
    # One line, on purpose: PageHeader's subtitle does not wrap, so a long one
    # sets the window's minimum width and pushes a 1366px laptop sideways.
    BLURB = "Every conversation, contact and broadcast on your WhatsApp number."

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
        self.broadcast_btn = C.button(i18n.t("New broadcast"), "primary",
                                      icon_name="plus", on_click=self.new_broadcast)
        self.header = C.PageHeader(
            i18n.t(self.TITLE), i18n.t(self.BLURB), [
                C.button(i18n.t("AI tools"), "tertiary", icon_name="grid",
                         on_click=lambda: self.navigate.emit("agents")),
                self.broadcast_btn])
        root.addWidget(self.header)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(0)
        root.addWidget(self._body, stretch=1)

    # -- lifecycle --------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        # Re-read settings on every show. MainWindow swaps its cfg dict without
        # telling this panel, which it built once at startup; a stale copy,
        # saved back, would wipe whatever the other screens wrote meanwhile.
        try:
            import core_bridge as CB
            self.cfg = CB.config.load()
        except Exception:                                   # noqa: BLE001
            pass
        if self._workbench is None:
            self._build()                       # its first page activates itself
        else:
            self._workbench.refresh(self.cfg)
            self._workbench.activate()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._workbench is not None:
            self._workbench.deactivate()

    def _build(self):
        # Imported lazily so the workspace never loads on a startup where the
        # screen is not opened.
        from addons.whatsapp.workbench import WhatsAppWorkbench
        self._workbench = WhatsAppWorkbench(self.cfg, self)
        self._body_lay.addWidget(self._workbench)

    def new_broadcast(self):
        if self._workbench is None:
            self._build()
        from addons.whatsapp.workbench import _BROADCASTS
        self._workbench.show_tab(_BROADCASTS)

    def refresh(self):
        if self._workbench is not None:
            self._workbench.activate()
