"""Six screens: the Guide, the AI tools registry, History, and the three
add-on front doors (BOQ, Gerber, Email).

They were "a page header and one card" — destinations rather than workbenches
— and measured 50-67% empty grey at 1440x900. The cause was structural and
identical on all six: a top-anchored column inside a scroll area finished with
`addStretch(1)`, so every pixel of leftover window height piled up in one band
underneath a small card.

What replaced it, screen by screen:

  AI tools   was nine hand-laid category cards in a QHBoxLayout padded with
             addStretch, every one of them wearing a green "In use" pill that
             meant nothing. It is now a real registry: the pipeline you have
             configured, then all 32 tools in a reflowing CardGrid with search
             and category filters. The pill says what Prism can actually know
             — which stage a tool is set to run — and never claims a sign-in
             it has no way to check.

  History    was already dense and stays dense, but it grouped nothing,
             filtered nothing, searched nothing, and rendered success in
             ACCENT — which rotates with the role, so in a green profile
             "Done" and "Failed" stopped being distinguishable. It now uses
             the OK semantic through StatusBadge, groups by date, and
             separates a run that FAILED from a run that never started.

  Add-ons    were one small centred card over a 67% grey field. Each is now a
             module: what it does, what it has produced on this machine, and
             the way in.

Nothing here invents a figure. Where a screen has nothing real to show it says
so in an EmptyState that centres in the full height it is given, which is the
honest version of the same silence.

BOQ, Gerber and Email keep their dialogs — the dialogs are where the work
happens. These screens are the front door.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import core_bridge as CB
import dashboard_data as DATA
import i18n
import theme
from widgets import controls as C
from widgets import icons


# ── copy tables ─────────────────────────────────────────────────────────────
# devtools/extract_strings.py scans module-level tables by NAME (see its
# COPY_TABLES set), so anything the user reads that reaches the screen through
# a variable has to live in a table called one of those names or it ships
# untranslatable. LABELS, ADDONS and SECTIONS below are exactly that.

# The nine selectable categories, in the words the filter chips use. The
# registry's own `label` ("Orchestration & Brains") is the long form and is
# still shown on the pipeline cards; these are the short form a chip row can
# carry without wrapping.
LABELS = {
    "research": "Research",
    "leads": "Leads",
    "brains": "Reasoning",
    "content": "Writing",
    "visual": "Images",
    "media": "Video",
    "audio": "Audio",
    "development": "Apps",
    "presentation": "Decks",
}

# Which add-on wrote a run record, in the word a History row wears.
ADDONS = {
    "boq": "BOQ",
    "bom": "BOM",
    "gerber": "Gerber",
    "email": "Email",
    "reel": "Reel",
    "motion": "Motion",
}

# History's date groups, coarsest last. Returned by _bucket() and translated
# at render time — the literals are here so the extractor can see them.
SECTIONS = ("Today", "Yesterday", "Earlier this week", "Last week",
            "Two weeks ago", "Three weeks ago", "Earlier this month", "Older")

# A leading line icon per category, for the pipeline cards. Icon names, not
# copy — every one is lowercase and alphanumeric so the string extractor's
# identifier test rejects it. Do NOT put a hyphenated icon name in here; it
# would read as prose and land in front of a translator.
_CATEGORY_ICONS = {
    "research": "book", "leads": "user", "brains": "bulb", "content": "pencil",
    "visual": "image", "media": "video", "audio": "mic", "development": "code",
    "presentation": "present", "summary": "list",
}

# How each add-on stamps the run record it saves, so a History row and an
# add-on's own "recent runs" list can both recognise its work. Matched with
# str.startswith against stored data and never shown to anyone, which is why
# this table is deliberately NOT named after one of the extractor's copy
# tables — a translated match prefix would match nothing.
#   boq_dialog.py:351     f"BOQ — {self.request}"
#   gerber_dialog.py:247  f"Gerber — {…}"
#   email_dialog.py:604   f"/email {goal}"
#   prism.py (the CLI)    "/boq …", "/email …", "/reel …"
_RUN_PREFIXES = (
    ("boq", ("BOQ — ", "/boq ")),
    ("bom", ("BOM — ", "/bom ")),
    ("gerber", ("Gerber — ", "/gerber ")),
    ("email", ("/email ",)),
    ("reel", ("/reel ",)),
    ("motion", ("motion — ", "/motion ")),
)

# dashboard_data.recent_runs() substitutes this when a record carries no query
# at all. Matching the sentinel is the only way, from the shaped row, to tell
# "the user never typed anything" from "the user typed something and it broke"
# — see ## WIRING NEEDED, which asks for an explicit flag instead.
_NO_QUERY = "Untitled task"


# ── small shared helpers ────────────────────────────────────────────────────
class _Elided(QLabel):
    """A single-line label that is allowed to shrink.

    This exists because of a measured defect, not for tidiness. A plain QLabel
    reports its full text width as its layout minimum, so ONE long run title
    drags the whole page wider than the window and the user gets a horizontal
    scrollbar on a list screen — audit_ui.py caught History overflowing by
    74px at 1366x768 and 160px at 1280x800 while looking perfectly fine at
    1440x900 with that hour's data.

    So: a small minimum width, a size policy that lets the layout squeeze it,
    and the text elided to whatever width it actually got. The full string
    stays in the tooltip, so nothing is lost.

    The font is set as a real QFont as well as in the stylesheet. Both come
    from theme, so they agree — but the QFont is what QFontMetrics measures,
    and style.qss's `* { font-size: 14px }` would otherwise make every
    elision computation wrong by a couple of characters.
    """

    MIN_W = 64

    def __init__(self, text: str = "", level: str = "BODY", colour: str = "",
                 weight: int = 0, grow: bool = True, min_w: int = 0,
                 max_w: int = 0, mode=Qt.ElideRight, parent=None):
        super().__init__(parent)
        self._full = text or ""
        self._mode = mode
        self.setFont(theme.font(level, weight))
        family, px, css_weight, ink = theme.TYPE.get(level, theme.T_BODY)
        stack = (theme.FONT_MONO_STACK if level == "MONO" else f"'{family}'")
        self.setStyleSheet(
            f"font-family: {stack}; font-size: {px}px;"
            f" font-weight: {weight or css_weight}; color: {colour or ink};"
            f" background: transparent;")
        # Ignored, not Preferred: Ignored drops the sizeHint entirely, which is
        # what lets a long title give its width back to the row instead of
        # taking it from everything else.
        self.setSizePolicy(QSizePolicy.Ignored if grow else QSizePolicy.Preferred,
                           QSizePolicy.Fixed)
        self.setMinimumWidth(min_w or self.MIN_W)
        if max_w:
            self.setMaximumWidth(max_w)
        if self._full:
            self.setToolTip(self._full)
        self._apply()

    def set_full_text(self, text: str):
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def _apply(self):
        metrics = QFontMetrics(self.font())
        width = max(self.minimumWidth(), self.width())
        QLabel.setText(self, metrics.elidedText(self._full, self._mode, width))


class _ActionCard(C.Card):
    """A card that is a link. Icon, name, one line, and it goes somewhere.

    Used by the guide's "Where things are" section. A Card subclass rather
    than a sixth card recipe, and keyboard-reachable because a card that only
    a mouse can activate is a control that half the audit does not see.
    """

    clicked = Signal()

    def __init__(self, icon: str, title: str, body: str, parent=None):
        super().__init__(parent=parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        # Card sets a plain "#card { … }" rule with no interactive states, so
        # a focused card would be indistinguishable from a resting one. The
        # resting half is re-declared identically rather than added to,
        # because a widget stylesheet REPLACES the app rule for this widget.
        self.setStyleSheet(
            f"#card {{ background: {theme.CARD};"
            f" border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.HAIRLINE}; }}"
            f"#card:hover {{ border-color: {theme.NEUTRAL[300]}; }}"
            f"#card:focus {{ border-color: {theme.ACCENT}; }}")
        col = self.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15))
        top.addWidget(_Elided(title, "CARD_TITLE"), stretch=1)
        arrow = QLabel()
        arrow.setPixmap(icons.pixmap("chevron-right", 15, theme.NEUTRAL[500]))
        top.addWidget(arrow)
        col.addLayout(top)
        col.addWidget(_wrapped(body, "META"))
        self.setAccessibleName(f"{title}. {body}")

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


def _wrapped(text: str, level: str = "SUPPORT", colour: str = "") -> QLabel:
    """A wrapping paragraph that is also allowed to shrink.

    Same reasoning as _Elided: an explicit minimumWidth replaces whatever the
    layout would otherwise compute from the text, which is what keeps a card
    grid from forcing the page wider than the window.
    """
    lbl = C.label(text, level=level, colour=colour, wrap=True)
    lbl.setMinimumWidth(80)
    return lbl


def _clip(text: str, limit: int = 104) -> str:
    """The opening of a registry `specialty`, cut on a word boundary.

    The registry writes some of these as whole paragraphs (ChatGPT's runs to
    nine lines). A card grid needs every card to be roughly one height, and
    the full text is one tooltip away, so the card shows the claim and not the
    essay. Truncating what is displayed is not the same as inventing it.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;.:—-") + "…"


