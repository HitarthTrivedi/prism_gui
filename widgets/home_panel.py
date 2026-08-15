"""Home — the dashboard the redesign introduces.

Prism used to open straight onto an empty composer. That is the right screen
for someone who already knows what they want to type, and the wrong one for
everybody else: it answers "what do I do now" with a blank box, and says
nothing about what the app has already done for you.

So Home now leads with a hero that asks the question in words, backs it with
quick-starts into the three add-ons, and then reports: what is running, what
the week looked like, what finished recently, and which add-ons you own.

Every figure on this screen comes out of dashboard_data, which reads the real
run records and the real inquiry register. Where a store is empty the card says
so plainly instead of showing a zero that looks like data.
"""
from __future__ import annotations
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import dashboard_data as DATA
import i18n
import identity
import theme
from widgets import icons
from widgets.controls import (
    Avatar, Card, IconPad, Pill, ProgressBar, Sparkline, ToolBadge, elevate,
    kicker, track,
)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return i18n.t("Good morning")
    if hour < 17:
        return i18n.t("Good afternoon")
    return i18n.t("Good evening")


def _label(text: str, role: str = "", size: int = 0, colour: str = "",
           weight: int = 0, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    bits = []
    if size:
        bits.append(f"font-size: {size}px;")
    if colour:
        bits.append(f"color: {colour};")
    if weight:
        bits.append(f"font-weight: {weight};")
    if bits:
        lbl.setStyleSheet(" ".join(bits) + " background: transparent;")
    lbl.setWordWrap(wrap)
    return lbl


class ActiveRunCard(Card):
    """One in-flight task: its name, the tools it will pass through, how far
    along it is, and what is happening right now.

    The tool row is the point of this card. A progress bar alone says "wait";
    the chain of badges says *what is being waited on*, which is the difference
    between a customer trusting the run and killing it at 40%.
    """

    opened = Signal()

    def __init__(self, title: str, stages: list[tuple[str, str]],
                 fraction: float, note: str, started: str,
                 hue: str = None, parent=None):
        super().__init__(parent=parent)
        hue = hue or theme.WARN
        col = self.body((18, 16, 18, 16), spacing=0)

        head = QHBoxLayout()
        head.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: {hue}; border-radius: 3px;")
        head.addWidget(dot)
        head.addWidget(_label(title, size=14, weight=600), stretch=1)
        col.addLayout(head)
        col.addSpacing(12)

        # tool chain — badge over caption, chevrons between
        chain = QHBoxLayout()
        chain.setSpacing(5)
        chain.setAlignment(Qt.AlignLeft)
        for i, (tool, caption) in enumerate(stages):
            if i:
                sep = QLabel()
                sep.setPixmap(icons.pixmap("chevron-right", 10,
                                           theme.NEUTRAL[300], stroke=3))
                sep.setAlignment(Qt.AlignTop)
                sep.setContentsMargins(0, 11, 0, 0)
                chain.addWidget(sep)
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cell.setAlignment(Qt.AlignHCenter)
            badge = ToolBadge(tool, 34, radius=9)
            # On this card the badge is a soft tinted pad rather than a solid
            # fill — three saturated squares in a row out-shouted the task
            # name, which is the thing you are actually scanning for.
            badge.setStyleSheet(
                f"background: {theme.tint(theme.badge_color(tool))};"
                f" color: {theme.badge_color(tool)};"
                f" border: 1px solid {theme.tint(theme.badge_color(tool), '40')};"
                f" border-radius: 9px; font-family: '{theme.FONT_HEADING}';"
                f" font-weight: 700; font-size: 13px;")
            cell.addWidget(badge, alignment=Qt.AlignHCenter)
            cell.addWidget(_label(caption, size=9, colour=theme.NEUTRAL[400]),
                           alignment=Qt.AlignHCenter)
            chain.addLayout(cell)
        col.addLayout(chain)
        col.addSpacing(12)

        col.addWidget(ProgressBar(fraction, hue))
        col.addSpacing(8)
        col.addWidget(_label(note, size=12, colour=theme.NEUTRAL[500], wrap=True))
        col.addSpacing(12)

        foot = QHBoxLayout()
        foot.addWidget(_label(started, "faint"), stretch=1)
        open_btn = QPushButton(i18n.t("Open →"))
        open_btn.setObjectName("smallBtn")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(self.opened.emit)
        foot.addWidget(open_btn)
        col.addLayout(foot)


class StatCard(Card):
    """A figure, what it counts, and a sparkline of how it got there."""

    def __init__(self, icon_name: str, hue: str, value: str, caption: str,
                 qualifier: str = "", series: list = None, parent=None):
        super().__init__(parent=parent)
        col = self.body((18, 16, 18, 16), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconPad(icon_name, hue, 30, 8, 15))
        head.addStretch(1)
        if series:
            head.addWidget(Sparkline(series, hue))
        col.addLayout(head)
        col.addSpacing(10)
        col.addWidget(_label(value, "stat"))
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(_label(caption, size=12.5, colour=theme.NEUTRAL[700]))
        if qualifier:
            row.addWidget(_label(qualifier, size=12.5, colour=theme.NEUTRAL[400]))
        row.addStretch(1)
        col.addSpacing(2)
        col.addLayout(row)


class HomePanel(QScrollArea):
    """The dashboard. Rebuilt wholesale by refresh() rather than mutated —
    it is a read-only report over two stores, it is rebuilt only on navigation
    or when a run finishes, and a rebuild is far easier to keep correct than a
    dozen setText() paths that each have to remember the empty case."""

    describe_task = Signal()
    open_addon = Signal(str)
    open_history = Signal()
    open_run = Signal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._active: list[dict] = []
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        # 28px right so a card's drop shadow has somewhere to fall instead of
        # being clipped by the scroll viewport.
        self._col.setContentsMargins(40, 32, 40, 32)
        self._col.setSpacing(24)
        self.refresh()

    # ── live run state, pushed in by the window ──────────────────────────
    def set_active(self, runs: list[dict]):
        """`runs` is [{title, stages, fraction, note, started}]. Empty clears
        the section — Home must not keep showing a run that has finished."""
        self._active = list(runs or [])
        self.refresh()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self):
        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

        self._col.addLayout(self._header())
        self._col.addWidget(self._hero())
        if self._active:
            self._col.addLayout(self._active_runs())
        self._col.addLayout(self._stats())
        self._col.addLayout(self._bottom())
        self._col.addStretch(1)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    # ── sections ──────────────────────────────────────────────────────────
    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(20)
        who = (identity.current().get("name") or "").split(" ")[0]
        left = QVBoxLayout()
        left.setSpacing(2)
        title = _label(f"{_greeting()}, {who} 👋" if who else _greeting(), "h1")
        left.addWidget(track(title, -0.015))
        left.addWidget(_label(i18n.t("Here's where things stand."), size=13,
                              colour=theme.NEUTRAL[600]))
        row.addLayout(left)
        row.addStretch(1)

        # Search is a real destination, not decoration: it opens History,
        # which is where every past run can be found. Showing a search field
        # that does nothing would be worse than showing none.
        search = QPushButton()
        search.setObjectName("iconBtn")
        search.setToolTip(i18n.t("Find a past run"))
        search.setCursor(Qt.PointingHandCursor)
        icons.button_icon(search, "search", 16, theme.NEUTRAL[500])
        search.clicked.connect(self.open_history.emit)
        row.addWidget(search)

        # Only when this copy actually belongs to a named person. A "?" avatar
        # on a solo install identifies nobody and reads as a broken image —
        # the design's avatar is there to disambiguate between colleagues, so
        # with no colleagues there is nothing for it to say.
        who = identity.describe()
        if who:
            badge = Avatar(who, 34)
            badge.setToolTip(who)
            row.addWidget(badge)
        return row

    def _hero(self) -> QWidget:
        card = Card(stripe=True, radius=theme.R_HERO, raised=True)
        col = card.body((28, 26, 28, 26), spacing=0)

        head = QHBoxLayout()
        kick = kicker(i18n.t("New task"))
        head.addWidget(kick)
        head.addStretch(1)
        head.addWidget(Pill(i18n.t("Waiting on you"), "neutral"))
        col.addLayout(head)
        col.addSpacing(12)

        col.addWidget(_label(i18n.t("What do you need done today?"), "h3"))
        col.addSpacing(8)
        lead = _label(i18n.t("Describe what you want done — name any file or "
                             "folder in plain words and Prism will go find it."),
                      "lead", wrap=True)
        lead.setMaximumWidth(640)
        col.addWidget(lead)
        col.addSpacing(18)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for key, text in (("inquiry", i18n.t("Read today's inbox")),
                          ("boq", i18n.t("Take a BOQ off a drawing")),
                          ("email", i18n.t("Draft an email"))):
            chip = QPushButton(text)
            chip.setObjectName("chipBtn")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self.open_addon.emit(k))
            chips.addWidget(chip)
        chips.addStretch(1)
        col.addLayout(chips)
        col.addSpacing(20)

        go = QPushButton(f"{i18n.t('Describe a task')}  ")
        go.setObjectName("primaryBtn")
        go.setCursor(Qt.PointingHandCursor)
        # RightToLeft puts the arrow after the label instead of before it.
        # It also mirrors the alignment QBoxLayout would apply, which pinned
        # the button to the right edge of the hero — so the button goes in its
        # own left-to-right row with the stretch doing the aligning.
        go.setLayoutDirection(Qt.RightToLeft)
        icons.button_icon(go, "arrow-right", 16, "#ffffff")
        go.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        go.clicked.connect(self.describe_task.emit)
        elevate(go, theme.SHADOW_ACCENT, theme.ACCENT)
        go_row = QHBoxLayout()
        go_row.setContentsMargins(0, 0, 0, 0)
        go_row.addWidget(go)
        go_row.addStretch(1)
        col.addLayout(go_row)
        return card

    def _active_runs(self) -> QVBoxLayout:
        wrap = QVBoxLayout()
        wrap.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(_label(i18n.t("Active runs"), "h5"), stretch=1)
        link = QPushButton(i18n.t("View all →"))
        link.setObjectName("linkBtn")
        link.setCursor(Qt.PointingHandCursor)
        link.clicked.connect(self.open_history.emit)
        head.addWidget(link)
        wrap.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(16)
        for run in self._active:
            card = ActiveRunCard(
                run.get("title", ""), run.get("stages", []),
                run.get("fraction", 0.0), run.get("note", ""),
                run.get("started", ""), run.get("hue"))
            card.opened.connect(self.open_run.emit)
            row.addWidget(card)
        if len(self._active) == 1:
            row.addStretch(1)           # one run must not stretch to full width
        wrap.addLayout(row)
        return wrap

    def _stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        series = DATA.runs_per_day(self.cfg)
        done, failed = DATA.run_counts(self.cfg)
        stats = DATA.inquiry_stats(self.cfg)

        if stats:
            inq = DATA.inquiries_per_day(self.cfg)
            row.addWidget(StatCard(
                "inbox", theme.OK, str(stats["logged_week"]),
                i18n.t("Inquiries logged"), i18n.t("· this week"), inq))
            row.addWidget(StatCard(
                "file", theme.ACCENT, stats["quoted_value"],
                i18n.t("Quoted"), i18n.t("· this month")))
        else:
            # No register yet. Rather than two zeroed cards pretending to be a
            # sales dashboard, the space goes to what this copy *has* done.
            row.addWidget(StatCard(
                "check", theme.OK, str(done), i18n.t("Tasks finished"),
                i18n.t("· this week"), series))
            row.addWidget(StatCard(
                "alert", theme.ERR if failed else theme.NEUTRAL[400],
                str(failed), i18n.t("Didn't finish"), i18n.t("· this week")))
        row.addWidget(StatCard(
            "clock", theme.WARN, str(sum(series)), i18n.t("Runs started"),
            i18n.t("· this week"), series))
        return row

    def _bottom(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(20)
        row.addWidget(self._recent(), stretch=16)
        row.addWidget(self._addons(), stretch=10)
        return row

    def _recent(self) -> QWidget:
        card = Card()
        col = card.body((22, 20, 22, 20), spacing=0)
        head = QHBoxLayout()
        head.addWidget(_label(i18n.t("Recent activity"), "h5"), stretch=1)
        link = QPushButton(i18n.t("See all in History →"))
        link.setObjectName("linkBtn")
        link.setCursor(Qt.PointingHandCursor)
        link.clicked.connect(self.open_history.emit)
        head.addWidget(link)
        col.addLayout(head)
        col.addSpacing(6)

        runs = DATA.recent_runs(self.cfg, 4)
        if not runs:
            empty = _label(i18n.t("Nothing yet. Once Prism finishes a task, "
                                  "it turns up here."), "emptyState", wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            col.addWidget(empty)
            return card

        for i, run in enumerate(runs):
            if i:
                line = QFrame()
                line.setObjectName("cardLine")
                line.setFixedHeight(1)
                col.addWidget(line)
            col.addWidget(self._recent_row(run))
        return card

    def _recent_row(self, run: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(6, 10, 6, 10)
        row.setSpacing(12)
        ok = run.get("ok", True)
        row.addWidget(IconPad("check" if ok else "alert",
                              theme.ACCENT if ok else theme.ERR, 34, 9, 17))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        title = _label(run["title"], size=14, weight=500)
        title.setToolTip(run["title"])
        stack.addWidget(title)
        tools = " · ".join(run["tools"]) if run["tools"] else i18n.t("No tool recorded")
        stack.addWidget(_label(f"{tools} · {run['when']}", "faint"))
        row.addLayout(stack, stretch=1)
        row.addWidget(Pill(i18n.t("Done") if ok else i18n.t("Failed"),
                           "accent" if ok else "err"))
        return wrap

    def _addons(self) -> QWidget:
        card = Card()
        col = card.body((22, 20, 22, 20), spacing=0)
        col.addWidget(_label(i18n.t("Your add-ons"), "h5"))
        col.addSpacing(8)
        stats = DATA.inquiry_stats(self.cfg)
        waiting = f"{stats['waiting']} waiting" if stats and stats["waiting"] else ""
        for key, label, desc, icon_name, hue, badge in (
            ("inquiry", i18n.t("Inquiry Automation"), i18n.t("Register, quote, chase"),
             "inbox", theme.OK, waiting),
            ("boq", i18n.t("BOQ"), i18n.t("Quantities off a drawing"),
             "file", theme.ACCENT, ""),
            ("email", i18n.t("Email"), i18n.t("Draft & send, your account"),
             "mail", theme.WARN, ""),
            ("bom", i18n.t("BOM & Stock"), i18n.t("Coming soon"),
             "list", theme.NEUTRAL[400], ""),
        ):
            col.addWidget(self._addon_row(key, label, desc, icon_name, hue, badge))
        return card

    def _addon_row(self, key, label, desc, icon_name, hue, badge) -> QWidget:
        soon = key == "bom"
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        if not soon:
            wrap.setCursor(Qt.PointingHandCursor)
            wrap.mousePressEvent = lambda _e, k=key: self.open_addon.emit(k)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(6, 9, 6, 9)
        row.setSpacing(12)
        row.addWidget(IconPad(icon_name, hue, 32, 9, 16))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        ink = theme.NEUTRAL[400] if soon else theme.TEXT
        stack.addWidget(_label(label, size=13, weight=500, colour=ink))
        stack.addWidget(_label(desc, size=11.5, colour=theme.NEUTRAL[400]))
        row.addLayout(stack, stretch=1)
        if badge:
            row.addWidget(Pill(badge, "neutral"))
        return wrap
