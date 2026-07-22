"""Context rail, top half: the files Prism thinks you meant.

Speak "the brochure in my Documents folder" and this is where the guess lands
— one card per mention, with the resolved path and a Keep / Change pair, which
is the CLI's confirm-before-attach prompt turned into two buttons. Anything
kept drops into the attached list underneath."""
from __future__ import annotations
import os
from PySide6.QtCore import Signal, Qt, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QGraphicsOpacityEffect,
)

import theme
from widgets import icons
from widgets.controls import kicker


def _fade_in(widget: QWidget):
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(200)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutQuart)
    anim.start(QPropertyAnimation.DeleteWhenStopped)
    widget._fade_anim = anim  # keep a reference alive


class MentionRow(QFrame):
    accepted = Signal(int)
    changed = Signal(int)

    def __init__(self, index: int, description: str, resolved: str, kind: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("row")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 11, 12, 11)
        root.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(9)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(
            "folder" if kind == "folder" else ("file" if kind == "file" else "help"),
            18, theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        head.addWidget(glyph)

        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(os.path.basename(resolved.rstrip("/")) if resolved else "Not found")
        name.setStyleSheet("font-size: 13px; font-weight: 500;")
        name.setWordWrap(True)
        text.addWidget(name)
        where = QLabel(
            f"in {os.path.basename(os.path.dirname(resolved.rstrip('/')))}"
            if resolved else f'for "{description}"')
        where.setObjectName("meta")
        where.setWordWrap(True)
        text.addWidget(where)
        head.addLayout(text, stretch=1)
        root.addLayout(head)

        self.setToolTip(f'"{description}"  →  {resolved or "(not found)"}')

        actions = QHBoxLayout()
        actions.setSpacing(7)
        keep = QPushButton(" Keep")
        keep.setObjectName("primaryBtn")
        keep.setCursor(Qt.PointingHandCursor)
        keep.setStyleSheet("font-size: 13px; padding: 5px 10px;")
        icons.button_icon(keep, "check", 14, theme.BG)
        keep.setEnabled(bool(resolved))
        keep.clicked.connect(lambda: self.accepted.emit(self.index))
        actions.addWidget(keep, stretch=1)

        change = QPushButton("Change")
        change.setObjectName("smallBtn")
        change.setCursor(Qt.PointingHandCursor)
        change.clicked.connect(lambda: self.changed.emit(self.index))
        actions.addWidget(change, stretch=1)
        root.addLayout(actions)

        _fade_in(self)


class FilesPanel(QWidget):
    mention_accepted = Signal(int)
    mention_change_requested = Signal(int)
    detach_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)
        root.addWidget(kicker("Files you mentioned"))

        self.empty = QLabel(
            "Nothing attached yet. Mention a file out loud, or use Add file.")
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        mentions_wrap = QWidget()
        self.mentions_box = QVBoxLayout(mentions_wrap)
        self.mentions_box.setContentsMargins(0, 0, 0, 0)
        self.mentions_box.setSpacing(8)
        root.addWidget(mentions_wrap)

        self.attached_label = kicker("Attached", muted=True)
        root.addWidget(self.attached_label)
        self.attached_list = QListWidget()
        self.attached_list.setFrameShape(QListWidget.NoFrame)
        self.attached_list.setIconSize(QSize(15, 15))
        self.attached_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.attached_list)
        self.detach_btn = QPushButton("Detach selected")
        self.detach_btn.setObjectName("smallBtn")
        self.detach_btn.setCursor(Qt.PointingHandCursor)
        self.detach_btn.clicked.connect(self._detach_selected)
        root.addWidget(self.detach_btn)

        self._refresh_empty_state()

    def _refresh_empty_state(self):
        has_mentions = self.mentions_box.count() > 0
        has_attached = self.attached_list.count() > 0
        self.empty.setVisible(not has_mentions and not has_attached)
        self.attached_label.setVisible(has_attached)
        self.attached_list.setVisible(has_attached)
        self.detach_btn.setVisible(has_attached)

    def clear_mentions(self):
        while self.mentions_box.count():
            item = self.mentions_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._refresh_empty_state()

    def add_mention(self, index: int, description: str, resolved: str, kind: str):
        row = MentionRow(index, description, resolved, kind)
        row.accepted.connect(self.mention_accepted.emit)
        row.changed.connect(self.mention_change_requested.emit)
        self.mentions_box.addWidget(row)
        self._refresh_empty_state()

    def set_attached(self, attachments: list[dict]):
        self.attached_list.clear()
        for a in attachments:
            item = QListWidgetItem(
                icons.icon("folder" if a["kind"] == "folder" else "file", 15,
                           theme.NEUTRAL[600]),
                a["name"])
            item.setData(1000, a["path"])
            item.setToolTip(a["path"])
            self.attached_list.addItem(item)
        # Height follows the list, capped at five rows — a single attachment
        # shouldn't leave an empty tray sitting in the rail.
        rows = min(max(len(attachments), 1), 5)
        self.attached_list.setFixedHeight(rows * 29 + 8)
        self._refresh_empty_state()

    def _detach_selected(self):
        it = self.attached_list.currentItem()
        if it:
            self.detach_requested.emit(it.data(1000))