def _kind_of(title: str) -> str:
    """Which add-on wrote this run record, or "" for a workbench task."""
    title = title or ""
    for kind, prefixes in _RUN_PREFIXES:
        for prefix in prefixes:
            if title.startswith(prefix):
                return kind
    return ""


def _plain_title(title: str) -> str:
    """A run's title with the add-on's own prefix taken off, so a BOQ row
    reads "Quantities for the shed" and not "BOQ — Quantities for the shed"
    next to a chip that already says BOQ."""
    title = title or ""
    for _kind, prefixes in _RUN_PREFIXES:
        for prefix in prefixes:
            if title.startswith(prefix):
                return title[len(prefix):].strip() or title
    return title


def _state_of(run: dict) -> str:
    """One run as a theme.STATUS state: completed, failed, or cancelled.

    The third one is the whole point, and it is a DISPLAY decision — nothing
    is deleted, hidden from the counts, or made unopenable.

    Real user data on this machine holds 86 records out of 103 with no query
    text, no tool and the error "Chrome would not launch". Nothing was ever
    attempted in any of them. Rendering those in red as FAILED, six in a row,
    makes Prism look like a product that does not work — when what actually
    happened is that it never started. `cancelled` is the state the system
    already has for that: neutral tone, square dot, outside the error colour.

    They are still listed, still counted on their own filter chip, and still
    open their record when clicked. Suppressing them was the alternative and
    it is worse: 86 identical aborts is the single most useful diagnostic
    signal in this History, and a user who cannot see them cannot report it.
    """
    if run.get("ok"):
        return "completed"
    if not run.get("tools") and (run.get("title") or "").strip() == _NO_QUERY:
        return "cancelled"
    return "failed"


def _bucket(when: str, stamp: float = 0.0) -> str:
    """Which date group a run belongs to.

    Driven by the raw mtime `recent_runs` now returns. It used to read
    `_ago()`'s English instead, and that had one bad consequence: every
    phrasing containing "week" — one week or four — landed in a single
    bucket. A workspace with a month of history therefore rendered as one
    undated heap headed "Earlier this month · 78 runs", which is not an
    ordering a person can read even though the rows inside it were in
    perfect order.

    The English is still accepted as a fallback so a caller that has no
    stamp (an older record, a test fixture) keeps working.
    """
    if stamp:
        import time
        days = max(0.0, (time.time() - stamp) / 86400.0)
        if days < 1:
            return SECTIONS[0]          # Today
        if days < 2:
            return SECTIONS[1]          # Yesterday
        if days < 7:
            return SECTIONS[2]          # Earlier this week
        if days < 14:
            return SECTIONS[3]          # Last week
        if days < 21:
            return SECTIONS[4]          # Two weeks ago
        if days < 28:
            return SECTIONS[5]          # Three weeks ago
        if days < 60:
            return SECTIONS[6]          # Earlier this month
        return SECTIONS[7]              # Older

    text = (when or "").strip().lower()
    if text == "yesterday":
        return SECTIONS[1]
    if text == "just now" or text.endswith("m ago") or "hour" in text:
        return SECTIONS[0]
    if "day" in text:
        return SECTIONS[2]
    if "week" in text:
        return SECTIONS[6]
    return SECTIONS[7]


def _focusable_row(widget: QFrame):
    """Give a clickable list row its hover and focus states.

    style.qss defines #rowFlat and #rowFlat:hover but no :focus, so a row
    reached by keyboard looked exactly like a row that was not — which makes
    tabbing through History indistinguishable from doing nothing. The border
    is always there and only changes colour, so gaining focus never reflows
    the row underneath the cursor.
    """
    widget.setStyleSheet(
        f"#rowFlat {{ background: transparent;"
        f" border: 1px solid transparent;"
        f" border-radius: {theme.R_CONTROL}px; }}"
        f"#rowFlat:hover {{ background: {theme.WELL}; }}"
        f"#rowFlat:focus {{ background: {theme.WELL};"
        f" border-color: {theme.ACCENT}; }}")
    return widget


def _tool_line(tool: str | None) -> QWidget:
    """A tool's badge and name, or the fact that no tool is set.

    Shared by the AI tools pipeline cards and the add-on screens, so "which
    tool runs this" reads identically wherever the question comes up.
    """
    wrap = QFrame()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.SPACE_2)
    if tool:
        row.addWidget(C.ToolBadge(tool, 22, theme.R_MICRO))
        row.addWidget(_Elided(tool, "SUPPORT", theme.TEXT, weight=600),
                      stretch=1)
    else:
        row.addWidget(C.Pill(i18n.t("Not picked"), "quiet"))
        row.addStretch(1)
    return wrap


