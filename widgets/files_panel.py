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

import i18n
import theme
from widgets import icons
from widgets.controls import kicker

def _label(att: dict) -> str:
    """The row's text, saying so when only part of the file will be read.

    Prism inlines the first 12,000 characters of a file's text. For a 60-page
    tender that is roughly the first eight pages, and silently answering from
    an eighth of a document is a wrong deliverable rather than a degraded one.
    Truncation is reasonable; not mentioning it is not.
    """
    if att.get("truncated"):
        return f"{att['name']}   (first part only)"
    return att["name"]


def _tip(att: dict) -> str:
    if att.get("truncated"):
        return (f"{att['path']}\n\nThis file is long, so Prism is using its "
                f"first 12,000 characters — about 8 pages. The whole file is "
                f"still uploaded to any tool that accepts attachments.")
    return att["path"]


# Item roles and what "Detach selected" should do with the highlighted row.
_PATH_ROLE = 1000
_MODE_ROLE = 1001
DETACH_FILE = "file"
DETACH_FOLDER = "folder"


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

        self.setToolTip(i18n.t('"{what}"  →  {where}').format(
            what=description, where=resolved or i18n.t("(not found)")))

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
    detach_folder_requested = Signal(str)   # the folder's own path
    detach_all_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)
        # No "Files you mentioned" heading here. The context rail draws it
        # itself, on the same line as the collapse chevron — having both
        # printed it put the title on screen twice.

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
        # Detaching one file at a time is fine until "Add folder" puts
        # fifteen of them in at once — the engine attaches a folder as its
        # individual files, so there was no single thing to take back out.
        # Selecting a folder's header row now removes the whole group.
        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        self.detach_btn = QPushButton("Detach selected")
        self.detach_btn.setObjectName("smallBtn")
        self.detach_btn.setCursor(Qt.PointingHandCursor)
        self.detach_btn.setToolTip(
            "Removes the highlighted file — or, if you highlight a folder "
            "heading, everything that came from that folder.")
        self.detach_btn.clicked.connect(self._detach_selected)
        buttons.addWidget(self.detach_btn)
        self.detach_all_btn = QPushButton("Detach all")
        self.detach_all_btn.setObjectName("smallBtn")
        self.detach_all_btn.setCursor(Qt.PointingHandCursor)
        self.detach_all_btn.setToolTip("Take every attached file back out.")
        self.detach_all_btn.clicked.connect(self.detach_all_requested.emit)
        buttons.addWidget(self.detach_all_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self._refresh_empty_state()

    def _refresh_empty_state(self):
        has_mentions = self.mentions_box.count() > 0
        has_attached = self.attached_list.count() > 0
        self.empty.setVisible(not has_mentions and not has_attached)
        self.attached_label.setVisible(has_attached)
        self.attached_list.setVisible(has_attached)
        self.detach_btn.setVisible(has_attached)
        self.detach_all_btn.setVisible(has_attached)

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
        """Draw the tray: loose files as themselves, folders as one heading
        with their files indented underneath.

        Grouping is presentation only — the engine still receives the flat
        list of files, because that is what it uploads. What it buys is a
        single row that means "this whole folder", which is the thing there
        was previously no way to take back out.
        """
        self.attached_list.clear()

        loose = [a for a in attachments if not a.get("from_dir")]
        folders: dict[str, list[dict]] = {}
        for a in attachments:
            if a.get("from_dir"):
                folders.setdefault(a["from_dir"], []).append(a)

        for a in loose:
            self._add_row(_label(a), a["path"], DETACH_FILE,
                          "folder" if a.get("kind") == "folder" else "file",
                          _tip(a))

        for folder, files in folders.items():
            count = len(files)
            self._add_row(
                f"{os.path.basename(folder.rstrip(os.sep)) or folder}"
                f"   ({count} file{'' if count == 1 else 's'})",
                folder, DETACH_FOLDER, "folder", folder, bold=True)
            for a in files:
                self._add_row("     " + _label(a), a["path"], DETACH_FILE,
                              "file", _tip(a), muted=True)

        rows = min(max(self.attached_list.count(), 1), 6)
        self.attached_list.setFixedHeight(rows * 29 + 8)
        self._refresh_empty_state()

    def _add_row(self, label: str, target: str, mode: str, icon_name: str,
                 tip: str, *, bold: bool = False, muted: bool = False):
        item = QListWidgetItem(
            icons.icon(icon_name, 15,
                       theme.ACCENT if bold else theme.NEUTRAL[600]),
            label)
        item.setData(_PATH_ROLE, target)
        item.setData(_MODE_ROLE, mode)
        item.setToolTip(tip if not bold else
                        f"{tip}\n\nSelect this row and press Detach selected "
                        f"to remove the whole folder.")
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        if muted:
            item.setForeground(theme.c(theme.NEUTRAL[600]))
        self.attached_list.addItem(item)

    def _detach_selected(self):
        it = self.attached_list.currentItem()
        if not it:
            return
        if it.data(_MODE_ROLE) == DETACH_FOLDER:
            self.detach_folder_requested.emit(it.data(_PATH_ROLE))
        else:
            self.detach_requested.emit(it.data(_PATH_ROLE))
