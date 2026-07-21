"""Left sidebar: every CLI '/' command as a click target, grouped by intent,
plus favorites and the wake-word toggle."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QCheckBox,
)

import favorites as FAV

# (command key, label, tooltip) grouped under section headers — mirrors
# prism_terminal/prism.py's HELP text, but grouped by what the user is
# trying to do rather than dumped as one flat list.
SECTIONS = [
    ("WORKSPACE", [
        ("status", "📊  Status", "Current profile, key & agents"),
        ("runs",   "🗂️  Run History", "List saved runs"),
    ]),
    ("CONFIGURE", [
        ("agents",  "🧩  Agents",         "Re-pick one agent per category (saved default)"),
        ("profile", "🧑  Profile",        "Change what-you-do"),
        ("key",     "🔑  API Key",        "Change your Groq API key"),
        ("chrome",  "🌐  Chrome Version", "Pin or auto-detect your Chrome version"),
        ("config",  "⚙️  Full Setup",     "Re-run the whole setup wizard"),
    ]),
    ("TOOLS", [
        ("catalog", "📚  AI Directory", "What every AI agent is picked for"),
        ("login",   "🔐  Login Tabs",   "Re-open your tools in Chrome to sign in"),
        ("email",   "✉️  Email",        "Draft & send an email from attached files/CSV"),
    ]),
]

_HEADER_ROLE = 1001
_KEY_ROLE = 1000


class Sidebar(QWidget):
    command_triggered = Signal(str)
    favorite_chosen = Signal(str)
    wakeword_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(260)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 18, 14, 16)
        root.setSpacing(8)

        brand = QLabel("◈  PRISM")
        brand.setObjectName("brand")
        root.addWidget(brand)

        wake_row = QHBoxLayout()
        wake_row.setSpacing(6)
        self.wake_check = QCheckBox('🎙️  Listen for "Prism"')
        self.wake_check.setToolTip(
            "Best-effort wake word: polls the mic every ~2s and checks Groq "
            "Whisper for the word 'Prism'. Not instant like a real wake-word "
            "engine — see wakeword.py for details.")
        self.wake_check.toggled.connect(self.wakeword_toggled.emit)
        wake_row.addWidget(self.wake_check, stretch=1)
        self.listen_dot = QLabel("●")
        self.listen_dot.setObjectName("listenDot")
        self.listen_dot.setToolTip('Listening for "Prism"…')
        self.listen_dot.setVisible(False)
        wake_row.addWidget(self.listen_dot)
        root.addLayout(wake_row)

        self.cmd_list = QListWidget()
        self.cmd_list.setObjectName("cmdList")
        self.cmd_list.setFrameShape(QListWidget.NoFrame)
        self.cmd_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for section, items in SECTIONS:
            self.cmd_list.addItem(self._header_item(section))
            for key, label, tip in items:
                item = QListWidgetItem(label)
                item.setData(_KEY_ROLE, key)
                item.setToolTip(tip)
                self.cmd_list.addItem(item)
        self.cmd_list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.cmd_list, stretch=2)

        fav_row = QHBoxLayout()
        fav_row.addWidget(QLabel("FAVORITES"), stretch=1)
        add_btn = QPushButton("＋")
        add_btn.setObjectName("iconBtn")
        add_btn.setFixedWidth(30)
        add_btn.setToolTip("Favorite a file or folder")
        add_btn.clicked.connect(self._add_favorite)
        fav_row.addWidget(add_btn)
        rm_btn = QPushButton("🗑")
        rm_btn.setObjectName("iconBtn")
        rm_btn.setFixedWidth(30)
        rm_btn.setToolTip("Remove the selected favorite")
        rm_btn.clicked.connect(self._remove_favorite)
        fav_row.addWidget(rm_btn)
        root.addLayout(fav_row)

        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favList")
        self.fav_list.setFrameShape(QListWidget.NoFrame)
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fav_list.setToolTip("Double-click to attach")
        self.fav_list.itemDoubleClicked.connect(self._favorite_clicked)
        root.addWidget(self.fav_list, stretch=2)

        self.reload_favorites()

    @staticmethod
    def _header_item(text: str) -> QListWidgetItem:
        header = QListWidgetItem(text)
        header.setFlags(Qt.NoItemFlags)
        header.setData(_HEADER_ROLE, True)
        header.setForeground(QColor("#6E7180"))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        header.setFont(font)
        return header

    def _on_item_clicked(self, item: QListWidgetItem):
        key = item.data(_KEY_ROLE)
        if key:
            self.command_triggered.emit(key)

    def set_listening(self, on: bool):
        self.listen_dot.setVisible(on)

    def reload_favorites(self):
        self.fav_list.clear()
        items = FAV.load()
        if not items:
            placeholder = self._header_item("No favorites yet")
            placeholder.setToolTip("Click ＋ above to favorite a file or folder")
            self.fav_list.addItem(placeholder)
            return
        for item in items:
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
        if not it or not it.data(1000):
            return
        FAV.remove(it.data(1000))
        self.reload_favorites()

    def _favorite_clicked(self, item: QListWidgetItem):
        path = item.data(1000)
        if path:
            self.favorite_chosen.emit(path)