def _categories_of(tool: str) -> list[str]:
    """Every category that offers this tool, in pipeline order.

    A tool appearing more than once is deliberate and documented in the
    registry — LAZYCOOK is offered under four categories, Claude under four —
    so the card states all of them rather than picking one and looking like a
    duplicate.
    """
    out = []
    for stage in CB.agents.PIPELINE_ORDER:
        meta = CB.agents.CATEGORIES.get(stage)
        if meta and tool in meta.get("agents", ()):
            out.append(stage)
    return out


# ── the page scaffold every screen here uses ────────────────────────────────
class _Page(QWidget):
    """A fixed PageHeader, then a scrolling column with page padding.

    The header never scrolls; the column is rebuilt by refresh(). Subclasses
    implement build() and add to self._col.

    build() owns what happens to the leftover height, and that is the whole
    fix for these screens. Finish with self._col.addStretch(1) only when there
    is real content above it; otherwise hand the slack to a C.EmptyState added
    with stretch=1, which centres in it. The one thing build() must never do
    is top-anchor a small card and leave a grey field beneath.

    LAZY defers the first build until the screen is actually shown, so a panel
    that reads run records off a (possibly shared, possibly slow) folder costs
    nothing at startup — MainWindow constructs all eleven screens in its own
    __init__.
    """

    TITLE = ""
    BLURB = ""
    MAX_W = 0                   # 0 = fill the width
    LAZY = False                # don't touch the disk until shown
    RELOAD_ON_SHOW = False      # re-read every time the screen is opened

    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._built = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = C.PageHeader(i18n.t(self.TITLE),
                                   i18n.t(self.BLURB) if self.BLURB else "",
                                   self.header_actions())
        root.addWidget(self.header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self._scroll.setWidget(host)
        frame = QHBoxLayout(host)
        frame.setContentsMargins(theme.PAGE_PAD, theme.PAGE_PAD,
                                 theme.PAGE_PAD, theme.PAGE_PAD)
        frame.setSpacing(0)
        holder = QWidget()
        if self.MAX_W:
            holder.setMaximumWidth(self.MAX_W)
        self._col = QVBoxLayout(holder)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(theme.CARD_GAP)
        frame.addWidget(holder, stretch=1)
        root.addWidget(self._scroll, stretch=1)

        self.refresh()

    # -- overridable ------------------------------------------------------
    def header_actions(self) -> list:
        """Already-built widgets for the header's right-hand side. Exactly one
        primary per surface."""
        return []

    def build(self):
        raise NotImplementedError

    # -- lifecycle --------------------------------------------------------
    def refresh(self):
        self.header.title.setText(i18n.t(self.TITLE))
        self.header.set_subtitle(i18n.t(self.BLURB) if self.BLURB else "")
        self._drop(self._col)
        if self.LAZY and not self.isVisible():
            self._built = False
            return
        self._built = True
        self.build()

    def showEvent(self, event):
        super().showEvent(event)
        if self.LAZY and (not self._built or self.RELOAD_ON_SHOW):
            self.refresh()

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            # Held in a local, deliberately. `item.widget().setParent(None)`
            # hands ownership back to Python, and with no reference kept the
            # widget is collected on the spot — so a second `item.widget()`
            # on the next line returns None and the reparenting crashes the
            # rebuild.
            widget = item.widget()
            if widget is not None:
                # Hidden first: setParent(None) on a visible widget makes it a
                # top-level OS window for a frame — the ghost-window flash.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._drop(child)


# ── Guide ───────────────────────────────────────────────────────────────────
class GuidePanel(_Page):
    TITLE = "How to use Prism"
    BLURB = "For someone who has never used AI before."

    navigate = Signal(str)          # a key for MainWindow._handle_command

    # The five stages of the mental model, which is the one thing a first-time
    # user has to hold. Same order the engine runs them in.
    STEPS = [
        ("pencil", "Describe",
         "Say the job in your own words. No form, no settings, no prompt."),
        ("list", "Plan",
         "Prism works out the stages and which tool should run each one."),
        ("check", "Review",
         "Read the plan. Drop a step you don't want, or send it elsewhere."),
        ("play", "Execute",
         "Your Chrome opens and the tools are worked as you, in order."),
        ("archive", "Results",
         "Everything comes back in one place, and is kept in History."),
    ]

    CARDS = [
        ("pencil", "Describe a job in your own words",
         "“Write a proposal for a 40-camera CCTV project.” Prism works out "
         "which AI tools are needed, uses them in order, and hands you the "
         "finished result."),
        ("sliders", "Review the plan before it runs",
         "Every stage is shown as a plain-English step. Drop any you don't "
         "want, or send a step to a different tool."),
        ("grid", "The add-ons are purpose-built",
         "Email automation, BOQ and Email are dedicated tools for recurring "
         "jobs — they don't need a plan, just your files."),
        ("globe", "Prism's own language, and the AI's, are separate",
         "Set them independently in Settings — a Gujarati-speaking owner may "
         "still want the output in English."),
        # Not in the design, but the single most common support question: the
        # tools run in the customer's own Chrome, signed in as them, and
        # nobody guesses that from the outside.
        ("lock", "It drives your own browser",
         "Prism opens your Chrome and works the tools as you, using the "
         "accounts you already pay for. Nothing is sent to a Prism server."),
    ]

    # Every destination the rail can reach, as a way out of the guide. The
    # rail was slimmed to eleven controls on purpose and several screens now
    # live inside Settings, so "where is it" is a real question and this is
    # the screen it should be answered on. The keys are MainWindow's own
    # command names — see _handle_command.
    DIRECT = [
        ("workbench", "plus", "Start a task",
         "Describe a job and let Prism plan it."),
        ("catalog", "grid", "AI tools",
         "Every tool Prism can drive, and which stage each one runs."),
        ("runs", "clock", "History",
         "Everything you have run, and what came back."),
        ("inquiry", "inbox", "Email automation",
         "Inquiries logged, quoted and followed up."),
        ("boq", "file", "BOQ",
         "Quantities off a drawing or a written spec."),
        ("agents", "sliders", "Settings",
         "Your tools, your languages, your workspace and your licence."),
    ]

    def header_actions(self):
        return [
            C.button(i18n.t("AI tools"), "secondary", icon_name="grid",
                     on_click=lambda: self.navigate.emit("catalog")),
            C.button(i18n.t("Start a task"), "primary", icon_name="plus",
                     on_click=lambda: self.navigate.emit("workbench")),
        ]

    def build(self):
        self._col.addWidget(C.SectionHeader(
            i18n.t("What happens when you start a task"),
            i18n.t("Five steps, always in this order.")))
        flow = C.CardGrid(min_col_width=186)
        flow.add_all([self._step_card(i + 1, icon, title, body)
                      for i, (icon, title, body) in enumerate(self.STEPS)])
        self._col.addWidget(flow)

        self._col.addWidget(C.SectionHeader(
            i18n.t("Worth knowing"),
            i18n.t("The five things people ask about first.")))
        grid = C.CardGrid(min_col_width=310)
        grid.add_all([self._note_card(icon, title, body)
                      for icon, title, body in self.CARDS])
        self._col.addWidget(grid)

        self._col.addWidget(C.SectionHeader(
            i18n.t("Where things are"),
            i18n.t("The rail keeps eleven controls; everything else lives "
                   "inside one of these.")))
        where = C.CardGrid(min_col_width=272)
        cards = []
        for key, icon, title, body in self.DIRECT:
            card = _ActionCard(icon, i18n.t(title), i18n.t(body))
            card.clicked.connect(lambda k=key: self.navigate.emit(k))
            cards.append(card)
        where.add_all(cards)
        self._col.addWidget(where)
        self._col.addStretch(1)

    def _step_card(self, index: int, icon: str, title: str, body: str):
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15))
        top.addWidget(C.kicker(f"{index:02d}"), stretch=1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t(title), "CARD_TITLE"))
        col.addWidget(_wrapped(i18n.t(body), "META"))
        return card

    def _note_card(self, icon: str, title: str, body: str):
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15),
                      alignment=Qt.AlignTop)
        top.addWidget(_wrapped(i18n.t(title), "CARD_TITLE"), stretch=1)
        col.addLayout(top)
        col.addWidget(_wrapped(i18n.t(body), "SUPPORT"))
        return card


