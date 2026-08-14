"""Left rail: brand, the five primary destinations, the wake-word switch,
and favorites.

Prism has more commands than that, so the rest keep the same .navitem shape
one size down under a tracked section label — the same treatment the mock
already uses for Favorites. CONFIGURE is the one exception: its seven rows
are all doors into the same Setup dialog the primary Settings button already
opens (see main_window._open_setup), so they ride behind a disclosure — the
same collapsed-by-default chevron pattern "Behind the scenes" already uses
(widgets/prompt_panel.py) — instead of showing seven settings to someone who
hasn't used the product once yet."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QWidget, QScrollArea,
)

import favorites as FAV
import i18n
import identity
import theme
from widgets import icons
from widgets.controls import ToggleSwitch, kicker, track

_PATH_ROLE = 1000

# (key, label, icon) — the primary destinations, straight from the mock.
PRIMARY = [
    ("home",    "Home",     "home"),
    ("guide",   "How to use Prism", "help"),
    ("catalog", "AI tools", "grid"),
    ("runs",    "History",  "clock"),
    ("config",  "Settings", "sliders"),
]

# Sentinel for a shelf item that isn't built yet, as opposed to one the
# customer simply hasn't bought.
SOON = "__soon__"

# Everything else the CLI exposes, grouped by intent. The 5th field is the
# licence entitlement the item needs — "" for anything always available.
SECONDARY = [
    # ADD-ONS are the purpose-built pipelines — the ones sold on top of the
    # generic product. Each one takes a real business document in and gives a
    # finished one out, rather than being a general prompt. New verticals
    # (quotation from spec, BOM vs inventory, export papers) land here.
    ("ADD-ONS", [
        # First in the list on purpose: it is the only add-on used every day.
        # BOQ is occasional and Email is a task; this one is the reason the
        # app gets opened at all, so it sits where the eye lands.
        ("inquiry", "Inquiry Automation", "inbox",
         "Read the inbox, register every inquiry, quote it and chase it",
         "inbox"),
        ("boq",   "BOQ",   "file", "Bill of Quantities — from a CAD drawing, or from a written spec", "boq"),
        ("email", "Email", "mail", "Draft & send an email from attached files", "email"),
        # Shown but disabled on purpose: the shelf should look like a product
        # line, and a visible "next one" is worth more in a client demo than
        # an empty gap. Reads as coming-soon, never as broken.
        ("bom",   "BOM & Stock", "list",
         "Coming soon — match a parts list against your stock and get the "
         "shortage list", SOON),
    ]),
    ("WORKSPACE", [
        ("status", "Status",       "chart", "Current profile, key & agents", ""),
        # Not "lock": that glyph means "you don't own this" everywhere else in
        # the rail (see set_entitlements below), and Login tabs is always
        # available — reusing it here would teach the wrong lesson.
        ("login",  "Login tabs",   "external", "Re-open your tools in Chrome to sign in", ""),
    ]),
    ("CONFIGURE", [
        ("licence", "Licence", "archive",
         "Your plan, what's included, seats and expiry", ""),
        ("agents",  "Agents",  "grid",  "Re-pick one agent per category", ""),
        ("language", "Language", "globe",
         "Prism's own language, and what the AI tools answer in", ""),
        ("team",    "Your role", "user",
         "Which job this copy is set up for, and the team workspace", ""),
        ("profile", "Profile", "user",  "Change what-you-do", ""),
        ("key",     "API key", "key",   "Change your Groq API key", ""),
        ("chrome",  "Chrome",  "globe", "Pin or auto-detect your Chrome version", ""),
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

        # The rail wants ~816px at its minimum and the window's floor is 640,
        # so on a 1366x768 laptop — ordinary kit in a drawing office — Qt was
        # squeezing the nav buttons below their sizeHint and clipping the
        # labels. Scroll instead of compressing: a rail you can reach is worth
        # more than one that fits. The stretch on the favourites list still
        # absorbs the slack whenever there IS room, so nothing changes on a
        # large screen.
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        inner = QWidget()
        inner.setObjectName("sidebarInner")
        scroll.setWidget(inner)
        shell.addWidget(scroll)

        root = QVBoxLayout(inner)
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
        self._gated: dict[str, tuple[QPushButton, str, str, str]] = {}
        self._configure_toggle: QPushButton | None = None
        for section, items in SECONDARY:
            root.addSpacing(12)
            if section == "CONFIGURE":
                root.addWidget(self._build_configure_group(items))
                continue
            root.addWidget(kicker(section, muted=True))
            root.addSpacing(4)
            for key, label, icon_name, tip, feature in items:
                soon = feature == SOON
                btn = nav_button(
                    i18n.t("{addon}  (soon)").format(addon=i18n.t(label))
                    if soon else label,
                    icon_name, small=True, tip=tip)
                if soon:
                    btn.setEnabled(False)
                else:
                    btn.clicked.connect(
                        lambda _=False, k=key: self.command_triggered.emit(k))
                    if feature:
                        self._gated[key] = (btn, label, icon_name, feature)
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
        help_text = QPushButton("Need a hand?")
        help_text.setFlat(True)
        help_text.setCursor(Qt.PointingHandCursor)
        help_text.setStyleSheet(
            f"text-align: left; border: none; color: {theme.NEUTRAL[600]};"
            f"font-size: 13px; padding: 0;")
        help_text.setToolTip("Opens the guide — what Prism can do and what to type")
        help_text.clicked.connect(lambda: self.command_triggered.emit("guide"))
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
        # Stacked under the wordmark when this copy belongs to a company
        # member: on a shared workspace several people run Prism side by side
        # and the accent colour alone does not say WHICH sales person.
        who = identity.describe()
        if who:
            stack = QVBoxLayout()
            stack.setContentsMargins(0, 0, 0, 0)
            stack.setSpacing(0)
            stack.addWidget(track(name, 0.16))
            member = QLabel(who)
            member.setObjectName("meta")
            member.setToolTip("This copy of Prism is set up for this person. "
                              "Change it in Settings \u2192 Your role.")
            stack.addWidget(member)
            row.addLayout(stack, stretch=1)
        else:
            row.addWidget(track(name, 0.16), stretch=1)
        return wrap

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("hr")
        line.setFixedHeight(1)
        return line

    def _build_configure_group(self, items) -> QWidget:
        """Seven raw settings collapsed behind one disclosure row instead of
        sitting flat in the rail. None of them are gated by licence (every
        `feature` field in CONFIGURE is empty), so — unlike ADD-ONS — there's
        no lock state to track here."""
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        toggle = QPushButton(f"  {i18n.t('More settings')}")
        toggle.setObjectName("navItem")
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setFlat(True)
        toggle.setCheckable(True)
        toggle.setLayoutDirection(Qt.RightToLeft)   # chevron on the right
        toggle.setStyleSheet("padding: 6px 11px; font-size: 13px;")
        icons.button_icon(toggle, "chevron-right", 15, theme.NEUTRAL[600])
        col.addWidget(toggle)

        body = QWidget()
        body_col = QVBoxLayout(body)
        body_col.setContentsMargins(0, 0, 0, 0)
        body_col.setSpacing(2)
        for key, label, icon_name, tip, _feature in items:
            btn = nav_button(label, icon_name, small=True, tip=tip)
            btn.clicked.connect(
                lambda _=False, k=key: self.command_triggered.emit(k))
            body_col.addWidget(btn)
        body.setVisible(False)
        col.addWidget(body)

        def _on_toggled(open_: bool):
            icons.button_icon(toggle, "chevron-down" if open_ else "chevron-right",
                              15, theme.NEUTRAL[600])
            body.setVisible(open_)
        toggle.toggled.connect(_on_toggled)
        self._configure_toggle = toggle
        return wrap

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
        if key == "config" and self._configure_toggle is not None:
            # Settings just got clicked on purpose: reveal the direct-jump
            # shortcuts underneath for next time, instead of making a
            # returning user find the disclosure themselves.
            self._configure_toggle.setChecked(True)
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

    # ── licence ───────────────────────────────────────────────────────────
    def set_entitlements(self, features, usable: bool = True):
        """Mark add-ons the licence doesn't cover.

        A padlock means one thing only: **you don't own this**. It must not
        also mean "we can't reach the server" — those need different actions
        from the customer, and padlocking a feature they have paid for tells
        them they've lost it. Availability is the banner's job; ownership is
        this. `usable` is accepted and ignored so callers need not care.

        Locked items stay **enabled**. Clicking one opens the pitch for it,
        which is the most useful thing that click can do — the customer has
        just told us exactly what they want. A greyed-out row sells nothing,
        and is indistinguishable from something broken.
        """
        for _, (btn, label, icon_name, feature) in self._gated.items():
            unlocked = feature in features
            # The icon swaps to a padlock; the label stays put. Appending
            # "(locked)" would make the shelf read as a list of things you
            # can't have rather than a product line.
            icons.button_icon(btn, icon_name if unlocked else "lock", 15,
                              theme.NEUTRAL[600] if unlocked else theme.NEUTRAL[400])
            btn.setProperty("locked", not unlocked)
            if not unlocked:
                btn.setToolTip(i18n.t(
                    "{addon} isn't in your licence — click to find out "
                    "about it").format(addon=label))
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
        path = QFileDialog.getExistingDirectory(self, i18n.t("Favorite a folder…"))
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, i18n.t("…or favorite a file"))
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
