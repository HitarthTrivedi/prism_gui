"""The WhatsApp workspace — the whole surface, full-window, in the panel.

Same shape as Leads & Outreach: an underlined tab strip over a stacked page,
each page built the first time it is opened so an unopened tab costs nothing.

    Inbox · Contacts · Broadcasts · Settings

The strip's right edge carries the one thing worth glancing at without a click:
whether this is live, demo data, or unreachable.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import demo
from widgets import controls as C

_INBOX, _CONTACTS, _BROADCASTS, _SETTINGS = range(4)


def _tab_names() -> tuple:
    # Literal i18n.t calls, not a loop over a tuple of names: the string
    # extractor only sees literals, and a tab it cannot see is one that stays
    # in English for every translated install.
    return (i18n.t("Inbox"), i18n.t("Contacts"), i18n.t("Broadcasts"), i18n.t("Settings"))


class WhatsAppWorkbench(QWidget):
    unreadChanged = Signal(int)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._pages: dict = {}
        self._unread = 0
        self._current = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._tabstrip())
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("QStackedWidget { background: transparent; }")
        for _ in range(4):
            self._stack.addWidget(QWidget())        # placeholders, replaced on first open
        root.addWidget(self._stack, 1)
        self._select(_INBOX)

    # ── tab strip ────────────────────────────────────────────────────────────
    def _tabstrip(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("waTabs")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#waTabs {{ background: {theme.CARD}; border: none;"
            f" border-bottom: 1px solid {theme.HAIRLINE}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, 0)
        lay.setSpacing(theme.SPACE_5)
        self._tab_buttons: list[QPushButton] = []
        for i, name in enumerate(_tab_names()):
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, k=i: self._select(k))
            self._tab_buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.conn = C.Pill("", "quiet")
        lay.addWidget(self.conn)
        self._set_connection("checking")
        return bar

    def _style_tab(self, b: QPushButton, active: bool):
        # border-radius 0 on purpose: the app-wide QPushButton radius would curl
        # the ends of the 2px underline up into a bracket (same fix Leads uses).
        if active:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid {theme.ACCENT};color:{theme.TEXT};"
                f"padding:12px 4px;margin-bottom:-1px;font-size:13px;font-weight:600;}}")
        else:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid transparent;color:{theme.NEUTRAL[600]};"
                f"padding:12px 4px;font-size:13px;font-weight:500;}}"
                f"QPushButton:hover{{color:{theme.TEXT};}}")

    def _set_connection(self, state: str):
        if demo.enabled():
            state = "demo"
        text, tone = {"checking": (i18n.t("Connecting…"), "quiet"),
                      "live": (i18n.t("Live"), "ok"),
                      "demo": (i18n.t("Demo data"), "warn"),
                      "offline": (i18n.t("Can't reach WhatsApp data"), "err")}[state]
        self.conn.setText(text)
        self.conn.set_tone(tone)

    # ── pages, built lazily ──────────────────────────────────────────────────
    def _page(self, index: int) -> QWidget:
        if index in self._pages:
            return self._pages[index]
        if index == _INBOX:
            from addons.whatsapp.inbox import InboxPage
            page = InboxPage(self.cfg)
            page.unreadChanged.connect(self._on_unread)
            page.statusChanged.connect(
                lambda msg, err: self._set_connection("offline" if err else "live"))
        elif index == _CONTACTS:
            from addons.whatsapp.contacts import ContactsPage
            page = ContactsPage(self.cfg)
        elif index == _BROADCASTS:
            from addons.whatsapp.broadcast import BroadcastPage
            page = BroadcastPage(self.cfg)
        else:
            from addons.whatsapp.settings import SettingsPage
            page = SettingsPage(self.cfg)
        old = self._stack.widget(index)
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(index, page)
        self._pages[index] = page
        return page

    def _select(self, index: int):
        prev = self._pages.get(self._current)
        if prev is not None and self._current == _INBOX:
            prev.deactivate()
        self._current = index
        page = self._page(index)
        self._stack.setCurrentIndex(index)
        for k, b in enumerate(self._tab_buttons):
            self._style_tab(b, k == index)
        page.activate()

    def show_tab(self, index: int):
        self._select(index)

    # ── unread badge ─────────────────────────────────────────────────────────
    def _on_unread(self, n: int):
        self._unread = n
        base = _tab_names()[_INBOX]
        self._tab_buttons[_INBOX].setText(f"{base}  ({n})" if n else base)
        self.unreadChanged.emit(n)

    # ── lifecycle, driven by the panel ───────────────────────────────────────
    def activate(self):
        page = self._pages.get(self._current)
        if page is not None:
            page.activate()

    def deactivate(self):
        page = self._pages.get(_INBOX)
        if page is not None:
            page.deactivate()

    def refresh(self, cfg: dict):
        """The panel re-read settings; hand them on."""
        self.cfg = cfg
        for page in self._pages.values():
            page.cfg = cfg