# ── AI tools ────────────────────────────────────────────────────────────────
class CatalogPanel(_Page):
    """The tool registry, as a registry.

    Two cuts of the same data, and both are needed.

    The pipeline grid at the top is the per-CATEGORY cut the old screen had,
    and the reason it stays is the reason the old comment gave: it is the same
    list Settings → Agents edits, so what you read here is what you change
    there. It is also the only place the ORDER is visible — stages run
    top-to-bottom and each feeds the next.

    The tool grid underneath is the per-TOOL cut, which the old screen could
    not show at all: 32 tools exist and nine were on screen. A tool card names
    every category that offers it, so the pipeline above and the grid below
    read as two views of one list rather than two lists.

    On status, and this is deliberate: Prism CANNOT know whether you are
    signed in to Perplexity without driving the browser to find out. So no
    card claims a connection. "In your pipeline" means this copy is set to
    send that stage here; "Built in" means the tool runs inside Prism with no
    account at all, which is the one connectivity fact that is knowable. The
    old screen's green "In use" pill said neither — it was on every card
    unconditionally.
    """

    TITLE = "AI tools"
    BLURB = ("Prism opens each of these in your own Chrome and works it as "
             "you. It cannot check a sign-in from here.")

    open_directory = Signal()       # kept: AIDirectoryDialog's entry point
    navigate = Signal(str)          # a key for MainWindow._handle_command

    def header_actions(self):
        return [C.button(i18n.t("Change which tool runs what"), "secondary",
                         icon_name="sliders",
                         on_click=lambda: self.navigate.emit("agents"))]

    def build(self):
        self._chosen = {stage: tool
                        for stage, tool in (self.cfg.get("agents") or {}).items()
                        if tool}
        stages = [s for s in CB.agents.PIPELINE_ORDER if s != "summary"]
        picked = sum(1 for s in stages if self._chosen.get(s))

        self._col.addWidget(C.SectionHeader(
            i18n.t("Your pipeline"),
            i18n.t("{done} of {total} stages have a tool. Stages run in this "
                   "order and each feeds the next — the same list "
                   "Settings → Agents edits.").format(done=picked,
                                                      total=len(stages))))
        pipeline = C.CardGrid(min_col_width=196)
        pipeline.add_all(
            [self._stage_card(i + 1, stage, self._chosen.get(stage))
             for i, stage in enumerate(stages)]
            + [self._summary_card(len(stages) + 1)])
        self._col.addWidget(pipeline)

        self._col.addWidget(C.SectionHeader(
            i18n.t("Every tool Prism can drive"),
            i18n.t("A tool is offered under more than one category when it is "
                   "genuinely good at both. That is intentional, not a "
                   "duplicate.")))

        bar = C.Toolbar()
        self._search = C.SearchField(
            i18n.t("Search a tool, a category, or what it is good at"))
        self._search.changed.connect(lambda _text: self._populate())
        bar.add(self._search, stretch=1)
        self._count = C.label("", role="meta")
        bar.add(self._count)
        self._col.addWidget(bar)

        chips = [("all", i18n.t("All"))]
        chips += [(stage, i18n.t(LABELS[stage]))
                  for stage in CB.agents.PIPELINE_ORDER if stage in LABELS]
        self._chips = C.FilterChips(chips, "all")
        self._chips.changed.connect(lambda _value: self._populate())
        self._col.addWidget(self._chips)

        self._grid = C.CardGrid(min_col_width=286)
        self._col.addWidget(self._grid)
        self._empty = C.EmptyState(
            "search", i18n.t("No tool matches that"),
            i18n.t("Try a different word, or show every category again."))
        self._empty.setVisible(False)
        self._col.addWidget(self._empty)
        self._empty_at = self._col.count() - 1
        self._col.addStretch(1)
        self._populate()

    # -- the pipeline cut -------------------------------------------------
    def _stage_card(self, index: int, stage: str, tool: str | None):
        meta = CB.agents.CATEGORIES.get(stage, {})
        card = C.Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad(_CATEGORY_ICONS.get(stage, "grid"),
                                theme.ACCENT, 26, theme.R_CHIP, 14))
        top.addWidget(C.kicker(f"{index:02d}"))
        top.addStretch(1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t(LABELS.get(stage, stage)), "CARD_TITLE"))
        col.addWidget(_Elided(meta.get("label", ""), "META"))
        col.addWidget(C.hairline())
        col.addWidget(_tool_line(tool))
        return card

    def _summary_card(self, index: int):
        """The final stage. The old screen skipped it with a `continue`, which
        left the pipeline reading as if it ended at Presentations — it does
        not: summary_agent_name() reuses whichever tool is set for Reasoning,
        then Writing, then Research."""
        card = C.Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad("list", theme.ACCENT, 26, theme.R_CHIP, 14))
        top.addWidget(C.kicker(f"{index:02d}"))
        top.addStretch(1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t("Final summary"), "CARD_TITLE"))
        col.addWidget(_Elided(i18n.t("Reuses your Reasoning tool"), "META"))
        col.addWidget(C.hairline())
        col.addWidget(_tool_line(CB.agents.summary_agent_name(self._chosen)))
        return card

    # -- the per-tool cut -------------------------------------------------
    def _populate(self):
        query = (self._search.text() or "").strip().lower()
        want = self._chips.current()
        self._grid.clear()

        cards, total = [], 0
        for name, entry in CB.agents.AGENT_REGISTRY.items():
            categories = _categories_of(name)
            total += 1
            if want != "all" and want not in categories:
                continue
            if query and not self._matches(name, entry, categories, query):
                continue
            cards.append(self._tool_card(name, entry, categories))
        self._grid.add_all(cards)
        self._grid.setVisible(bool(cards))
        self._empty.setVisible(not cards)
        # Handing the slack to the empty state is what keeps a filter that
        # matches nothing from being a small line of text over a grey field.
        self._col.setStretch(self._empty_at, 0 if cards else 1)
        self._count.setText(i18n.t("{shown} of {total} tools").format(
            shown=len(cards), total=total))

    def _matches(self, name, entry, categories, query) -> bool:
        haystack = [name.lower(), (entry.get("specialty") or "").lower(),
                    (entry.get("cost") or "").lower()]
        for stage in categories:
            haystack.append(LABELS.get(stage, stage).lower())
            haystack.append(
                (CB.agents.CATEGORIES.get(stage, {}).get("label") or "").lower())
        return any(query in part for part in haystack)

    def _tool_card(self, name: str, entry: dict, categories: list) -> QWidget:
        assigned = [stage for stage in CB.agents.PIPELINE_ORDER
                    if self._chosen.get(stage) == name and stage in LABELS]
        local = bool(entry.get("local"))

        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.ToolBadge(name, 28), alignment=Qt.AlignTop)
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(_Elided(name, "CARD_TITLE"))
        access = " · ".join(x for x in (
            entry.get("cost", ""), entry.get("avg", ""),
            i18n.t("runs in Prism") if local else i18n.t("opens in Chrome"),
        ) if x)
        stack.addWidget(_Elided(access, "META"))
        head.addLayout(stack, stretch=1)
        # Never a green "Connected": see the class docstring.
        if local:
            head.addWidget(C.Pill(i18n.t("Built in"), "ok"),
                           alignment=Qt.AlignTop)
        elif assigned:
            head.addWidget(C.Pill(i18n.t("In your pipeline"), "accent"),
                           alignment=Qt.AlignTop)
        else:
            head.addWidget(C.Pill(i18n.t("Available"), "quiet"),
                           alignment=Qt.AlignTop)
        col.addLayout(head)

        good_at = _wrapped(_clip(entry.get("specialty", "")), "SUPPORT")
        good_at.setToolTip(" ".join((entry.get("specialty") or "").split()))
        col.addWidget(good_at)

        col.addWidget(C.hairline())
        col.addWidget(C.kicker(i18n.t("Offered under"), muted=True))
        col.addWidget(_Elided(
            " · ".join(i18n.t(LABELS[s]) for s in categories) or i18n.t("None"),
            "META", theme.NEUTRAL[700]))
        if assigned:
            col.addWidget(_Elided(
                i18n.t("Set to run: {stages}").format(
                    stages=", ".join(i18n.t(LABELS[s]) for s in assigned)),
                "META", theme.ACCENT_RAMP[700]))
        return card


