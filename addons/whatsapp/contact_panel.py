"""The contact side panel — who this is, whether you can reply, how they are
tagged, and whether they have opted out.

One widget, used twice: the right-hand rail of the Inbox (beside a live
conversation) and the detail pane of the Contacts tab. It holds no worker and
makes no network call. It draws a contact, applies an edit to what it shows
immediately, and emits what changed; the page above decides how to save it and
calls set_contact() again with the truth if the save fails.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCompleter, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QScrollArea, QVBoxLayout,
                               QWidget)

import i18n
import theme
from addons.whatsapp.chat import avatar_colour, human_delta
from widgets import controls as C


class _TagChip(QFrame):
    removed = Signal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self.setObjectName("waTag")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#waTag {{ background: rgba(0,0,0,0.07); border-radius: 12px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 3, 4, 3)
        row.setSpacing(2)
        row.addWidget(C.label(tag, level="SUPPORT", weight=600, colour=theme.NEUTRAL[800]))
        x = C.icon_button("x", i18n.t("Remove tag"), colour=theme.NEUTRAL[600])
        x.setFixedSize(20, 20)
        x.clicked.connect(lambda: self.removed.emit(tag))
        row.addWidget(x)


class ContactPanel(QFrame):
    tagsChanged = Signal(object, list)          # contact id, new tag list
    optOutChanged = Signal(object, bool)        # contact id, opted out?

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("waContactPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._row: dict | None = None
        self._known_tags: list = []
        self._window = None                     # timedelta | None | "n/a"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self._scroll)
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        self._col.setSpacing(theme.SPACE_4)
        self._render()

    # -- public -------------------------------------------------------------------
    def set_known_tags(self, tags: list):
        self._known_tags = list(tags or [])

    def set_contact(self, row: dict | None, window="n/a"):
        """`window`: a timedelta (time left to reply freely; negative = closed),
        None (they have never written), or "n/a" to leave that section out."""
        self._row = dict(row) if row else None
        self._window = window
        self._render()

    def contact_id(self):
        return (self._row or {}).get("id")

    # -- drawing ------------------------------------------------------------------
    def _clear(self):
        self._clear_layout(self._col)

    @classmethod
    def _clear_layout(cls, layout):
        """Empty a layout, including any layouts nested inside it — a nested
        one holds widgets of its own that a flat sweep would leave behind,
        stacked invisibly under the next render."""
        while layout.count():
            item = layout.takeAt(0)
            widget, inner = item.widget(), item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif inner is not None:
                cls._clear_layout(inner)

    def _render(self):
        self._clear()
        row = self._row
        if not row:
            self._col.addStretch(1)
            empty = C.label(i18n.t("Select someone to see their details."),
                            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            self._col.addWidget(empty)
            self._col.addStretch(1)
            return

        who = row.get("name") or row.get("phone") or i18n.t("Unknown")
        opted_out = bool(row.get("opt_out"))

        head = QVBoxLayout()
        head.setSpacing(theme.SPACE_2)
        head.addWidget(C.Avatar(who, 68, avatar_colour(who, opted_out)),
                       alignment=Qt.AlignHCenter)
        name = C.label(who, level="SECTION", weight=700)
        name.setAlignment(Qt.AlignHCenter)
        name.setWordWrap(True)
        head.addWidget(name)
        phone = row.get("phone") or ""
        if phone:
            line = QHBoxLayout()
            line.setSpacing(theme.SPACE_1)
            line.addStretch(1)
            line.addWidget(C.label("+" + phone.lstrip("+"), level="SUPPORT",
                                   colour=theme.NEUTRAL[600]))
            copy = C.icon_button("copy", i18n.t("Copy number"),
                                 colour=theme.NEUTRAL[600])
            copy.setFixedSize(24, 24)
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(phone))
            line.addWidget(copy)
            line.addStretch(1)
            head.addLayout(line)
        head.addWidget(C.Pill(i18n.t("Opted out") if opted_out else i18n.t("Opted in"),
                              "warn" if opted_out else "ok"), alignment=Qt.AlignHCenter)
        self._col.addLayout(head)

        details = [(i18n.t("Email"), row.get("email")), (i18n.t("Company"), row.get("company"))]
        details = [(k, v) for k, v in details if v]
        if details:
            self._col.addWidget(C.hairline())
            for k, v in details:
                box = QVBoxLayout()
                box.setSpacing(0)
                box.addWidget(C.label(k.upper(), level="LABEL", colour=theme.NEUTRAL[500]))
                box.addWidget(C.label(v, level="BODY", wrap=True))
                self._col.addLayout(box)

        if self._window != "n/a":
            self._col.addWidget(C.hairline())
            self._col.addWidget(self._window_block())

        self._col.addWidget(C.hairline())
        self._col.addWidget(C.label(i18n.t("TAGS"), level="LABEL", colour=theme.NEUTRAL[500]))
        self._col.addWidget(self._tags_block(row))

        self._col.addWidget(C.hairline())
        self._col.addLayout(self._optout_block(opted_out))
        self._col.addStretch(1)

    def _window_block(self) -> QWidget:
        box = QFrame()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        col.addWidget(C.label(i18n.t("REPLY WINDOW"), level="LABEL", colour=theme.NEUTRAL[500]))
        w = self._window
        if w is None:
            pill, text = C.Pill(i18n.t("No messages from them"), "quiet"), i18n.t(
                "They haven't written to you, so only an approved template can start a chat.")
        elif w.total_seconds() > 0:
            pill, text = C.Pill(i18n.t("Open · {t} left").format(t=human_delta(w)), "ok"), i18n.t(
                "You can reply freely until it closes.")
        else:
            pill, text = C.Pill(i18n.t("Closed"), "warn"), i18n.t(
                "It's been over 24 hours since they wrote. Only an approved template will be delivered.")
        col.addWidget(pill, alignment=Qt.AlignLeft)
        col.addWidget(C.label(text, level="META", colour=theme.NEUTRAL[600], wrap=True))
        return box

    def _tags_block(self, row: dict) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        tags = [t for t in (row.get("tags") or []) if isinstance(t, str) and t]
        if tags:
            holder = QWidget()
            flow = C.FlowLayout(holder, h_space=6, v_space=6)
            for t in tags:
                chip = _TagChip(t)
                chip.removed.connect(self._remove_tag)
                flow.addWidget(chip)
            col.addWidget(holder)
        add = QLineEdit()
        add.setPlaceholderText(i18n.t("Add a tag and press Enter"))
        add.setMinimumHeight(34)
        completer = QCompleter([t for t in self._known_tags if t not in tags], add)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        add.setCompleter(completer)
        add.returnPressed.connect(lambda: self._add_tag(add))
        col.addWidget(add)
        return box

    def _optout_block(self, opted_out: bool) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(theme.SPACE_1)
        row = QHBoxLayout()
        row.addWidget(C.label(i18n.t("Opted out of messages"), level="BODY", weight=600),
                      stretch=1)
        sw = C.ToggleSwitch()
        sw.setChecked(opted_out)
        sw.toggled.connect(self._toggle_opt_out)
        row.addWidget(sw)
        col.addLayout(row)
        col.addWidget(C.label(
            i18n.t("Opted-out contacts are skipped by every broadcast and can't be "
                   "replied to from here."), level="META", colour=theme.NEUTRAL[600], wrap=True))
        return col

    # -- edits ----------------------------------------------------------------------
    def _current_tags(self) -> list:
        return [t for t in ((self._row or {}).get("tags") or []) if isinstance(t, str) and t]

    def _add_tag(self, edit: QLineEdit):
        tag = edit.text().strip()
        if not tag or not self._row:
            return
        tags = self._current_tags()
        if tag.lower() in (t.lower() for t in tags):
            edit.clear()
            return
        tags = sorted(tags + [tag])
        self._row["tags"] = tags
        cid = self.contact_id()
        self._render()
        self.tagsChanged.emit(cid, tags)

    def _remove_tag(self, tag: str):
        if not self._row:
            return
        tags = [t for t in self._current_tags() if t != tag]
        self._row["tags"] = tags
        cid = self.contact_id()
        self._render()
        self.tagsChanged.emit(cid, tags)

    def _toggle_opt_out(self, checked: bool):
        if not self._row:
            return
        if not checked:
            answer = QMessageBox.question(
                self, i18n.t("Start messaging again?"),
                i18n.t("Only do this if they have asked to hear from you again. "
                       "Messaging someone who opted out can get your number restricted."),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self._render()                      # put the switch back
                return
        self._row["opt_out"] = checked
        cid = self.contact_id()
        self._render()
        self.optOutChanged.emit(cid, checked)
