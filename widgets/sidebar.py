"""Left rail: brand, Home, the New-task button, the wake-word switch, the
add-on shelf, everything else, and the licence + profile foot.

The redesign turns this dark and re-orders it around one idea: the rail is a
*shelf*, and the thing you came to do is at the top of it. So Home and a single
filled "New task" button lead, the purpose-built add-ons come next with their
own colour-coded chips, and the generic destinations (AI tools, guide, history,
settings) drop into a quieter MORE group below them.

Two things here are Prism's and not the design's, and both are kept:

* **Favourites** — the design has no equivalent. It is the only way to re-attach
  a folder you use every day without walking a file dialog, so it stays, under
  MORE where it does not compete with the add-ons.
* **The direct-jump settings** (your role, API key, Chrome, login tabs). The
  design folds these into one Settings page, and they *are* also reachable
  there — but the disclosure keeps the one-click route for someone who already
  knows which one they want, which is most people who open it twice.
"""
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
from widgets.controls import Avatar, ToggleSwitch, elevate, kicker, track

_PATH_ROLE = 1000

# (key, label, icon) — the primary destination. The design cuts this to Home
# alone: everything else is either an add-on (its own shelf, below) or a place
# you go occasionally (MORE). A five-item primary group gave equal weight to
# "Settings" and "the thing the app is for".
PRIMARY = [
    ("home", "Home", "home"),
]

# Sentinel for a shelf item that isn't built yet, as opposed to one the
# customer simply hasn't bought.
SOON = "__soon__"

# The add-on shelf. The 5th field is the licence entitlement the item needs —
# "" for anything always available. The 6th is the chip hue: these are what
# make the shelf scannable, so each add-on keeps one colour everywhere it
# appears (rail chip, Home summary row, its own screen's stat cards).
ADDONS = [
    # First on purpose: it is the only add-on used every day. BOQ is occasional
    # and Email is a task; this one is the reason the app gets opened at all.
    ("inquiry", "Inquiry Automation", "inbox",
     "Read the inbox, register every inquiry, quote it and chase it",
     "inbox", theme.OK),
    ("boq", "BOQ", "file",
     "Bill of Quantities — from a CAD drawing, or from a written spec",
     "boq", theme.ACCENT),
    ("email", "Email", "mail",
     "Draft & send an email from attached files", "email", theme.WARN),
    ("reel", "Reel / Studio", "video",
     "Turn a task into a short video, drawn and rendered automatically",
     "reel", theme.ACCENT_RAMP[600]),
    # Shown but disabled on purpose: the shelf should look like a product line,
    # and a visible "next one" is worth more in a client demo than an empty
    # gap. Reads as coming-soon, never as broken.
    ("bom", "BOM & Stock", "list",
     "Coming soon — match a parts list against your stock and get the "
     "shortage list", SOON, theme.NEUTRAL[500]),
]

# Everything that is neither Home nor an add-on.
MORE = [
    ("catalog", "AI tools", "grid", "Every tool Prism can drive, and whether "
     "you're signed in to it"),
    ("guide", "How to use Prism", "help",
     "What Prism can do and what to type"),
    ("runs", "History", "clock", "Every past run, re-rendered"),
    ("config", "Settings", "sliders", "Licence, agents, profile and language"),
]

# Behind the disclosure under MORE. Every one of these is also a section of the
# Settings screen; these are the shortcuts for people who know where they are
# going. None are licence-gated, so unlike ADDONS there is no lock to track.
DIRECT = [
    ("status", "Status", "chart", "Current profile, key & agents"),
    # Not "lock": that glyph means "you don't own this" everywhere else in the
    # rail, and Login tabs is always available — reusing it would teach the
    # wrong lesson.
    ("login", "Login tabs", "external",
     "Re-open your tools in Chrome to sign in"),
    ("licence", "Licence", "archive",
     "Your plan, what's included, seats and expiry"),
    ("agents", "Agents", "grid", "Re-pick one agent per category"),
    ("language", "Language", "globe",
     "Prism's own language, and what the AI tools answer in"),
    ("team", "Your role", "user",
     "Which job this copy is set up for, and the team workspace"),
    ("profile", "Profile", "user", "Change what-you-do"),
    ("key", "API key", "key", "Change your Groq API key"),
    ("chrome", "Chrome", "globe", "Pin or auto-detect your Chrome version"),
]