# ── History ─────────────────────────────────────────────────────────────────
class _RunRow(QFrame):
    """One run: what was asked, which tools ran it, when, and how it ended.

    Keyboard reachable, which the old row was not — it was a bare QFrame with
    mousePressEvent monkey-patched onto the instance, so the entire History
    screen was unreachable without a mouse.
    """

    activated = Signal()

    def __init__(self, run: dict, state: str, parent=None):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        _focusable_row(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(C.MIN_TARGET + 22)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                               theme.SPACE_4, theme.SPACE_3)
        row.setSpacing(theme.SPACE_3)

        kind = _kind_of(run.get("title", ""))
        title = _plain_title(run.get("title", ""))

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        stack.addWidget(_Elided(title, "SUPPORT", theme.TEXT, weight=500))

        under = QHBoxLayout()
        under.setContentsMargins(0, 0, 0, 0)
        under.setSpacing(theme.SPACE_1)
        tools = run.get("tools") or []
        # Three badges at most. Six of them is 130px of fixed width fighting
        # the title for the row, and the names are spelled out beside them.
        for tool in tools[:3]:
            under.addWidget(C.ToolBadge(tool, 18, theme.R_MICRO))
        if tools:
            under.addSpacing(theme.SPACE_1)
        under.addWidget(_Elided(" · ".join(tools) or i18n.t("No tool recorded"),
                                "META"), stretch=1)
        stack.addLayout(under)
        row.addLayout(stack, stretch=1)

        if kind:
            row.addWidget(C.Pill(i18n.t(ADDONS[kind]), "info"))
        row.addWidget(_Elided(run.get("when", ""), "META", grow=False,
                              min_w=76, max_w=118))
        detail = i18n.t("never ran") if state == "cancelled" else ""
        row.addWidget(C.StatusBadge(state, detail, focusable=False))

        self.setAccessibleName(f"{title}. {run.get('when', '')}")
        self.setToolTip(run.get("title", "") or title)

    def mousePressEvent(self, event):
        self.activated.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)


class _AbortedRow(QFrame):
    """A run of consecutive never-started records, folded into one line.

    Six identical "Untitled task / No tool recorded / Failed" rows is what
    made History look broken; on this machine there are eighty-six. Nothing is
    hidden — the count is stated, the "Never ran" filter chip lists them
    individually, and clicking here expands them in place.
    """

    expand = Signal()

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        _focusable_row(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(C.MIN_TARGET + 22)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                               theme.SPACE_4, theme.SPACE_3)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad("archive", theme.NEUTRAL[600], 26,
                                theme.R_CHIP, 14))
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        stack.addWidget(_Elided(
            i18n.t("{n} runs that never started").format(n=count),
            "SUPPORT", theme.TEXT, weight=500))
        stack.addWidget(_Elided(
            i18n.t("No task text and no tool was recorded for any of them."),
            "META"))
        row.addLayout(stack, stretch=1)
        row.addWidget(C.button(i18n.t("Show them"), "tertiary",
                               icon_name="chevron-down",
                               on_click=self.expand.emit))

        self.setAccessibleName(i18n.t("{n} runs that never started").format(
            n=count))

    def mousePressEvent(self, event):
        self.expand.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.expand.emit()
            return
        super().keyPressEvent(event)


