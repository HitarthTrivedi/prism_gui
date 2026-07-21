"""Left sidebar: every CLI '/' command as a click target, plus favorites."""
from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QCheckBox,
)

import favorites as FAV

# (command key, label, tooltip) — mirrors prism_terminal/prism.py's HELP text.
COMMANDS = [
    ("status",    "📊  Status",           "Current profile, key & agents"),
    ("catalog",   "📚  AI Directory",      "What every AI agent is picked for"),
    ("agents",    "🧩  Agents",            "Re-pick one agent per category (saved default)"),
    ("profile",   "🧑  Profile",           "Change what-you-do"),
    ("key",       "🔑  API Key",           "Change your Groq API key"),
    ("chrome",    "🌐  Chrome Version",    "Pin or auto-detect your Chrome version"),
    ("login",     "🔐  Login Tabs",        "Re-open your tools in Chrome to sign in"),
    ("config",    "⚙️  Full Setup",        "Re-run the whole setup wizard"),
    ("email",     "✉️  Email",             "Draft & send an email from attached files/CSV"),
    ("runs",      "🗂️  Run History",       "List saved runs"),
]


class Sidebar(QWidget):
    command_triggered = Signal(str)
    favorite_chosen = Signal(str)
    wakeword_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(260)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 16, 12, 16)
        root.setSpacing(10)

        brand = QLabel("◈  PRISM")
        brand.setObjectName("brand")
        root.addWidget(brand)

        self.wake_check = QCheckBox('🎙️  Listen for "Prism" (experimental)')
        self.wake_check.setToolTip(
            "Best-effort wake word: polls the mic every ~2s and checks Groq "
            "Whisper for the word 'Prism'. Not instant like a real wake-word "
            "engine — see wakeword.py for details.")
        self.wake_check.toggled.connect(self.wakeword_toggled.emit)
        root.addWidget(self.wake_check)

        root.addWidget(QLabel("COMMANDS"))
        self.cmd_list = QListWidget()
        self.cmd_list.setObjectName("cmdList")
        for key, label, tip in COMMANDS:
            item = QListWidgetItem(label)
            item.setData(1000, key)
            item.setToolTip(tip)
            self.cmd_list.addItem(item)
        self.cmd_list.itemClicked.connect(
            lambda it: self.command_triggered.emit(it.data(1000)))
        root.addWidget(self.cmd_list, stretch=2)

        fav_row = QHBoxLayout()
        fav_row.addWidget(QLabel("FAVORITES"))
        add_btn = QPushButton("＋")
        add_btn.setFixedWidth(28)
        add_btn.setToolTip("Favorite a file or folder")
        add_btn.clicked.connect(self._add_favorite)
        fav_row.addWidget(add_btn)
        root.addLayout(fav_row)

        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favList")
        self.fav_list.itemDoubleClicked.connect(self._favorite_clicked)
        root.addWidget(self.fav_list, stretch=2)

        rm_btn = QPushButton("Remove selected favorite")
        rm_btn.clicked.connect(self._remove_favorite)
        root.addWidget(rm_btn)

        self.reload_favorites()

    def reload_favorites(self):
        self.fav_list.clear()
        for item in FAV.load():
            icon = "📁" if item["kind"] == "folder" else "📄"
            li = QListWidgetItem(f"{icon} {item['label']}")
            li.setData(1000, item["path"])
            li.setToolTip(item["path"])
            self.fav_list.addItem(li)

    def _add_favorite(self):
        path = QFileDialog.getExistingDirectory(self, "Favorite a folder…")
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "…or favorite a file")
        if not path:
            return
        FAV.add(path)
        self.reload_favorites()

    def _remove_favorite(self):
        it = self.fav_list.currentItem()
        if not it:
            return
        FAV.remove(it.data(1000))
        self.reload_favorites()

    def _favorite_clicked(self, item: QListWidgetItem):
        self.favorite_chosen.emit(item.data(1000))
