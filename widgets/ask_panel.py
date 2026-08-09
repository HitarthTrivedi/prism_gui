"""One box to say what you want — reused by every add-on screen.

The target user is a business owner, not a software user. They should not
have to find a setting, understand a category, or know which box a file goes
in. So every add-on opens the same way the home screen does: one large
prompt, a Speak button, an Add file button, and their starred folders one
click away. Everything else on the screen is either automatic or folded
away behind "More options".

Anything technical that still has to exist (drawing path, units, layer
filters, recipient lists) lives in a collapsed section that a first-time
user never opens.
"""
from __future__ import annotations
import os

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel,
    QFileDialog, QMenu, QFrame,
)

import favorites
import i18n
import theme
from widgets import icons


def small_button(label: str, icon_name: str, tip: str = "") -> QPushButton:
    btn = QPushButton(f" {label}")
    btn.setObjectName("smallBtn")
    btn.setCursor(Qt.PointingHandCursor)
    icons.button_icon(btn, icon_name, 15, theme.TEXT)
    if tip:
        btn.setToolTip(tip)
    return btn


class AskPanel(QWidget):
    """A prompt box + Speak + Add file + Favourites, and a list of chips for
    whatever is attached."""

    speak_clicked = Signal()
    files_added = Signal(list)      # list of absolute paths

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.edit = QTextEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFixedHeight(92)
        root.addWidget(self.edit)

        row = QHBoxLayout()
        self.mic_btn = small_button("Speak", "mic", "Say it instead of typing")
        self.mic_btn.clicked.connect(self.speak_clicked.emit)
        row.addWidget(self.mic_btn)

        add_btn = small_button("Add file", "paperclip",
                               "Attach a drawing, a list, a brochure — anything")
        add_btn.clicked.connect(self._pick_file)
        row.addWidget(add_btn)

        self.fav_btn = small_button("Favourites", "folder",
                                    "Your starred files and folders")
        self.fav_btn.clicked.connect(self._show_favourites)
        row.addWidget(self.fav_btn)
        row.addStretch(1)
        root.addLayout(row)

        self.chips = QLabel("")
        self.chips.setObjectName("emptyState")
        self.chips.setWordWrap(True)
        self.chips.setVisible(False)
        root.addWidget(self.chips)

    # ── text ────────────────────────────────────────────────────────────
    def text(self) -> str:
        return self.edit.toPlainText().strip()

    def set_text(self, value: str):
        self.edit.setPlainText(value)

    def append_text(self, value: str):
        existing = self.text()
        self.edit.setPlainText((existing + " " + value).strip())

    def set_recording(self, on: bool):
        self.mic_btn.setText(" Stop" if on else " Speak")

    # ── files ───────────────────────────────────────────────────────────
    def _pick_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, i18n.t("Attach files"))
        if paths:
            self.add_paths(paths)

    def _show_favourites(self):
        items = favorites.load()
        menu = QMenu(self)
        if not items:
            act = menu.addAction("No favourites yet — star them on the home screen")
            act.setEnabled(False)
        else:
            for it in items:
                label = it.get("label") or os.path.basename(it["path"])
                act = menu.addAction(label)
                act.triggered.connect(
                    lambda _=False, p=it["path"]: self._add_favourite(p))
        menu.exec(self.fav_btn.mapToGlobal(self.fav_btn.rect().bottomLeft()))

    def _add_favourite(self, path: str):
        # A starred FOLDER is a shelf, not an attachment — open it so the
        # user picks the file they actually mean, rather than silently
        # attaching a whole directory.
        if os.path.isdir(path):
            picked, _ = QFileDialog.getOpenFileNames(
                self, i18n.t("Choose from this folder"), path)
            if picked:
                self.add_paths(picked)
        else:
            self.add_paths([path])

    def add_paths(self, paths: list[str]):
        fresh = [p for p in paths if p and p not in self._paths]
        if not fresh:
            return
        self._paths += fresh
        self._refresh_chips()
        self.files_added.emit(fresh)

    def paths(self) -> list[str]:
        return list(self._paths)

    def clear_files(self):
        self._paths = []
        self._refresh_chips()

    def _refresh_chips(self):
        if not self._paths:
            self.chips.setVisible(False)
            return
        names = "   ".join(f"📎 {os.path.basename(p)}" for p in self._paths)
        self.chips.setText(names)
        self.chips.setVisible(True)


class MoreOptions(QFrame):
    """A section that stays shut until someone wants it.

    Everything a non-technical user must never be confronted with goes in
    here: file paths, units, layer filters, recipient editing. Hidden by
    default, one click to open, and the button says plainly that it is
    optional."""

    def __init__(self, label: str = "More options", parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.toggle = QPushButton(
            "  " + i18n.t("{label}  (optional)").format(label=i18n.t(label)))
        self.toggle.setObjectName("smallBtn")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setCheckable(True)
        icons.button_icon(self.toggle, "chevron-right", 14, theme.NEUTRAL[600])
        self.toggle.clicked.connect(self._toggled)
        root.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body.setVisible(False)
        root.addWidget(self.body)

    def _toggled(self, checked: bool):
        self.body.setVisible(checked)
        icons.button_icon(self.toggle,
                          "chevron-down" if checked else "chevron-right",
                          14, theme.NEUTRAL[600])

    def add(self, widget):
        self.body_layout.addWidget(widget)

    def add_layout(self, layout):
        self.body_layout.addLayout(layout)