class HistoryPanel(_Page):
    """Every run, grouped by date, searchable and filterable by outcome.

    Reads the disk only when the screen is opened. MainWindow builds all
    eleven screens inside its own __init__, and this one used to open forty
    JSON files there — on a shared or synced workspace folder that is startup
    latency for a screen nobody has asked for yet.
    """

    TITLE = "History"
    BLURB = "Every past run, re-rendered out of its stored record."

    open_run = Signal(str)          # path of the run record
    navigate = Signal(str)          # a key for MainWindow._handle_command

    LAZY = True
    LIMIT = 200
    COLLAPSE_AT = 3                 # fold this many consecutive aborts

    def __init__(self, cfg: dict = None, parent=None):
        self._runs = []
        self._expanded = set()
        self._chips = None
        self._chip_counts = None
        super().__init__(cfg, parent)

    def header_actions(self):
        return [C.button(i18n.t("New task"), "primary", icon_name="plus",
                         on_click=lambda: self.navigate.emit("workbench"))]

    def build(self):
        self._runs = DATA.recent_runs(self.cfg, self.LIMIT) or []
        self._expanded = set()
        self._chips = None
        self._chip_counts = None

        bar = C.Toolbar()
        self._search = C.SearchField(
            i18n.t("Search a task, or a tool that ran it"))
        self._search.changed.connect(lambda _text: self._render())
        bar.add(self._search, stretch=1)
        self._count = C.label("", role="meta")
        bar.add(self._count)
        self._col.addWidget(bar)

        self._chip_host = QWidget()
        self._chip_col = QVBoxLayout(self._chip_host)
        self._chip_col.setContentsMargins(0, 0, 0, 0)
        self._chip_col.setSpacing(0)
        self._col.addWidget(self._chip_host)

        self._list = QWidget()
        self._list_col = QVBoxLayout(self._list)
        self._list_col.setContentsMargins(0, 0, 0, 0)
        self._list_col.setSpacing(theme.CARD_GAP)
        self._col.addWidget(self._list, stretch=1)
        self._render()

    # -- filters ----------------------------------------------------------
    def _sync_chips(self, counts: dict):
        """Rebuilt only when the COUNTS change, never on a click — a chip row
        that deletes itself from inside its own clicked handler is a crash
        waiting for a slow machine."""
        if self._chips is not None and counts == self._chip_counts:
            return
        current = self._chips.current() if self._chips else "all"
        self._chip_counts = dict(counts)
        self._drop(self._chip_col)
        self._chips = C.FilterChips([
            ("all", i18n.t("All"), counts["all"]),
            ("completed", i18n.t("Completed"), counts["completed"]),
            ("failed", i18n.t("Failed"), counts["failed"]),
            ("cancelled", i18n.t("Never ran"), counts["cancelled"]),
        ], current)
        self._chips.changed.connect(lambda _value: self._render())
        self._chip_col.addWidget(self._chips)

    def _hits(self, run: dict, query: str) -> bool:
        parts = [(run.get("title") or "").lower()]
        parts += [t.lower() for t in (run.get("tools") or [])]
        kind = _kind_of(run.get("title", ""))
        if kind:
            parts.append(ADDONS[kind].lower())
        return any(query in part for part in parts)

    # -- render -----------------------------------------------------------
    def _render(self):
        self._drop(self._list_col)
        runs = self._runs
        counts = {"all": len(runs), "completed": 0, "failed": 0, "cancelled": 0}
        states = []
        for run in runs:
            state = _state_of(run)
            states.append(state)
            counts[state] += 1
        self._sync_chips(counts)

        want = self._chips.current() if self._chips else "all"
        query = (self._search.text() or "").strip().lower()
        rows = [(run, state) for run, state in zip(runs, states)
                if (want == "all" or state == want)
                and (not query or self._hits(run, query))]
        self._count.setText(i18n.t("{shown} of {total} runs").format(
            shown=len(rows), total=len(runs)))

        if not runs:
            self._list_col.addWidget(C.EmptyState(
                "inbox", i18n.t("No runs yet"),
                i18n.t("Every task you start is kept here — what you asked "
                       "for, which tools ran it, and what came back. Use "
                       "“New task” at the top of this screen to begin.")),
                stretch=1)
            return
        if not rows:
            self._list_col.addWidget(C.EmptyState(
                "search", i18n.t("Nothing matches that"),
                i18n.t("Try a different word, or show every run again.")),
                stretch=1)
            return

        groups: list[tuple[str, list]] = []
        for run, state in rows:
            bucket = _bucket(run.get("when", ""), run.get("stamp", 0.0))
            if not groups or groups[-1][0] != bucket:
                groups.append((bucket, []))
            groups[-1][1].append((run, state))

        folding = want == "all" and not query
        for bucket, items in groups:
            self._list_col.addWidget(C.SectionHeader(
                i18n.t(bucket),
                i18n.t("1 run") if len(items) == 1
                else i18n.t("{n} runs").format(n=len(items))))
            card = C.Card()
            col = card.body((0, 0, 0, 0), spacing=0)

            # Real work first, in date order; the runs that never started
            # gathered into ONE row at the foot of the group.
            #
            # This used to fold each CONSECUTIVE stretch of aborts where it
            # sat, which on real data produced folds of 52, then 3, then 11
            # scattered between single real runs — and because a fold row
            # carries no date, the column read as though it had no order at
            # all. Aborted runs are also the overwhelming majority here (66 of
            # 82, every one the same Chrome failure), so leaving them inline
            # buried the fifteen runs that actually did something.
            #
            # Nothing is hidden: the count is stated, "Show them" expands the
            # group, and the "Never ran" chip lists them on their own.
            aborted = sum(1 for _r, s in items if s == "cancelled")
            fold_them = (folding and bucket not in self._expanded
                         and aborted >= self.COLLAPSE_AT)
            shown = ([(r, s) for r, s in items if s != "cancelled"]
                     if fold_them else items)

            first = True
            for run, state in shown:
                if not first:
                    col.addWidget(C.hairline())
                row = _RunRow(run, state)
                row.activated.connect(
                    lambda p=run.get("path", ""): p and self.open_run.emit(p))
                col.addWidget(row)
                first = False
            if fold_them:
                if not first:
                    col.addWidget(C.hairline())
                fold = _AbortedRow(aborted)
                fold.expand.connect(lambda b=bucket: self._expand(b))
                col.addWidget(fold)
            self._list_col.addWidget(card)
        self._list_col.addStretch(1)

    def _expand(self, bucket: str):
        self._expanded.add(bucket)
        self._render()


