"""Left rail: brand, the four primary destinations, the wake-word switch,
and favorites.

The design gives the rail four nav items (Home / AI tools / History /
Settings). Prism has more commands than that, so the rest keep the same
.navitem shape one size down under a tracked section label — the same
treatment the mock already uses for Favorites — rather than inventing a
second kind of control."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QWidget,
)

import favorites as FAV
import theme
from widgets import icons
from widgets.controls import ToggleSwitch, kicker, track

_PATH_ROLE = 1000

# (key, label, icon) — the primary destinations, straight from the mock.
PRIMARY = [
    ("home",    "Home",     "home"),
    ("catalog", "AI tools", "grid"),
    ("runs",    "History",  "clock"),
    ("config",  "Settings", "sliders"),
]

# Everything else the CLI exposes, grouped by intent.
SECONDARY = [
    ("WORKSPACE", [
        ("status", "Status",       "chart", "Current profile, key & agents"),
        ("login",  "Login tabs",   "lock",  "Re-open your tools in Chrome to sign in"),
        ("email",  "Email",        "mail",  "Draft & send an email from attached files"),
    ]),
    ("CONFIGURE", [
        ("agents",  "Agents",  "grid",  "Re-pick one agent per category"),
        ("profile", "Profile", "user",  "Change what-you-do"),
        ("key",     "API key", "key",   "Change your Groq API key"),
        ("chrome",  "Chrome",  "globe", "Pin or auto-detect your Chrome version"),
    ]),
]


def nav_button(label: str, icon_name: str, small: bool = False,
               tip: str = "") -> QPushButton:
    btn = QPushButton(f"  {label}")
    btn.setObjectName("navItem")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFlat(True)
    size = 15 if small else 17
    icons.button_icon(btn, icon_name, size, theme.NEUTRAL[600])
    btn.setIconSize(QSize(size, size))
    btn.setProperty("cur", False)
    if tip:
        btn.setToolTip(tip)
    if small:
        btn.setStyleSheet("padding: 6px 11px; font-size: 13px;")
    return btn


class Sidebar(QFrame):
    command_triggered = Signal(str)
    favorite_chosen = Signal(str)
    wakeword_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 18, 14, 14)
        root.setSpacing(2)

        root.addWidget(self._brand())
        root.addSpacing(16)

        # -- primary destinations ------------------------------------------
        self._nav: dict[str, QPushButton] = {}
        for key, label, icon_name in PRIMARY:
            btn = nav_button(label, icon_name)
            btn.clicked.connect(lambda _=False, k=key: self._go(k))
            self._nav[key] = btn
            root.addWidget(btn)
        self._current = "home"
        self._refresh_nav()

        root.addSpacing(12)
        root.addWidget(self._rule())
        root.addSpacing(6)

        # -- wake word ------------------------------------------------------
        wake = QWidget()
        wake_row = QHBoxLayout(wake)
        wake_row.setContentsMargins(11, 7, 11, 7)
        wake_row.setSpacing(10)
        self.wake_switch = ToggleSwitch()
        self.wake_switch.setToolTip(
            "Best-effort wake word: polls the mic every ~2s and checks Groq "
            "Whisper for the word 'Prism'. Not instant like a real wake-word "
            "engine — see wakeword.py for details.")
        self.wake_switch.toggled.connect(self.wakeword_toggled.emit)
        wake_row.addWidget(self.wake_switch)
        wake_label = QLabel('Listen for "Prism"')
        wake_label.setStyleSheet("font-size: 13px; color: #424244;")
        wake_row.addWidget(wake_label, stretch=1)
        root.addWidget(wake)

        # -- everything else ------------------------------------------------
        for section, items in SECONDARY:
            root.addSpacing(12)
            root.addWidget(kicker(section, muted=True))
            root.addSpacing(4)
            for key, label, icon_name, tip in items:
                btn = nav_button(label, icon_name, small=True, tip=tip)
                btn.clicked.connect(lambda _=False, k=key: self.command_triggered.emit(k))
                root.addWidget(btn)

        # -- favorites -------------------------------------------------------
        root.addSpacing(14)
        fav_head = QHBoxLayout()
        fav_head.setSpacing(2)
        fav_head.addWidget(kicker("Favorites", muted=True), stretch=1)
        add_btn = self._mini("plus", "Favorite a file or folder", self._add_favorite)
        fav_head.addWidget(add_btn)
        rm_btn = self._mini("trash", "Remove the selected favorite", self._remove_favorite)
        fav_head.addWidget(rm_btn)
        root.addLayout(fav_head)
        root.addSpacing(4)

        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favList")
        self.fav_list.setFrameShape(QListWidget.NoFrame)
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fav_list.setStyleSheet("background: transparent; border: none; padding: 0;")
        self.fav_list.setToolTip("Double-click to attach")
        self.fav_list.setIconSize(QSize(15, 15))
        self.fav_list.itemDoubleClicked.connect(self._favorite_clicked)
        root.addWidget(self.fav_list, stretch=1)

        help_row = QHBoxLayout()
        help_row.setContentsMargins(2, 6, 2, 0)
        help_row.setSpacing(8)
        help_icon = QLabel()
        help_icon.setPixmap(icons.pixmap("help", 16, theme.NEUTRAL[600]))
        help_row.addWidget(help_icon)
        help_text = QLabel("Need a hand?")
        help_text.setObjectName("meta")
        help_text.setToolTip("Every panel explains itself — hover anything.")
        help_row.addWidget(help_text, stretch=1)
        root.addLayout(help_row)

        self.reload_favorites()

    # ── chrome ────────────────────────────────────────────────────────────
    def _brand(self) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(icons.logo_pixmap(26))
        row.addWidget(mark)
        name = QLabel("PRISM")
        name.setObjectName("brand")
        row.addWidget(track(name, 0.16), stretch=1)
        return wrap

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("hr")
        line.setFixedHeight(1)
        return line

    def _mini(self, icon_name: str, tip: str, slot) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("ghostBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tip)
        btn.setFixedSize(24, 24)
        icons.button_icon(btn, icon_name, 14, theme.NEUTRAL[600])
        btn.clicked.connect(slot)
        return btn

    # ── nav ───────────────────────────────────────────────────────────────
    def _go(self, key: str):
        self.set_current(key)
        if key != "home":
            self.command_triggered.emit(key)

    def set_current(self, key: str):
        if key in self._nav:
            self._current = key
            self._refresh_nav()

    def _refresh_nav(self):
        for key, btn in self._nav.items():
            cur = key == self._current
            btn.setProperty("cur", cur)
            icons.button_icon(btn, dict((k, i) for k, _, i in PRIMARY)[key], 17,
                              theme.ACCENT_RAMP[800] if cur else theme.NEUTRAL[600])
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_listening(self, on: bool):
        """Reflect wake-word state pushed back from the window (e.g. it
        refused to start because no API key is set)."""
        if self.wake_switch.isChecked() != on:
            self.wake_switch.blockSignals(True)
            self.wake_switch.setChecked(on)
            self.wake_switch.blockSignals(False)

    # ── favorites ─────────────────────────────────────────────────────────
    def reload_favorites(self):
        self.fav_list.clear()
        items = FAV.load()
        if not items:
            placeholder = QListWidgetItem("No favorites yet")
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setToolTip("Click + above to favorite a file or folder")
            self.fav_list.addItem(placeholder)
            return
        for item in items:
            name = "folder" if item["kind"] == "folder" else "file"
            li = QListWidgetItem(icons.icon(name, 15, theme.NEUTRAL[600]), item["label"])
            li.setData(_PATH_ROLE, item["path"])
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
        if not it or not it.data(_PATH_ROLE):
            return
        FAV.remove(it.data(_PATH_ROLE))
        self.reload_favorites()

    def _favorite_clicked(self, item: QListWidgetItem):
        path = item.data(_PATH_ROLE)
        if path:
            self.favorite_chosen.emit(path)
