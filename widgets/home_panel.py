"""Home — the command centre Prism opens on.

Prism used to open straight onto an empty composer. That is the right screen
for someone who already knows what they want to type, and the wrong one for
everybody else: it answers "what do I do now" with a blank box, and says
nothing about what the app has already done for you.

So Home is a report, and it answers six questions in order:

    what can I do      the hero, with the one primary action on the screen
    what is running    the active-run section, pushed in live by the window
    how did it go      four figures over the runs this workspace actually has
    what happened      recent activity, then the add-ons you own
    what is connected  which tool each pipeline stage is set up to drive
    how do I start     "Describe a task", and three quick-starts beside it

Every figure comes out of dashboard_data, which reads the real run records and
the real inquiry register. Where a store is empty the card says so plainly
instead of showing a zero that looks like data.

Two things this file is deliberately careful about, because both have bitten:

**Nothing here may report its full text width as its minimum.** A plain QLabel
does, and one 143-character run title (there is a real one in the shipped
data) dragged Home's inner widget out to 1391px inside a 1200px viewport — so
the third figure and the whole add-ons column were clipped off the right edge
of the window, with the horizontal scrollbar switched off to hide it. Worse,
it came and went with whatever happened to be in the runs folder that hour, so
it looked like an intermittent fault rather than a missing `elidedText` call.
Anything that renders user data on this screen goes through `_Elided`.

**A "failed" run and a run that never started are different events.** 86 of the
102 records in the shipped workspace have no query, no tools and
`"error": "Chrome would not launch"` — they are the same environment fault
recorded 86 times, not 86 failed jobs. Rendering four of them as "Untitled task
· Failed" makes the product look broken and buries the one run that did work.
They are counted and named separately here, never hidden. See `_split()`.
"""
from __future__ import annotations
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import dashboard_data as DATA
import i18n
import identity
import theme
from widgets import controls as C
from widgets import icons

# How many run records Home reads per refresh. The figures are honest about
# their own scope ("of your last 102 runs") rather than pretending to be a
# lifetime total, and the bound is what keeps a workspace with five thousand
# runs on a shared drive from costing five thousand file opens.
#
# 120 and not 40, which was the first guess: the shipped workspace opens with
# 87 consecutive records that never reached a tool, so a 40-record window sat
# entirely inside them and reported "0 completed" to somebody with 15
# successful runs. A window has to be wide enough to clear the longest run of
# one outcome or it is not measuring anything. 102 records costs ~32ms here,
# and this is read on refresh() only — never on set_active(), which is the
# call that runs nine times per job.
RUN_WINDOW = 120

# The number of recent runs listed. Five is what fits beside the two narrower
# columns without either of them stretching to fill.
RECENT_SHOWN = 5

# Stages shown in an active run's tool chain before it collapses to a count.
# A nine-stage plan drawn in full is 800px of badges, which is wider than the
# card at 1280 — and the last four are not the ones you are waiting on.
CHAIN_SHOWN = 6

# The add-on shelf, in the rail's order. A module-level copy table so
# devtools/extract_strings.py finds the labels — the name `ADDONS` is in its
# COPY_TABLES set, and matches widgets/sidebar.ADDONS, which is the list this
# one must never drift from.
#
# `hue=None` means "the accent", resolved at build time rather than here: this
# module is imported before theme.apply_role() runs, so an accent frozen into
# the table would stay Prism blue in a green profile while everything around
# it rotated.
ADDONS = [
    ("inquiry", "Email automation", "Register, quote, chase", "inbox", theme.OK),
    ("boq", "BOQ", "Quantities off a drawing", "file", None),
    ("gerber", "Gerber", "Measured off the Gerber files", "grid", None),
    ("email", "Email", "Draft & send, your account", "mail", theme.WARN),
    ("reel", "Reel / Studio", "A short video from a task", "video", None),
    ("motion", "Motion Graphics", "A scene-graph video with camera, charts & diagrams", "video", None),
    # Shown but disabled, exactly as the rail shows it: the shelf should read
    # as a product line, and a visible "next one" beats an empty gap.
    ("bom", "BOM & Stock", "Coming soon", "list", theme.NEUTRAL[400]),
]