# ── the add-on front doors ──────────────────────────────────────────────────
class _AddonFrontDoor(_Page):
    """One add-on as a product module: what it does, what it has produced on
    this machine, and the way in.

    Built to be subclassed — set the class attributes, and override
    status_block() if the add-on knows something real about its own
    configuration (EmailPanel does; it knows the sending address). Every
    add-on screen should come through here rather than copying the layout: the
    inquiry screen has its own hand-copied version of the old one-card shape
    and that is exactly how six screens drifted apart in the first place.

    Recent activity is read, not invented. Add-on dialogs stamp the run record
    they save with their own prefix, so an add-on can recognise its own work
    in the same store History reads.
    """

    ICON = "file"
    HUE = None
    HEADLINE = ""
    DETAIL = ""
    ACTION = ""
    ACTION_ICON = "paperclip"
    STEPS = []                  # [(icon, title, body)] — what it actually does
    # [(example ask, the note beside it)]. Lifted verbatim from the add-on
    # dialog's own AskPanel placeholder, so the front door and the dialog
    # cannot end up teaching two different things — "what do I actually type"
    # is the first question every one of these gets, and the answer used to
    # only exist inside a modal you had to open to read it.
    PLACEHOLDERS = []
    KIND = ""                   # the run-record prefix key in _RUN_PREFIXES

    LAZY = True
    RELOAD_ON_SHOW = True       # a run finished in the dialog must show here
    # How far back to look for this add-on's own work. The same depth History
    # reads, because an add-on used twice a month is otherwise buried under a
    # month of workbench runs and its screen says "nothing yet" while its
    # output sits in History two screens away. Paid for only when the screen
    # is actually opened — see _Page.LAZY.
    SCAN = 200

    opened = Signal()
    open_run = Signal(str)      # path of a run record, same as History's
    navigate = Signal(str)      # a key for MainWindow._handle_command

    def header_actions(self):
        return [
            C.button(i18n.t("AI tools"), "secondary", icon_name="grid",
                     on_click=lambda: self.navigate.emit("agents")),
            C.button(i18n.t(self.ACTION), "primary",
                     icon_name=self.ACTION_ICON,
                     on_click=self.opened.emit),
        ]

    # -- overridable ------------------------------------------------------
    def status_block(self) -> QWidget | None:
        """Something the add-on genuinely knows about its own setup, shown on
        the right of the banner. None if it knows nothing."""
        return None

    def tool_roles(self) -> list:
        """[(icon, what it does, why that one, the tool)] — which of the
        user's own configured tools this add-on will actually reach for.

        Not a guess. Every add-on dialog picks its agent by a fixed rule off
        CB.config.active_agents(cfg) and refuses to run if the rule finds
        nothing, so the answer is knowable before you open the dialog — and
        "No writing agent set up yet" arriving as a modal AFTER you attached
        a drawing is the wrong moment to learn it.

        It is also the join the owner asked for: the add-ons stop being
        separate products the moment the screen says which of your tools runs
        them, in the same badge the AI tools screen uses.
        """
        return []

    def _agents(self) -> dict:
        """The user's configured tools, by category — the same call the
        add-on dialogs make when they choose one."""
        try:
            return CB.config.active_agents(self.cfg) or {}
        except Exception:                                   # noqa: BLE001
            return {stage: tool
                    for stage, tool in (self.cfg.get("agents") or {}).items()
                    if tool}

    # -- build ------------------------------------------------------------
    def build(self):
        runs = self._recent()
        self._col.addWidget(self._banner(runs))

        # Activity first — it is the only part of this screen that changes,
        # and on a module somebody uses weekly it is the reason they came.
        # The two static sections then sit UNDER it and carry the rest of the
        # page height, which is what stops a screen with one run from being
        # one row over a 400px grey field.
        self._col.addWidget(C.SectionHeader(
            i18n.t("Recent runs"),
            i18n.t("Read back out of the stored records, same as History.")))
        if runs:
            card = C.Card()
            col = card.body((0, 0, 0, 0), spacing=0)
            for i, run in enumerate(runs):
                if i:
                    col.addWidget(C.hairline())
                row = _RunRow(run, _state_of(run))
                row.activated.connect(
                    lambda p=run.get("path", ""): p and self.open_run.emit(p))
                col.addWidget(row)
            self._col.addWidget(card)
        else:
            # The shared EmptyState, but added WITHOUT a stretch factor. It
            # still centres itself in the height it is given; it is simply not
            # given four hundred pixels of it, because there are two sections
            # of real content underneath that use the space better than a
            # centred sentence would. One sentence for all three add-ons, and
            # it names this screen's own primary button rather than pointing
            # vaguely "above" — the header action is the only primary here, so
            # the empty state carries no second button of its own.
            self._col.addWidget(C.EmptyState(
                self.ICON, i18n.t("Nothing yet"),
                i18n.t(self.DETAIL) + " " + i18n.t(
                    "Use “{action}” at the top of this screen to start one."
                ).format(action=i18n.t(self.ACTION))))

        if self.STEPS:
            self._col.addWidget(C.SectionHeader(
                i18n.t("How it works"),
                i18n.t("Every step happens on this machine unless it says "
                       "otherwise.")))
            grid = C.CardGrid(min_col_width=246)
            grid.add_all([self._step_card(i + 1, icon, title, body)
                          for i, (icon, title, body) in enumerate(self.STEPS)])
            self._col.addWidget(grid)

        roles = self.tool_roles()
        if roles:
            self._col.addWidget(C.SectionHeader(
                i18n.t("Which of your tools it uses"),
                i18n.t("Picked from your own list, by a fixed rule. The "
                       "add-on will not run without them.")))
            grid = C.CardGrid(min_col_width=300)
            grid.add_all([self._role_card(icon, title, note, tool)
                          for icon, title, note, tool in roles])
            self._col.addWidget(grid)

        if self.PLACEHOLDERS:
            self._col.addWidget(C.SectionHeader(
                i18n.t("What you can ask for"),
                i18n.t("The same examples the dialog itself offers.")))
            asks = C.CardGrid(min_col_width=310)
            asks.add_all([self._example_card(text, note)
                          for text, note in self.PLACEHOLDERS])
            self._col.addWidget(asks)
        self._col.addStretch(1)

    def _role_card(self, icon: str, title: str, note: str,
                   tool: str) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad(icon, self.HUE or theme.ACCENT, 30,
                                theme.R_CONTROL, 15), alignment=Qt.AlignTop)
        top.addWidget(_wrapped(i18n.t(title), "CARD_TITLE"), stretch=1)
        col.addLayout(top)
        col.addWidget(_wrapped(i18n.t(note), "META"))
        col.addWidget(C.hairline())
        col.addWidget(_tool_line(tool))
        return card

    def _example_card(self, text: str, note: str) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad("mic", self.HUE or theme.ACCENT, 26,
                                theme.R_CHIP, 14), alignment=Qt.AlignTop)
        top.addWidget(_wrapped("“" + i18n.t(text) + "”", "SUPPORT", theme.TEXT),
                      stretch=1)
        col.addLayout(top)
        col.addWidget(_wrapped(i18n.t(note), "META"))
        return card

    def _recent(self, limit: int = 8) -> list:
        try:
            runs = DATA.recent_runs(self.cfg, self.SCAN) or []
        except Exception:                                   # noqa: BLE001
            return []
        return [run for run in runs
                if _kind_of(run.get("title", "")) == self.KIND][:limit]

    def _banner(self, runs: list) -> QWidget:
        hue = self.HUE or theme.ACCENT
        card = C.Card()
        row = QHBoxLayout(card)
        row.setContentsMargins(theme.CARD_PAD, theme.CARD_PAD,
                               theme.CARD_PAD, theme.CARD_PAD)
        row.setSpacing(theme.SPACE_5)
        row.addWidget(C.IconPad(self.ICON, hue, 52, theme.R_CARD, 24),
                      alignment=Qt.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        col.addWidget(_wrapped(i18n.t(self.HEADLINE), "SECTION"))
        col.addWidget(_wrapped(i18n.t(self.DETAIL), "SUPPORT"))
        row.addLayout(col, stretch=1)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(theme.SPACE_2)
        side.setAlignment(Qt.AlignTop | Qt.AlignRight)
        extra = self.status_block()
        if extra is not None:
            side.addWidget(extra, alignment=Qt.AlignRight)
        if runs:
            side.addWidget(C.Pill(
                i18n.t("1 run here") if len(runs) == 1
                else i18n.t("{n} runs here").format(n=len(runs)), "neutral"),
                alignment=Qt.AlignRight)
        row.addLayout(side)
        return card

    def _step_card(self, index: int, icon: str, title: str, body: str):
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad(icon, self.HUE or theme.ACCENT, 30,
                                theme.R_CONTROL, 15))
        top.addWidget(C.kicker(f"{index:02d}"), stretch=1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t(title), "CARD_TITLE"))
        col.addWidget(_wrapped(i18n.t(body), "META"))
        return card


