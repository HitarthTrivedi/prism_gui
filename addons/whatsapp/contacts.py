"""The Contacts tab — everyone your number has talked to, searchable, taggable.

The same contact panel as the Inbox's right-hand rail, given the whole right
side. Tags set here are what a broadcast aims at, so this is where an audience
is built; the list says who is opted out so nobody is surprised by a skipped
send.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QListWidget, QListWidgetItem,
                               QSplitter, QStackedWidget, QVBoxLayout, QHBoxLayout,
                               QWidget)

import i18n
import theme
from addons.whatsapp.chat import CONTACT_ROW_H, ContactDelegate
from addons.whatsapp.contact_panel import ContactPanel
from addons.whatsapp.workers import (ContactOptOutWorker, ContactsLoadWorker,
                                     ContactTagsSaveWorker, TagsLoadWorker)
from widgets import controls as C


def _card(objname: str) -> QFrame:
    f = QFrame()
    f.setObjectName(objname)
    f.setAttribute(Qt.WA_StyledBackground, True)
    f.setStyleSheet(
        f"#{objname} {{ background: {theme.CARD}; border: 1px solid {theme.HAIRLINE};"
        f" border-radius: {theme.R_CARD}px; }}")
    return f


class ContactsPage(QWidget):
    countChanged = Signal(int)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._rows: list = []
        self._filter = "all"
        self._selected_id = None
        self._loaded = False
        self._sticky = ""                      # an error that must outlive the reload

        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.SPACE_3)
        split.setStyleSheet("QSplitter::handle { background: transparent; }")
        root.addWidget(split)

        left = _card("waContacts")
        left.setMinimumWidth(340)
        left.setMaximumWidth(560)
        col = QVBoxLayout(left)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_4, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_3)
        self.search = C.SearchField(i18n.t("Search name, number, company or email"))
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self.refresh)
        self.search.changed.connect(self._on_search)
        col.addWidget(self.search)
        self.chips = C.FilterChips([("all", i18n.t("All")), ("in", i18n.t("Opted in")),
                                    ("out", i18n.t("Opted out"))], current="all")
        self.chips.changed.connect(self._on_chip)
        col.addWidget(self.chips)

        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(ContactDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }")
        self.list.currentItemChanged.connect(self._on_selected)
        self.stack.addWidget(self.list)
        self.empty = C.EmptyState("user", i18n.t("No contacts yet"),
                                  i18n.t("People are added automatically the first time "
                                         "they message your number."))
        self.stack.addWidget(self.empty)
        col.addWidget(self.stack, stretch=1)
        self.status = C.label("", level="META", colour=theme.NEUTRAL[500])
        col.addWidget(self.status)
        split.addWidget(left)

        right = _card("waContactDetail")
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.panel = ContactPanel()
        self.panel.setMaximumWidth(500)         # a detail card, not a page-wide form
        self.panel.tagsChanged.connect(self._save_tags)
        self.panel.optOutChanged.connect(self._save_opt_out)
        rl.addStretch(1)
        rl.addWidget(self.panel, stretch=4)
        rl.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 600])

    def _on_search(self, _text: str):
        self._sticky = ""
        self._debounce.start()

    # -- loading ----------------------------------------------------------------
    def activate(self):
        self.refresh()
        if not self._loaded:
            tw = TagsLoadWorker()
            tw.done.connect(self.panel.set_known_tags)
            tw.failed.connect(lambda _e: None)
            self._tags_worker = tw
            tw.start()

    def refresh(self):
        if not self._sticky:
            self.status.setText(i18n.t("Loading…"))
            self.status.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        w = ContactsLoadWorker(search=self.search.text().strip())
        w.done.connect(self._on_loaded)
        w.failed.connect(self._on_failed)
        self._worker = w
        w.start()

    def _on_failed(self, error: str):
        self.status.setText(i18n.t("Couldn't load contacts — {e}").format(e=error))
        self.status.setStyleSheet(f"color: {theme.ERR_INK};")
        if not self._rows:
            self.empty.set_text(i18n.t("Couldn't load contacts"), error)
            self.stack.setCurrentIndex(1)

    def _on_loaded(self, rows: list):
        self._loaded = True
        self._rows = rows or []
        self.countChanged.emit(len(self._rows))
        self._show()

    def _show(self):
        rows = [r for r in self._rows
                if self._filter == "all"
                or (self._filter == "out") == bool(r.get("opt_out"))]
        self.list.blockSignals(True)
        self.list.clear()
        keep = -1
        for i, r in enumerate(rows):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, r)
            item.setSizeHint(QSize(0, CONTACT_ROW_H))
            self.list.addItem(item)
            if r.get("id") == self._selected_id:
                keep = i
        if keep >= 0:
            self.list.setCurrentRow(keep)
        self.list.blockSignals(False)
        total = len(self._rows)
        if self._sticky:
            self.status.setText(self._sticky)
            self.status.setStyleSheet(f"color: {theme.ERR_INK};")
        else:
            self.status.setText(i18n.t("{n} contacts").format(n=len(rows)) if rows or total
                                else "")
            self.status.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        if rows:
            self.stack.setCurrentIndex(0)
            if keep < 0:
                self.panel.set_contact(None)
        else:
            if self._rows or self.search.text().strip():
                self.empty.set_text(i18n.t("No one matches"),
                                    i18n.t("Try a different search or filter."))
            else:
                self.empty.set_text(i18n.t("No contacts yet"),
                                    i18n.t("People are added automatically the first time "
                                           "they message your number."))
            self.stack.setCurrentIndex(1)
            self.panel.set_contact(None)

    def _on_chip(self, value: str):
        self._sticky = ""
        self._filter = value
        self._show()

    def _on_selected(self, item, _prev=None):
        if item is None:
            return
        row = item.data(Qt.UserRole) or {}
        self._sticky = ""
        self._selected_id = row.get("id")
        self.panel.set_contact(row)

    # -- edits --------------------------------------------------------------------
    def _save_tags(self, cid, tags: list):
        w = ContactTagsSaveWorker(cid, tags)
        w.done.connect(lambda row, c=cid: self._saved(c, row))
        w.failed.connect(self._save_failed)
        self._save_worker = w
        w.start()

    def _save_opt_out(self, cid, opted_out: bool):
        w = ContactOptOutWorker(cid, opted_out)
        w.done.connect(lambda row, c=cid: self._saved(c, row))
        w.failed.connect(self._save_failed)
        self._save_worker = w
        w.start()

    def _saved(self, cid, row: dict):
        for r in self._rows:
            if r.get("id") == cid and row:
                r.update({k: v for k, v in row.items() if k in ("tags", "opt_out")})
        self._show()

    def _save_failed(self, error: str):
        # Kept in _sticky, not just set on the label: the reload that follows
        # rewrites the status line, and an error that vanishes a moment after
        # it appears is one nobody read.
        self._sticky = i18n.t("Couldn't save that change — {e}").format(e=error)
        self.status.setText(self._sticky)
        self.status.setStyleSheet(f"color: {theme.ERR_INK};")
        self.refresh()                          # show what is really saved