def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return i18n.t("Good morning")
    if hour < 17:
        return i18n.t("Good afternoon")
    return i18n.t("Good evening")


def _never_started(run: dict) -> bool:
    """True for a record that has no query AND no tools.

    Such a run never reached a tool. In the shipped workspace every one of
    them carries "Chrome would not launch" — they are one environment fault
    recorded 86 times, not 86 jobs that ran and went wrong. Counting them as
    failures turns a working install into a 96%-failure dashboard, and listing
    four of them as "Untitled task · Failed" pushes the runs that did work off
    the bottom of the card.

    Nothing is discarded on the strength of this: the count is shown, named for
    what it is, and History still lists every record in full.

    "Untitled task" is the literal dashboard_data.recent_runs() substitutes for
    an empty query — a plain Python string, never passed through i18n — so this
    compares against data and never against a translated label.
    """
    return (not run.get("ok", True)
            and not run.get("tools")
            and (run.get("title") or "").strip() in ("", "Untitled task"))


def _split(runs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(finished, failed, never-started) out of one window of run records."""
    done, failed, stalled = [], [], []
    for run in runs:
        if run.get("ok", True):
            done.append(run)
        elif _never_started(run):
            stalled.append(run)
        else:
            failed.append(run)
    return done, failed, stalled


class _Elided(QLabel):
    """A one-line label that shrinks to nothing rather than widening the page.

    This is the fix for Home's horizontal overflow. A QLabel reports the full
    width of its text as its minimum size, and a QScrollArea with
    `widgetResizable` honours that minimum even with the horizontal scrollbar
    switched off — so a single long run title silently pushed 191px of the
    dashboard past the right edge of the window, where there was no way to
    scroll to it and no clue it was there.

    Two changes make that impossible: an `Ignored` horizontal size policy, so
    the label asks the layout for nothing at all, and an elide on resize, so
    what it can no longer fit ends in an ellipsis instead of being clipped.
    The full text stays in the tooltip.

    Whitespace is collapsed first — a run title can contain newlines (there is
    a real "hello\\nwassup" in the shipped data), and a two-line row in a list
    of one-line rows reads as a rendering fault.
    """

    def __init__(self, text: str, level: str = "BODY", colour: str = "",
                 weight: int = 0, parent=None):
        super().__init__(parent)
        self._full = " ".join((text or "").split())
        css = theme.type_css(level, colour) + " background: transparent;"
        if weight:
            css += f" font-weight: {weight};"
        self.setStyleSheet(css)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(self._full)
        # Read the text back rather than trusting what was passed in. i18n
        # patches QLabel.setText, so a catalogue string handed here in English
        # is on screen in Hindi a moment later — and elidedText() run against
        # the English original would then quietly put English back the first
        # time the row resized. Whatever actually landed is what gets elided.
        self._full = self.text()
        if self._full:
            self.setToolTip(self._full)

    def text_value(self) -> str:
        """The untruncated string, for an accessible name."""
        return self._full

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = QFontMetrics(self.font())
        # The width is fixed by the layout (the policy is Ignored), so setting
        # a shorter text here cannot feed back into another resize.
        self.setText(metrics.elidedText(self._full, Qt.ElideRight,
                                        max(16, self.width())))


class _Row(QFrame):
    """A flat, hoverable row inside a card that can be activated.

    Home had two of these and neither was reachable from the keyboard — the
    add-on rows worked by reassigning `mousePressEvent` on a bare QFrame, which
    gives a mouse user a click target and everyone else nothing. This one is a
    tab stop, takes Return and Space, and draws a focus ring.
    """

    clicked = Signal()

    def __init__(self, enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._live = enabled
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.TabFocus)
            # The app stylesheet gives #rowFlat no border and no focus state.
            # A transparent border in the resting rule keeps the row from
            # jumping by a pixel when the ring appears.
            self.setStyleSheet(
                f"#rowFlat {{ border: 1px solid transparent; }}"
                f"#rowFlat:focus {{ border-color: {theme.ACCENT};"
                f" background: {theme.WELL}; }}")
        # Ten clear of the 28px floor, not sixteen: three columns of these rows
        # is what sets Home's total height, and four pixels a row was the
        # difference between the page fitting a 900px window and scrolling.
        self.setMinimumHeight(C.MIN_TARGET + 10)

    def mousePressEvent(self, event):
        if self._live:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self._live and event.key() in (Qt.Key_Return, Qt.Key_Enter,
                                          Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class ActiveRunCard(C.Card):
    """One in-flight task: its state, the tools it will pass through, how far
    along it is, and what is happening right now.

    Kept as a local Card subclass rather than folded into controls.py: nothing
    there composes a tool chain, and the chain is the point of this card. A
    progress bar alone says "wait"; the row of badges says *what is being
    waited on*, which is the difference between a customer trusting the run and
    killing it at 40%.

    The hand-rolled status dot it used to lead with is gone — the head row
    carries a real `StatusBadge`, so a run in flight says "RUNNING" here in the
    same words, colour and dot it uses on the run screen and in History.
    """

    opened = Signal()

    def __init__(self, title: str, stages: list[tuple[str, str]],
                 fraction: float, note: str, started: str,
                 hue: str = None, parent=None):
        super().__init__(parent=parent)
        hue = hue or theme.WARN
        col = self.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.StatusBadge("running", focusable=False))
        head.addWidget(_Elided(title, "CARD_TITLE"), stretch=1)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_3)

        col.addLayout(self._chain(stages))
        col.addSpacing(theme.SPACE_3)

        col.addWidget(C.ProgressBar(fraction, hue))
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(note, level="META", wrap=True))
        col.addSpacing(theme.SPACE_3)

        foot = QHBoxLayout()
        foot.setSpacing(theme.SPACE_2)
        foot.addWidget(C.label(started, role="faint"), stretch=1)
        open_btn = C.button(i18n.t("Open"), "secondary", "arrow-right",
                            small=True, on_click=self.opened.emit)
        foot.addWidget(open_btn)
        col.addLayout(foot)

    def _chain(self, stages: list[tuple[str, str]]) -> QHBoxLayout:
        """Badge over caption, chevrons between — capped so it cannot widen
        the page. Every caption cell is a fixed width and elides inside it, so
        a long stage name costs an ellipsis and never a clipped column."""
        chain = QHBoxLayout()
        chain.setSpacing(theme.SPACE_1 + 1)
        chain.setAlignment(Qt.AlignLeft)
        shown = list(stages)[:CHAIN_SHOWN]
        for i, (tool, caption) in enumerate(shown):
            if i:
                sep = QLabel()
                sep.setPixmap(icons.pixmap("chevron-right", 10,
                                           theme.NEUTRAL[300], stroke=3))
                sep.setAlignment(Qt.AlignTop)
                sep.setContentsMargins(0, 11, 0, 0)
                chain.addWidget(sep)
            cell = QVBoxLayout()
            cell.setSpacing(theme.SPACE_1)
            cell.setAlignment(Qt.AlignHCenter)
            badge = C.ToolBadge(tool, 34, radius=theme.R_CONTROL)
            # On this card the badge is a soft tinted pad rather than a solid
            # fill — three saturated squares in a row out-shouted the task
            # name, which is the thing you are actually scanning for.
            badge.setStyleSheet(
                f"background: {theme.tint(theme.badge_color(tool))};"
                f" color: {theme.badge_color(tool)};"
                f" border: 1px solid {theme.tint(theme.badge_color(tool), '40')};"
                f" border-radius: {theme.R_CONTROL}px;"
                f" font-family: '{theme.FONT_HEADING}';"
                f" font-weight: 700; font-size: 13px;")
            badge.setToolTip(f"{tool} — {caption}")
            cell.addWidget(badge, alignment=Qt.AlignHCenter)
            cap = _Elided(caption, "LABEL", theme.NEUTRAL[500])
            cap.setFixedWidth(74)
            cap.setAlignment(Qt.AlignHCenter)
            cell.addWidget(cap, alignment=Qt.AlignHCenter)
            chain.addLayout(cell)
        if len(stages) > CHAIN_SHOWN:
            more = C.Pill(i18n.t("+{n} more").format(n=len(stages) - CHAIN_SHOWN),
                          "quiet")
            more.setToolTip(" · ".join(t for t, _c in stages[CHAIN_SHOWN:]))
            chain.addWidget(more, alignment=Qt.AlignVCenter)
        chain.addStretch(1)
        return chain


class HomePanel(QWidget):
    """The dashboard. Rebuilt wholesale by refresh() rather than mutated — it
    is a read-only report over two stores, and a rebuild is far easier to keep
    correct than a dozen setText() paths that each have to remember the empty
    case.

    With ONE exception, and it is the reason the run section has its own host
    widget. refresh() costs a read of the register CSV plus a walk of the runs
    folder, and on a company install both live on a shared drive. set_active()
    is called from the window on every `stage_started`, so a nine-stage run was
    paying that whole cost nine times — synchronously, on the UI thread. That
    is the "it freezes for a few seconds every time it moves to the next step"
    report, and it is worst over VPN or a Drive-for-Desktop mount where a
    blocked stat is not interruptible. A run in flight changes one card, so
    set_active() repaints one card and touches neither store.

    The screen is a fixed PageHeader over a scrolling body, which is the
    standard page scaffold: the greeting and the way out to History stay put
    while the report scrolls under them.
    """

    describe_task = Signal()
    open_addon = Signal(str)        # any command the window's router accepts
    open_history = Signal()
    open_run = Signal()
    open_run_record = Signal(str)   # path of a saved run record — NEEDS WIRING

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._active: list[dict] = []
        self._rows: list[dict] = []     # register, read once per refresh()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = C.PageHeader(
            "", i18n.t("Here's where things stand."),
            [C.button(i18n.t("Search history"), "secondary", "search",
                      on_click=self.open_history.emit)])
        # The avatar is built once and hidden rather than skipped, so a rename
        # can bring it back without rebuilding the band. It shows only when
        # this copy actually belongs to a named person: a "?" avatar on a solo
        # install identifies nobody and reads as a broken image — it is there
        # to disambiguate between colleagues, and with no colleagues there is
        # nothing for it to say.
        self._avatar = C.Avatar("", 34)
        self._header.add_action(self._avatar)
        # The standard band is padded for a one-line page title; Home's is a
        # two-line greeting, and 20/16 around it left 45 rows of bare canvas
        # above the fold — every empty row on this screen, and a fifth of the
        # band itself. Tightened here rather than in controls.py, because the
        # other ten screens do carry a single title and are right as they are.
        self._header.layout().setContentsMargins(
            theme.PAGE_PAD, theme.SPACE_3 + 2, theme.PAGE_PAD, theme.SPACE_3)
        root.addWidget(self._header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._scroll.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.PAGE_PAD,
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        root.addWidget(self._scroll, stretch=1)

        # Owns the active-run section and outlives every refresh(), so
        # set_active() can repaint it without rebuilding the dashboard around
        # it. Built before the first refresh() because refresh() adds it.
        self._active_host = QWidget()
        _slot = QVBoxLayout(self._active_host)
        _slot.setContentsMargins(0, 0, 0, 0)
        self.refresh()

    # ── live run state, pushed in by the window ──────────────────────────
    def set_active(self, runs: list[dict]):
        """`runs` is [{title, stages, fraction, note, started}]. Empty clears
        the section — Home must not keep showing a run that has finished.

        Repaints ONLY the run card. Called on every stage of every run, so it
        must not touch the register or the runs folder — see the class
        docstring for what it used to cost.
        """
        self._active = list(runs or [])
        self._fill_active()

    def _fill_active(self):
        """Rebuild the run section alone, from state already in memory."""
        slot = self._active_host.layout()
        while slot.count():
            item = slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())
        if self._active:
            slot.addLayout(self._active_runs())
        # Hidden rather than absent, so the section carries no spacing of its
        # own when there is no run — the host is always in the column.
        self._active_host.setVisible(bool(self._active))

    # ── build ─────────────────────────────────────────────────────────────
    def _refresh_header(self):
        """The greeting and the avatar, re-read from identity.

        The band is fixed and outlives refresh(), so this has to be explicit:
        MainWindow._ask_display_name() calls refresh() precisely so that the
        name someone has just typed appears here, and a header built only in
        __init__ would keep greeting the old one until the app restarted.
        """
        who = (identity.display_name(self.cfg) or "").split(" ")[0]
        self._header.title.setText(
            f"{_greeting()}, {who} 👋" if who else _greeting())
        whole = identity.describe()
        self._avatar.setText((whole or "?").strip()[:1].upper())
        self._avatar.setToolTip(whole)
        self._avatar.setAccessibleName(whole)
        self._avatar.setVisible(bool(whole))

    def refresh(self):
        self._refresh_header()
        while self._col.count():
            item = self._col.takeAt(0)
            widget = item.widget()
            if widget is self._active_host:
                # Hidden first so setParent(None) can't flash it as a
                # top-level window; _fill_active() re-asserts visibility
                # right after the host is re-added below.
                widget.hide()
                widget.setParent(None)      # persistent — re-added below
            elif widget:
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

        # ONE read of each store, threaded through everything below. _stats()
        # called inquiry_stats() and inquiries_per_day() without rows, and
        # _addons() called inquiry_stats() again — three full reads of a CSV
        # that on a company install sits on a shared drive, for one screen.
        # The runs folder is now read once too, and the window is split into
        # its three outcomes for both the figures and the activity list.
        self._rows = DATA.register_rows(self.cfg)
        runs = DATA.recent_runs(self.cfg, RUN_WINDOW)
        done, failed, stalled = _split(runs)

        self._col.addWidget(self._hero())
        self._col.addWidget(self._active_host)
        self._fill_active()
        metrics = self._metrics(runs, done, failed, stalled)
        if metrics is not None:
            self._col.addWidget(metrics)
        # stretch=1, and nothing after it. The bottom row is three columns of
        # cards; handed the leftover height they grow into it, which is what
        # keeps Home from finishing in a band of bare canvas.
        self._col.addLayout(self._bottom(runs, stalled), stretch=1)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    # ── sections ──────────────────────────────────────────────────────────
    def _hero(self) -> QWidget:
        """The one primary action on the screen, and the three jobs that get
        done every day, in the width of one card."""
        card = C.Card(stripe=True, raised=True)
        col = card.body((theme.SPACE_6, theme.SPACE_5,
                         theme.SPACE_6, theme.SPACE_5), spacing=0)

        col.addWidget(C.kicker(i18n.t("New task")))
        col.addSpacing(theme.SPACE_2)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_5)
        title = C.heading(i18n.t("What do you need done today?"), 3)
        title.setWordWrap(True)
        head.addWidget(title, stretch=1)
        go = C.button(i18n.t("Describe a task"), "primary", "arrow-right",
                      on_click=self.describe_task.emit)
        go.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        C.elevate(go, theme.SHADOW_ACCENT, theme.ACCENT)
        head.addWidget(go, alignment=Qt.AlignTop)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_1)

        lead = C.label(i18n.t("Describe what you want done — name any file or "
                              "folder in plain words and Prism will go find "
                              "it."), level="SUPPORT", wrap=True)
        lead.setMaximumWidth(640)
        col.addWidget(lead)
        col.addSpacing(theme.SPACE_4)

        # Literal inside the t() call, not lifted into a table: the three
        # quick-starts are the only copy on this screen the extractor reads
        # straight off the call site, and a key it cannot see never reaches a
        # translator.
        chips = QHBoxLayout()
        chips.setSpacing(theme.SPACE_2)
        for key, text in (("inquiry", i18n.t("Read today's inbox")),
                          ("boq", i18n.t("Take a BOQ off a drawing")),
                          ("email", i18n.t("Draft an email"))):
            chip = C.button(text, "secondary")
            chip.setObjectName("chipBtn")
            chip.clicked.connect(
                lambda _=False, k=key: self.open_addon.emit(k))
            chips.addWidget(chip)
        chips.addStretch(1)
        col.addLayout(chips)
        return card

    def _active_runs(self) -> QVBoxLayout:
        wrap = QVBoxLayout()
        wrap.setSpacing(theme.SPACE_3)
        wrap.addWidget(C.SectionHeader(
            i18n.t("Active runs"), "",
            [C.button(i18n.t("View all"), "link",
                      on_click=self.open_history.emit)]))

        row = QHBoxLayout()
        row.setSpacing(theme.CARD_GAP)
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

    def _metrics(self, runs, done, failed, stalled) -> QWidget | None:
        """Four figures, or six once the inquiry register exists.

        Returns None on a workspace with no runs at all. Four cards reading
        zero is the "wall of zeroes" this whole dashboard is written to avoid —
        no runs and no successful runs are very different facts, and the
        Recent activity card says the first one in words.
        """
        stats = DATA.inquiry_stats(self.cfg, self._rows)
        if not runs and not stats:
            return None

        cards = []
        if runs:
            week = DATA.runs_per_day(self.cfg, 7)
            scope = i18n.t("of your last {n} runs").format(n=len(runs))
            cards += [
                # "Started this week", not "Started". The other three cards
                # partition the same window and visibly add up to it; this one
                # counts a different window entirely, and titled just
                # "Started" it read as a contradiction at a glance — "0
                # started" sitting beside "15 completed". The window belongs
                # in the title, where the eye lands, not only in the scope
                # line underneath the number.
                C.MetricCard(i18n.t("Started this week"), str(sum(week)),
                             i18n.t("last 7 days"), "clock", week, theme.ACCENT),
                C.MetricCard(i18n.t("Completed"), str(len(done)), scope,
                             "check", None, theme.OK),
                C.MetricCard(i18n.t("Failed"), str(len(failed)), scope,
                             "alert", None,
                             theme.ERR if failed else theme.NEUTRAL[400]),
                # Same scope line as the two above it, on purpose: the three
                # numbers then visibly add up to the window, which is what
                # stops "Never started 87" reading as a glitch.
                C.MetricCard(i18n.t("Never started"), str(len(stalled)), scope,
                             "x", None,
                             theme.WARN if stalled else theme.NEUTRAL[400]),
            ]
            cards[-1].setToolTip(i18n.t("These runs stopped before any tool "
                                        "was reached."))
        if stats:
            cards += [
                C.MetricCard(i18n.t("Inquiries logged"),
                             str(stats["logged_week"]), i18n.t("this week"),
                             "inbox", DATA.inquiries_per_day(self.cfg,
                                                             self._rows),
                             theme.OK),
                C.MetricCard(i18n.t("Quoted"), stats["quoted_value"],
                             i18n.t("this month"), "file", None, theme.ACCENT),
            ]
        # Four across on a wide window, three across once the register adds
        # two more, so the row always divides evenly instead of leaving a
        # half-empty second line.
        grid = C.CardGrid(min_col_width=200,
                          max_columns=4 if len(cards) <= 4 else 3)
        grid.add_all(cards)
        return grid

    def _bottom(self, runs, stalled) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.CARD_GAP)
        row.addWidget(self._recent(runs, stalled), stretch=2)
        row.addWidget(self._addons(), stretch=1)
        row.addWidget(self._tools(), stretch=1)
        return row

    def _recent(self, runs, stalled) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), spacing=0)
        col.addWidget(C.SectionHeader(
            i18n.t("Recent activity"), "",
            [C.button(i18n.t("See all in History"), "link",
                      on_click=self.open_history.emit)]))
        col.addSpacing(theme.SPACE_2)

        if not runs:
            empty = C.EmptyState(
                "inbox", i18n.t("No runs yet"),
                i18n.t("Every task you start is saved here, with the tools it "
                       "used and what it produced."),
                i18n.t("Describe a task"))
            empty.clicked.connect(self.describe_task.emit)
            col.addWidget(empty, stretch=1)
            return card

        # Newest first, and only the runs that actually reached a tool — see
        # _never_started(). The rest are counted at the foot of the card.
        listed = [r for r in runs if not _never_started(r)][:RECENT_SHOWN]
        if not listed:
            # Every run in the window stopped before a tool. That is a fault
            # to report, not a list to draw — one centred block that says what
            # happened and where to look beats a column of identical rows over
            # a white void.
            empty = C.EmptyState(
                "alert", i18n.t("Nothing has finished yet"),
                i18n.t("Every recent run stopped before a tool was reached. "
                       "Open History to see what each one recorded."),
                i18n.t("Open History"))
            empty.clicked.connect(self.open_history.emit)
            col.addWidget(empty, stretch=1)
            return card

        for i, run in enumerate(listed):
            if i:
                col.addWidget(C.hairline())
            col.addWidget(self._recent_row(run))
        if stalled:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(C.hairline())
            col.addWidget(self._stalled_row(stalled))
        col.addStretch(1)
        return card

    def _recent_row(self, run: dict) -> QWidget:
        """One finished run. The state is a StatusBadge, so "COMPLETED" is the
        semantic green everywhere it appears — it used to be `Pill("Done",
        "accent")`, which rotates with the role hue, so in a green profile the
        pill for "done" and the pill for "failed" stopped being different
        colours at all."""
        wrap = _Row()
        wrap.clicked.connect(
            lambda p=run.get("path", ""): p and self.open_run_record.emit(p))
        row = QHBoxLayout(wrap)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                               theme.SPACE_2, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)

        tools = run.get("tools") or []
        if tools:
            row.addWidget(C.ToolBadge(tools[0], 32, theme.R_CONTROL))
        else:
            row.addWidget(C.IconPad("clock", theme.NEUTRAL[400], 32,
                                    theme.R_CONTROL, 16))

        stack = QVBoxLayout()
        stack.setSpacing(1)
        title = _Elided(run["title"], "BODY", weight=500)
        stack.addWidget(title)
        detail = " · ".join(list(tools) + [run.get("when", "")]) if tools \
            else i18n.t("No tool recorded") + " · " + run.get("when", "")
        stack.addWidget(_Elided(detail, "META"))
        row.addLayout(stack, stretch=1)

        row.addWidget(C.StatusBadge(
            "completed" if run.get("ok", True) else "failed", focusable=False))
        wrap.setAccessibleName(title.text_value())
        return wrap

    def _stalled_row(self, stalled: list[dict]) -> QWidget:
        """The runs that never reached a tool, as one line rather than as four
        identical "Untitled task · Failed" rows.

        They are not hidden and they are not deleted — History still lists
        every one. What changes is that Home stops reporting an environment
        fault as four separate failed jobs, which is what made a working
        install read as a broken one.
        """
        wrap = _Row()
        wrap.clicked.connect(self.open_history.emit)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                               theme.SPACE_2, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad("alert", theme.WARN, 32, theme.R_CONTROL, 16))

        stack = QVBoxLayout()
        stack.setSpacing(1)
        stack.addWidget(_Elided(i18n.t("Stopped before any tool ran"),
                                "BODY", weight=500))
        # dashboard_data does not hand back the recorded reason yet (see the
        # WIRING NEEDED note); when it does, this line names it — "Chrome would
        # not launch" — instead of the generic sentence.
        reason = ""
        for run in stalled:
            reason = (run.get("error") or "").strip()
            if reason:
                break
        stack.addWidget(_Elided(
            reason or i18n.t("These runs never reached a tool. Open History to "
                             "see them."), "META"))
        row.addLayout(stack, stretch=1)
        row.addWidget(C.Pill(str(len(stalled)), "warn"))
        return wrap

    def _addons(self) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), spacing=0)
        col.addWidget(C.SectionHeader(i18n.t("Your add-ons")))
        col.addSpacing(theme.SPACE_2)
        stats = DATA.inquiry_stats(self.cfg, self._rows)
        waiting = (i18n.t("{n} waiting").format(n=stats["waiting"])
                   if stats and stats["waiting"] else "")
        for key, label, desc, icon_name, hue in ADDONS:
            badge = waiting if key == "inquiry" else ""
            col.addWidget(self._addon_row(key, label, desc, icon_name, hue,
                                          badge))
        col.addStretch(1)
        return card

    def _addon_row(self, key, label, desc, icon_name, hue, badge) -> QWidget:
        # "motion" joins "bom" here 2026-08-30: the render pipeline has a
        # known bug (see core.motion.render's kill-switch), so the tile stays
        # visible — a visible "next one" beats an empty gap — but not
        # clickable, same as "bom" already is, until the bug is fixed.
        soon = key in ("bom", "motion")
        wrap = _Row(enabled=not soon)
        if not soon:
            wrap.clicked.connect(
                lambda k=key: self.open_addon.emit(k))
        row = QHBoxLayout(wrap)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                               theme.SPACE_2, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad(icon_name, hue or theme.ACCENT, 32,
                                theme.R_CONTROL, 16))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        ink = theme.NEUTRAL[400] if soon else theme.TEXT
        stack.addWidget(_Elided(i18n.t(label), "SUPPORT", ink, weight=500))
        stack.addWidget(_Elided(i18n.t(desc), "META"))
        row.addLayout(stack, stretch=1)
        if badge:
            row.addWidget(C.Pill(badge, "warn"))
        wrap.setAccessibleName(i18n.t(label))
        return wrap

    def _tools(self) -> QWidget:
        """Which tool each pipeline stage is set up to drive.

        Straight off `cfg["agents"]` and the engine's own category table, which
        is the same pair the AI tools screen and Settings → Agents read — so
        what Home reports and what those two screens edit cannot disagree.
        """
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), spacing=0)
        col.addWidget(C.SectionHeader(
            i18n.t("Connected tools"), "",
            [C.button(i18n.t("Manage"), "link",
                      on_click=lambda: self.open_addon.emit("catalog"))]))
        col.addSpacing(theme.SPACE_2)

        stages, chosen, labels = self._pipeline()
        if not stages:
            col.addWidget(C.label(
                i18n.t("No tools are set up yet. Pick one for each kind of "
                       "work and Prism will drive it in your own Chrome."),
                level="SUPPORT", wrap=True))
            col.addStretch(1)
            return card

        # Distinct tools, in the order the pipeline first reaches them, each
        # carrying the kinds of work it covers. A tool driving four kinds is a
        # different fact from one driving a single kind, and naming them is
        # what turns this from a list of logos into an answer.
        order: list[str] = []
        covers: dict[str, list[str]] = {}
        for stage in stages:
            tool = (chosen.get(stage) or "").strip()
            if not tool:
                continue
            if tool not in covers:
                order.append(tool)
                covers[tool] = []
            covers[tool].append(labels.get(stage, stage))

        assigned = sum(len(v) for v in covers.values())
        col.addWidget(C.label(
            i18n.t("Every kind of work has a tool") if assigned >= len(stages)
            else i18n.t("{done} of {total} kinds of work have a tool").format(
                done=assigned, total=len(stages)),
            level="META"))
        col.addSpacing(theme.SPACE_2)

        for i, tool in enumerate(order):
            if i:
                col.addWidget(C.hairline())
            col.addWidget(self._tool_row(tool, covers[tool]))
        col.addStretch(1)
        return card

    def _pipeline(self) -> tuple[list[str], dict, dict]:
        """(stages that carry a tool choice, the tool chosen for each, the
        name of each kind of work).

        Guarded, and the guard is not tidiness: HomePanel is built inside
        MainWindow.__init__, so an import error reaching this far does not
        blank a card — it stops the window existing at all, in a frozen build
        with no console to say why.
        """
        try:
            import core_bridge as CB
            stages = [s for s in CB.agents.PIPELINE_ORDER if s != "summary"]
            cats = CB.agents.CATEGORIES or {}
        except Exception:                                   # noqa: BLE001
            return [], {}, {}
        # The engine's own label, split at the ampersand: "Research & Academic"
        # is a catalogue heading, and this column is 240px wide.
        labels = {s: (cats.get(s, {}).get("label") or s).split(" & ")[0]
                  for s in stages}
        return stages, dict(self.cfg.get("agents") or {}), labels

    def _tool_row(self, tool: str, covers: list[str]) -> QWidget:
        wrap = _Row()
        wrap.clicked.connect(lambda: self.open_addon.emit("catalog"))
        row = QHBoxLayout(wrap)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_2 - 2,
                               theme.SPACE_2, theme.SPACE_2 - 2)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.ToolBadge(tool, 28, theme.R_CHIP))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        # A tool's name is a brand, never translated — hence _Elided on the
        # raw value rather than anything that could reach the catalogue.
        stack.addWidget(_Elided(tool, "SUPPORT", weight=500))
        stack.addWidget(_Elided(" · ".join(covers), "META"))
        row.addLayout(stack, stretch=1)
        wrap.setAccessibleName(f"{tool}. {', '.join(covers)}")
        return wrap