class BoqPanel(_AddonFrontDoor):
    TITLE = "BOQ"
    BLURB = ("Quantities off a CAD drawing, or a written spec. Prism counts "
             "and measures — you price it.")
    ICON = "file"
    HEADLINE = "Attach a drawing or spec to begin"
    DETAIL = "DXF, PDF, or a written list of what's needed."
    ACTION = "Attach a file"
    KIND = "boq"

    STEPS = [
        ("paperclip", "Attach the drawing",
         "A DXF, a PDF, or nothing at all — a written description of what is "
         "needed works on its own."),
        ("chart", "Prism measures it",
         "Counts and lengths are taken locally by Prism's own geometry "
         "engine. No AI sees the drawing at this step."),
        ("file", "You get a checkable CSV",
         "Every measured figure is written to a CSV before anything is "
         "generated, so you can audit the numbers."),
        ("pencil", "Then it is written up",
         "The measured numbers go to your writing tool, which turns them "
         "into the document you send."),
    ]

    PLACEHOLDERS = [
        ("BOQ for CCTV, cabling and fibre for this site",
         "Attach the drawing and Prism measures it."),
        ("materials to build one 36x24 jaw crusher, 100 TPH",
         "No drawing needed — the quantities come out of the words."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors BoqDialog._run() exactly — writer, researcher, interpreter."""
        agents = self._agents()
        writer = next((agents[s] for s in ("content", "brains")
                       if agents.get(s)), "")
        return [
            ("pencil", "Writes the BOQ up",
             "Your Writing tool, or Reasoning if you have not set one.",
             writer),
            ("book", "Checks the trade standard",
             "Your Research tool, falling back to Reasoning — used when you "
             "leave “derive from standards” switched on.",
             agents.get("research") or agents.get("brains") or ""),
            ("image", "Reads a drawing screenshot",
             "ChatGPT specifically, and only when you attach an image for it "
             "to read the legend and scope off.",
             "ChatGPT"),
        ]


class BomPanel(_AddonFrontDoor):
    TITLE = "BOM"
    BLURB = ("The parts list to fabricate it — off a CAD drawing, or a written "
             "spec. Prism counts and measures the parts; you price them.")
    ICON = "list"
    HEADLINE = "Attach a fabrication drawing or spec to begin"
    DETAIL = "DXF, PDF, or a written description of what is built."
    ACTION = "Attach a file"
    KIND = "bom"

    STEPS = [
        ("paperclip", "Attach the drawing",
         "A DXF or PDF general-arrangement drawing — or nothing at all, a "
         "written description of the assembly works on its own."),
        ("chart", "Prism measures the parts",
         "Part counts, cut lengths and plate areas are taken locally by "
         "Prism's own geometry engine. No AI sees the drawing at this step."),
        ("file", "You get a checkable CSV",
         "Every measured figure is written to a CSV before anything is "
         "generated, so you can audit the take-off."),
        ("pencil", "Then the BOM is written up",
         "The measured parts go to your writing tool, which turns them into a "
         "grouped Bill of Materials with materials and grades."),
    ]

    PLACEHOLDERS = [
        ("Parts list to fabricate this over-band magnetic separator",
         "Attach the GA drawing and Prism measures the parts."),
        ("BOM for one 36x24 jaw crusher, 100 TPH",
         "No drawing needed — the parts come out of the words."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors BoqDialog(mode='bom')._run() — writer, researcher, interpreter."""
        agents = self._agents()
        writer = next((agents[s] for s in ("content", "brains")
                       if agents.get(s)), "")
        return [
            ("pencil", "Writes the BOM up",
             "Your Writing tool, or Reasoning if you have not set one.",
             writer),
            ("book", "Checks material grades & sizes",
             "Your Research tool, falling back to Reasoning — used when you "
             "leave “derive from standards” switched on.",
             agents.get("research") or agents.get("brains") or ""),
            ("image", "Reads a drawing screenshot",
             "ChatGPT specifically, and only when you attach an image for it "
             "to read the legend and scope off.",
             "ChatGPT"),
        ]


class GerberPanel(_AddonFrontDoor):
    TITLE = "Gerber"
    BLURB = ("PCB size, track width & spacing, drill size and count — "
             "measured from the Gerber files, not guessed.")
    ICON = "file"
    HEADLINE = "Drop a Gerber job to begin"
    DETAIL = ("A .zip or .rar exactly as the customer sent it — the design "
              "is measured here and never leaves this machine.")
    ACTION = "Attach a job"
    KIND = "gerber"

    STEPS = [
        ("paperclip", "Drop the job",
         "A .zip or .rar exactly as the customer sent it. Nothing has to be "
         "unpacked or renamed first."),
        ("chart", "Measured on this machine",
         "Board size, track width and spacing, drill sizes and counts — read "
         "out of the Gerber files by Prism itself."),
        ("lock", "The design never leaves",
         "Only the measured numbers are handed to the AI stage. The Gerber "
         "files are never attached to anything."),
        ("pencil", "Then a quote or a spec",
         "Ask for a fabrication note, a price breakdown or a customer reply "
         "— written from the numbers alone."),
    ]

    PLACEHOLDERS = [
        ("reply with our price for 500 pieces",
         "Optional. Say what to do with the numbers once they are measured "
         "— or leave it blank and just take the five figures. Measuring "
         "starts the moment the file lands, either way."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors GerberDialog._write_up() — one writer, and it is shown
        nothing but the numbers."""
        agents = self._agents()
        return [
            ("pencil", "Writes the numbers up",
             "Your Writing tool, or Reasoning if you have not set one. It is "
             "handed the five measured figures and nothing else — never a "
             "file and never a path.",
             next((agents[s] for s in ("content", "brains")
                   if agents.get(s)), "")),
        ]


# EmailPanel lives in widgets/email_panel.py now — a launcher in the shape
# of the Email-automation screen, not a brochure. Re-exported here so the
# import path the rest of the app and the tests use keeps working.
from widgets.email_panel import EmailPanel  # noqa: E402,F401
