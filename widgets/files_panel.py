"""Panel: what Prism guessed you meant by file/folder mentions, plus the
final attached-files list. Mirrors the CLI's /find confirm-before-attach flow
as buttons instead of a Y/n prompt."""
from __future__ import annotations
from PySide6.QtCore import Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QGraphicsOpacityEffect,
)


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
        self.setObjectName("mentionRow")
        row = QHBoxLayout(self)
        icon = "📁" if kind == "folder" else ("📄" if kind == "file" else "❓")
        text = f"{icon}  \"{description}\"  →  {resolved or '(not found)'}"
        row.addWidget(QLabel(text), stretch=1)
        accept = QPushButton("Keep this")
        accept.clicked.connect(lambda: self.accepted.emit(self.index))
        row.addWidget(accept)
        change = QPushButton("Change…")
        change.clicked.connect(lambda: self.changed.emit(self.index))
        row.addWidget(change)
        _fade_in(self)


class FilesPanel(QWidget):
    mention_accepted = Signal(int)
    mention_change_requested = Signal(int)
    detach_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(6)
        title = QLabel("Files & Folders Prism Found")
        title.setObjectName("panelTitle")
        root.addWidget(title)

        self.empty = QLabel(
            "No files attached yet — speak a task mentioning one, or use\n"
            "Attach file / Attach folder above.")
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        self.mentions_box = QVBoxLayout()
        mentions_wrap = QWidget()
        mentions_wrap.setLayout(self.mentions_box)
        root.addWidget(mentions_wrap)

        self.attached_label = QLabel("Attached")
        self.attached_label.setObjectName("dim")
        root.addWidget(self.attached_label)
        self.attached_list = QListWidget()
        self.attached_list.setMaximumHeight(90)
        root.addWidget(self.attached_list)
        self.detach_btn = QPushButton("Detach selected")
        self.detach_btn.clicked.connect(self._detach_selected)
        self.detach_btn.setVisible(False)
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
            item = QListWidgetItem(f"{a['name']}  ({a['kind']})")
            item.setData(1000, a["path"])
            self.attached_list.addItem(item)
        self._refresh_empty_state()

    def _detach_selected(self):
        it = self.attached_list.currentItem()
        if it:
            self.detach_requested.emit(it.data(1000))