def _amp(text: str) -> str:
    """Escape an ampersand for a button label.

    Qt reads `&` in button text as an accelerator marker, so "BOM & Stock"
    rendered as "BOM_Stock" with the S underlined. Every label that reaches a
    QPushButton goes through here.
    """
    return text.replace("&", "&&")


def nav_button(label: str, icon_name: str, small: bool = False,
               tip: str = "") -> QPushButton:
    btn = QPushButton(f"  {_amp(label)}")
    btn.setObjectName("navSub" if small else "navItem")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFlat(True)
    size = 15 if small else 17
    icons.button_icon(btn, icon_name, size,
                      "#ffffff" if not small else theme.over(0.40))
    btn.setIconSize(QSize(size, size))
    btn.setProperty("cur", False)
    if tip:
        btn.setToolTip(tip)
    return btn


class AddonRow(QPushButton):
    """A shelf item: a colour-tinted chip carrying the add-on's glyph, then its
    name. The chip is what separates this group from the flat rows above and
    below it — an add-on is a product, and it gets to look like one."""

    CHIP = 24

    def __init__(self, label: str, icon_name: str, hue: str, parent=None):
        super().__init__(parent)
        self.setObjectName("navSub")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self._hue = hue
        self._icon_name = icon_name

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(10)
        self._chip = QLabel()
        self._chip.setFixedSize(self.CHIP, self.CHIP)
        self._chip.setAlignment(Qt.AlignCenter)
        row.addWidget(self._chip)
        self._label = QLabel(label)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self._label, stretch=1)
        self.setMinimumHeight(34)
        self.set_muted(False)

    def set_muted(self, muted: bool, icon_name: str = ""):
        """Locked and coming-soon items keep the chip but lose its colour, so
        the shelf still reads as one list rather than two."""
        hue = theme.NEUTRAL[500] if muted else self._hue
        bg = ("rgba(255,255,255,0.08)" if muted
              else theme.tint(hue, "2e"))
        ink = theme.over(0.40) if muted else hue
        self._chip.setPixmap(icons.pixmap(icon_name or self._icon_name, 14, ink))
        self._chip.setStyleSheet(f"background: {bg}; border-radius: 7px;")
        self._label.setStyleSheet(
            "font-size: 13px; font-weight: 500; background: transparent;"
            f" color: {'rgba(255,255,255,0.32)' if muted else 'rgba(255,255,255,0.82)'};")


