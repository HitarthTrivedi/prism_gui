"""Email, the screen: two ways to start, and what has already gone.

The old screen was a brochure — "How it works" in four cards, "Which of
your tools it uses" — with one button that opened a window whose To field
was folded away under "Edit the recipient list (optional)". An owner who
wanted to write to one supplier could not find where the address went.

This screen does what the Email-automation launcher does: it answers the
question the owner came with, in plain words, and hands off. Two buttons —
write to one person, send to a list — because those are the two things
anyone does with this add-on. Under them, the emails already sent from this
computer, read back from `~/Prism Email/sent.json`, so "did that go?" is
answered by looking. Under that, the sending account, and the one way to
change it. Nothing on this screen is a second copy of the work.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

import i18n
import sent_log
import theme
from widgets import controls as C
from widgets.controls import Card

# The one primary on the populated screen and in the header.
NEW_LABEL = "New email"
ONE_LABEL = "Write to one person"
LIST_LABEL = "Send to a list"
SHOW_SENT = 50


class EmailPanel(QWidget):
    opened = Signal()               # header primary — the same as "one"
    open_compose = Signal(str)      # "one" | "list"
    change_account = Signal()
    navigate = Signal(str)          # kept: MainWindow wires every add-on alike
    open_run = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._actions = [
            C.button(i18n.t("Change account"), "secondary", icon_name="key",
                     on_click=self.change_account.emit),
            C.button(i18n.t(NEW_LABEL), "primary", icon_name="pencil",
                     on_click=self.opened.emit),
        ]
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = C.PageHeader(i18n.t("Email"), "", list(self._actions))
        root.addWidget(self.header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self._col = QVBoxLayout(host)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        self._scroll.setWidget(host)
        root.addWidget(self._scroll, stretch=1)
        self.refresh()

    def header_actions(self) -> list:
        return list(self._actions)

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self):
        self._drop(self._col)
        address = self._address()
        if not address:
            self.header.set_subtitle(i18n.t(
                "Send emails from your own account. Set the account up once."))
            self._col.addWidget(self._not_set_up(), stretch=1)
            return
        self.header.set_subtitle(i18n.t(
            "Send from {address} — to one person or to a whole list. You read "
            "every word before it goes.").format(address=address))
        self._col.addWidget(self._start_card())
        self._col.addWidget(self._sent_card())
        self._col.addWidget(self._account_card(address))
        self._col.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()          # a send in the window must show here at once

    def _address(self) -> str:
        return ((self.cfg.get("email") or {}).get("address") or "").strip()

    def _not_set_up(self) -> QWidget:
        door = C.EmptyState(
            "mail", i18n.t("No sending account yet"),
            i18n.t("Prism sends from your own email account. Set it up once "
                   "— address and app password — and every email after that "
                   "goes out in your name."),
            i18n.t("Set up the sending account"))
        door.clicked.connect(self.change_account.emit)
        return door

    def _start_card(self) -> QWidget:
        card = Card()
        col = card.body()
        col.setSpacing(theme.ROW_GAP)
        col.addWidget(C.label(i18n.t("Send an email"), level="CARD_TITLE"))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE_5)
        grid.setVerticalSpacing(theme.SPACE_2)
        self.one_btn = C.button(i18n.t(ONE_LABEL), "secondary", icon_name="user",
                                on_click=lambda: self.open_compose.emit("one"))
        self.list_btn = C.button(i18n.t(LIST_LABEL), "secondary", icon_name="list",
                                 on_click=lambda: self.open_compose.emit("list"))
        for column, (button, text) in enumerate((
            (self.one_btn, i18n.t(
                "Type the address, the subject and the message, then press "
                "Send. Prism can write the message for you if you ask it to.")),
            (self.list_btn, i18n.t(
                "Attach a CSV of addresses (name, email). Each person gets "
                "their own copy, with their own name in it.")),
        )):
            grid.addWidget(button, 0, column, alignment=Qt.AlignLeft)
            note = C.label(text, level="SUPPORT", wrap=True)
            note.setMinimumWidth(120)
            grid.addWidget(note, 1, column)
            grid.setColumnStretch(column, 1)
        col.addLayout(grid)
        return card

    def _sent_card(self) -> QWidget:
        card = Card()
        col = card.body()
        col.setSpacing(theme.ROW_GAP)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(C.label(i18n.t("Sent from this computer"),
                               level="CARD_TITLE"))
        head.addStretch(1)
        folder_btn = C.button(i18n.t("Open the folder"), "tertiary",
                              icon_name="folder", small=True,
                              on_click=self._open_folder)
        head.addWidget(folder_btn)
        col.addLayout(head)

        entries = sent_log.load(self.cfg)
        if not entries:
            col.addWidget(C.label(i18n.t(
                "Nothing sent yet. Every email you send is listed here — "
                "when, to whom, and whether it went."), level="SUPPORT",
                wrap=True))
            self.sent_table = None
            return card

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels([i18n.t(h) for h in
                                         ("Date", "To", "Subject", "Result")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        head = table.horizontalHeader()
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        for column in (0, 1, 3):
            head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for entry in entries[:SHOW_SENT]:
            row = table.rowCount()
            table.insertRow(row)
            date = f"{entry.get('date', '')} {entry.get('time', '')}".strip()
            cells = (date, sent_log.describe_to(entry),
                     entry.get("subject", ""), sent_log.describe_result(entry))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3 and entry.get("failed"):
                    item.setForeground(Qt.GlobalColor.darkRed)
                table.setItem(row, column, item)
            table.item(row, 1).setToolTip(
                "\n".join(r.get("email", "") for r in entry.get("to") or []))
        # Exactly as tall as its rows (up to twelve; more scroll) — a table
        # sized by Qt's own hint leaves a blank field under two rows.
        rows = min(table.rowCount(), 12)
        row_h = table.verticalHeader().defaultSectionSize()
        table.setFixedHeight(head.sizeHint().height() + rows * row_h + 4)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        col.addWidget(table)
        if len(entries) > SHOW_SENT:
            col.addWidget(C.label(i18n.t(
                "Showing the last {n}. The full record is in the folder."
            ).format(n=SHOW_SENT), level="SUPPORT"))
        self.sent_table = table
        return card

    def _account_card(self, address: str) -> QWidget:
        card = Card()
        col = card.body()
        col.setSpacing(theme.SPACE_2)
        col.addWidget(C.label(i18n.t("Sending account"), level="CARD_TITLE"))
        account = self.cfg.get("email") or {}
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(theme.SPACE_4)
        line.addWidget(C.label(address, level="BODY", weight=500))
        host = account.get("host") or ""
        if host:
            line.addWidget(C.label(i18n.t("through {host}").format(host=host),
                                   level="SUPPORT"))
        line.addStretch(1)
        line.addWidget(C.button(i18n.t("Change account"), "secondary",
                                icon_name="key", small=True,
                                on_click=self.change_account.emit))
        col.addLayout(line)
        col.addWidget(C.label(i18n.t(
            "Every email goes out from this address, through your own mail "
            "provider. Prism has no mail server of its own, and your password "
            "stays on this computer."), level="SUPPORT", wrap=True))
        return card

    # ── plumbing ──────────────────────────────────────────────────────────
    def _open_folder(self):
        target = sent_log.folder(self.cfg)
        try:
            os.makedirs(target, exist_ok=True)
        except OSError:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._drop(child)