class Sidebar(QFrame):
    command_triggered = Signal(str)
    favorite_chosen = Signal(str)
    wakeword_toggled = Signal(bool)
    tour_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(240)

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
        root.setContentsMargins(14, 20, 14, 14)
        root.setSpacing(2)

        root.addWidget(self._brand())
        root.addSpacing(14)

        # -- primary destination --------------------------------------------
        self._nav: dict[str, QPushButton] = {}
        for key, label, icon_name in PRIMARY:
            btn = nav_button(i18n.t(label), icon_name)
            btn.clicked.connect(lambda _=False, k=key: self._go(k))
            self._nav[key] = btn
            root.addWidget(btn)
        self._current = "home"

        # -- the one filled control in the rail ------------------------------
        self.new_task_btn = QPushButton(f"  {i18n.t('New task')}")
        self.new_task_btn.setObjectName("railPrimary")
        self.new_task_btn.setCursor(Qt.PointingHandCursor)
        icons.button_icon(self.new_task_btn, "plus", 15, "#ffffff")
        self.new_task_btn.clicked.connect(
            lambda: self.command_triggered.emit("workbench"))
        elevate(self.new_task_btn, theme.SHADOW_ACCENT, theme.ACCENT)
        root.addSpacing(6)
        root.addWidget(self.new_task_btn)
        root.addSpacing(4)

        root.addSpacing(8)
        root.addWidget(self._rule())
        root.addSpacing(4)

        # -- wake word ------------------------------------------------------
        wake = QWidget()
        wake_row = QHBoxLayout(wake)
        wake_row.setContentsMargins(12, 7, 12, 7)
        wake_row.setSpacing(10)
        self.wake_switch = ToggleSwitch()
        self.wake_switch.setToolTip(
            "Best-effort wake word: polls the mic every ~2s and checks Groq "
            "Whisper for the word 'Prism'. Not instant like a real wake-word "
            "engine — see wakeword.py for details.")
        self.wake_switch.toggled.connect(self.wakeword_toggled.emit)
        wake_row.addWidget(self.wake_switch)
        wake_label = QLabel(i18n.t('Listen for "Prism"'))
        wake_label.setObjectName("railMuted")
        wake_label.setStyleSheet("font-size: 12.5px;")
        wake_row.addWidget(wake_label, stretch=1)
        root.addWidget(wake)

        # -- the add-on shelf -------------------------------------------------
        root.addSpacing(6)
        root.addWidget(self._section("ADD-ONS"))
        root.addSpacing(4)
        self._gated: dict[str, tuple[AddonRow, str, str, str]] = {}
        for key, label, icon_name, tip, feature, hue in ADDONS:
            soon = feature == SOON
            text = (i18n.t("{addon}  (soon)").format(addon=i18n.t(label))
                    if soon else i18n.t(label))
            row = AddonRow(text, icon_name, hue)
            row.setToolTip(i18n.t(tip))
            if soon:
                row.setEnabled(False)
                row.set_muted(True)
            else:
                row.clicked.connect(
                    lambda _=False, k=key: self.command_triggered.emit(k))
                if feature:
                    self._gated[key] = (row, label, icon_name, feature)
            root.addWidget(row)

        # -- everything else --------------------------------------------------
        root.addSpacing(6)
        root.addWidget(self._section("MORE", faint=True))
        root.addSpacing(4)
        for key, label, icon_name, tip in MORE:
            btn = nav_button(i18n.t(label), icon_name, small=True, tip=i18n.t(tip))
            btn.clicked.connect(
                lambda _=False, k=key: self._go(k))
            self._nav[key] = btn
            root.addWidget(btn)

        root.addWidget(self._build_direct_group())

        # -- favorites -------------------------------------------------------
        root.addSpacing(8)
        fav_head = QHBoxLayout()
        fav_head.setSpacing(2)
        fav_head.addWidget(self._section("Favorites", faint=True), stretch=1)
        fav_head.addWidget(
            self._mini("plus", "Favorite a file or folder", self._add_favorite))
        fav_head.addWidget(
            self._mini("trash", "Remove the selected favorite",
                       self._remove_favorite))
        root.addLayout(fav_head)
        root.addSpacing(2)

        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favList")
        self.fav_list.setFrameShape(QListWidget.NoFrame)
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # On the dark rail the shared QListWidget rules would paint a white
        # box; the favourites list is part of the rail, not a control on it.
        self.fav_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; padding: 0;"
            " color: rgba(255,255,255,0.6); font-size: 12.5px; }"
            "QListWidget::item { padding: 5px 6px; border-radius: 7px; }"
            "QListWidget::item:hover { background: rgba(255,255,255,0.07);"
            " color: #ffffff; }"
            "QListWidget::item:selected { background: rgba(255,255,255,0.10);"
            " color: #ffffff; }")
        self.fav_list.setToolTip("Double-click to attach")
        self.fav_list.setIconSize(QSize(15, 15))
        self.fav_list.itemDoubleClicked.connect(self._favorite_clicked)
        # Sized to its contents by reload_favorites(), not stretched. Inside
        # the rail's scroll area a stretching list has no slack to take — the
        # content is already taller than the viewport — so Qt collapsed it to
        # its minimum and the favourites vanished entirely.
        self.fav_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        root.addWidget(self.fav_list)
        root.addStretch(1)

        # -- foot -------------------------------------------------------------
        # Pinned below the scroll area rather than inside it. The design keeps
        # these at the bottom of the rail with a flex spacer, which works
        # because a browser page is as tall as it needs to be. Here the rail is
        # a fixed 100%-height column that already scrolls on a 768px laptop, so
        # anything left inside would be pushed off the bottom — and "which plan
        # am I on" and "whose copy is this" are exactly the two things that
        # must never require a scroll to answer.
        foot = QWidget()
        foot.setObjectName("sidebarInner")
        foot_col = QVBoxLayout(foot)
        foot_col.setContentsMargins(14, 6, 14, 14)
        foot_col.setSpacing(2)

        tour = QPushButton(f"  {i18n.t('Take a tour')}")
        tour.setObjectName("navSub")
        tour.setFlat(True)
        tour.setCursor(Qt.PointingHandCursor)
        tour.setToolTip(i18n.t("A six-step walk through where everything lives"))
        icons.button_icon(tour, "help", 14, theme.over(0.45))
        tour.clicked.connect(self.tour_requested.emit)
        foot_col.addWidget(tour)

        foot_col.addSpacing(4)
        foot_col.addWidget(self._licence_card())
        foot_col.addSpacing(2)
        foot_col.addWidget(self._profile_row())
        shell.addWidget(foot)

        self.reload_favorites()
        self._refresh_nav()

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
            stack.addWidget(track(name, 0.14))
            member = QLabel(who)
            member.setObjectName("railMuted")
            member.setStyleSheet("font-size: 11px;")
            member.setToolTip("This copy of Prism is set up for this person. "
                              "Change it in Settings → Your role.")
            stack.addWidget(member)
            row.addLayout(stack, stretch=1)
        else:
            row.addWidget(track(name, 0.14), stretch=1)
        return wrap

    @staticmethod
    def _section(text: str, faint: bool = False) -> QLabel:
        lbl = kicker(text, muted=True)
        lbl.setObjectName("navSection")
        lbl.setStyleSheet(
            "font-family: 'Barlow Condensed'; font-size: 11px; font-weight: 600;"
            " background: transparent; padding: 6px 4px 2px;"
            f" color: rgba(255,255,255,{0.22 if faint else 0.32});")
        return lbl

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("railRule")
        line.setFixedHeight(1)
        return line

    def _licence_card(self) -> QWidget:
        """Plan, state, and one way to act on it. The design puts this at the
        foot of the rail so the answer to "what am I paying for" is always in
        the same place — it used to be four clicks into a dialog."""
        card = QFrame()
        card.setObjectName("railCard")
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(0)
        self._plan_title = QLabel(i18n.t("Licence"))
        self._plan_title.setObjectName("railCardTitle")
        col.addWidget(self._plan_title)
        self._plan_body = QLabel(i18n.t("Checking…"))
        self._plan_body.setObjectName("railCardBody")
        self._plan_body.setWordWrap(True)
        col.addWidget(self._plan_body)
        col.addSpacing(10)
        manage = QPushButton(i18n.t("Manage licence"))
        manage.setObjectName("railCardBtn")
        manage.setCursor(Qt.PointingHandCursor)
        manage.clicked.connect(lambda: self.command_triggered.emit("licence"))
        col.addWidget(manage)
        return card

    def _profile_row(self) -> QWidget:
        btn = QPushButton()
        btn.setObjectName("railProfile")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(i18n.t("Your role and workspace"))
        btn.clicked.connect(lambda: self.command_triggered.emit("team"))
        # A QPushButton does not grow its sizeHint for a layout put inside it,
        # so the second line was being clipped by the button's own text height.
        btn.setMinimumHeight(48)
        row = QHBoxLayout(btn)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(9)
        who = identity.describe() or i18n.t("This computer")
        row.addWidget(Avatar(who, 28))
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        name = QLabel(who)
        name.setObjectName("railProfileName")
        stack.addWidget(name)
        self._profile_role = QLabel(i18n.t("Signed in"))
        self._profile_role.setObjectName("railProfileRole")
        stack.addWidget(self._profile_role)
        row.addLayout(stack, stretch=1)
        chevron = QLabel()
        chevron.setPixmap(icons.pixmap("chevron-right", 13,
                                       theme.over(0.40)))
        row.addWidget(chevron)
        return btn

    def _build_direct_group(self) -> QWidget:
        """The settings shortcuts, collapsed behind one disclosure row.

        The design folds all of these into the Settings screen and shows none
        of them in the rail. They are kept because the screen is a place you
        navigate to and these are a place you jump to — but they stay closed by
        default, so the rail still reads as the design's four-item MORE group
        until someone asks for more.
        """
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        toggle = QPushButton(f"  {i18n.t('More settings')}")
        toggle.setObjectName("navSub")
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setFlat(True)
        toggle.setCheckable(True)
        toggle.setLayoutDirection(Qt.RightToLeft)   # chevron on the right
        icons.button_icon(toggle, "chevron-right", 15, theme.over(0.40))
        col.addWidget(toggle)

        body = QWidget()
        body_col = QVBoxLayout(body)
        body_col.setContentsMargins(0, 0, 0, 0)
        body_col.setSpacing(2)
        for key, label, icon_name, tip in DIRECT:
            btn = nav_button(i18n.t(label), icon_name, small=True,
                             tip=i18n.t(tip))
            btn.clicked.connect(
                lambda _=False, k=key: self.command_triggered.emit(k))
            body_col.addWidget(btn)
        body.setVisible(False)
        col.addWidget(body)

        def _on_toggled(open_: bool):
            icons.button_icon(toggle,
                              "chevron-down" if open_ else "chevron-right",
                              15, theme.over(0.40))
            body.setVisible(open_)
        toggle.toggled.connect(_on_toggled)
        self._configure_toggle = toggle
        return wrap

    def _mini(self, icon_name: str, tip: str, slot) -> QPushButton:
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(i18n.t(tip))
        btn.setFixedSize(24, 24)
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " border-radius: 6px; padding: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,0.09); }")
        icons.button_icon(btn, icon_name, 14, theme.over(0.45))
        btn.clicked.connect(slot)
        return btn

    # ── nav ───────────────────────────────────────────────────────────────
    def _go(self, key: str):
        self.set_current(key)
        self.command_triggered.emit(key)

    def set_current(self, key: str):
        if key in self._nav:
            self._current = key
            self._refresh_nav()

    def _refresh_nav(self):
        glyphs = {k: i for k, _, i in PRIMARY}
        glyphs.update({k: i for k, _, i, _t in MORE})
        for key, btn in self._nav.items():
            cur = key == self._current
            small = key != "home"
            btn.setProperty("cur", cur)
            if cur:
                ink = "#ffffff"
            else:
                ink = theme.over(0.40 if small else 0.55)
            icons.button_icon(btn, glyphs[key], 15 if small else 17, ink)
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
        for _, (row, label, icon_name, feature) in self._gated.items():
            unlocked = feature in features
            # The chip swaps to a padlock; the label stays put. Appending
            # "(locked)" would make the shelf read as a list of things you
            # can't have rather than a product line.
            row.set_muted(not unlocked, "" if unlocked else "lock")
            row.setProperty("locked", not unlocked)
            if not unlocked:
                row.setToolTip(i18n.t(
                    "{addon} isn't in your licence — click to find out "
                    "about it").format(addon=i18n.t(label)))
            row.style().unpolish(row)
            row.style().polish(row)

    def set_plan(self, title: str, detail: str):
        """Fill the rail's licence card. Called by the window whenever the
        licence state is recomputed, so the plan name and the banner can never
        disagree."""
        self._plan_title.setText(title)
        self._plan_body.setText(detail)

    def set_listening(self, on: bool):
        """Reflect wake-word state pushed back from the window (e.g. it
        refused to start because no API key is set)."""
        if self.wake_switch.isChecked() != on:
            self.wake_switch.blockSignals(True)
            self.wake_switch.setChecked(on)
            self.wake_switch.blockSignals(False)

    # ── favorites ─────────────────────────────────────────────────────────
    _FAV_ROW = 27
    _FAV_MAX = 5

    def _size_favorites(self, count: int):
        """Pin the list to exactly the rows it holds, up to five. Past that it
        scrolls itself rather than pushing the rest of the rail down."""
        rows = max(1, min(count, self._FAV_MAX))
        self.fav_list.setFixedHeight(rows * self._FAV_ROW + 6)

    def reload_favorites(self):
        self.fav_list.clear()
        items = FAV.load()
        self._size_favorites(len(items))
        if not items:
            placeholder = QListWidgetItem(i18n.t("No favorites yet"))
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setToolTip("Click + above to favorite a file or folder")
            self.fav_list.addItem(placeholder)
            return
        for item in items:
            name = "folder" if item["kind"] == "folder" else "file"
            li = QListWidgetItem(
                icons.icon(name, 15, theme.over(0.45)), item["label"])
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
