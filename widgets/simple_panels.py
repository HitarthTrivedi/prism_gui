"""The five lighter screens: Guide, History, AI tools, BOQ and Email.

The design gives these "lighter but real coverage" — they are destinations, not
workbenches, so each is a page header and one card. What matters is that they
are *screens*: a rail that switches the body for four destinations and throws a
modal for the other five teaches nothing consistent about where you are.

BOQ and Email keep their dialogs, because the dialogs are where the work
happens — attaching a drawing, picking recipients, watching a draft come back.
These screens are the front door: they say what the add-on is for and open it.
That is exactly the shape the design gives them.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import core_bridge as CB
import dashboard_data as DATA
import i18n
import theme
from widgets.controls import Card, IconPad, Pill, ToolBadge


def _label(text: str, role: str = "", size: float = 0, colour: str = "",
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


def _hairline() -> QFrame:
    line = QFrame()
    line.setObjectName("cardLine")
    line.setFixedHeight(1)
    return line


class _Page(QScrollArea):
    """Header, then whatever the subclass builds. Rebuilt on refresh()."""

    TITLE = ""
    BLURB = ""
    MAX_W = 1120

    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self.setWidget(self._host)
        outer = QHBoxLayout(self._host)
        outer.setContentsMargins(40, 32, 40, 32)
        holder = QWidget()
        holder.setMaximumWidth(self.MAX_W)
        self._col = QVBoxLayout(holder)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(18)
        outer.addWidget(holder, stretch=1)
        outer.addStretch(0)
        self.refresh()

    def refresh(self):
        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(i18n.t(self.TITLE), "h2"))
        if self.BLURB:
            head.addWidget(_label(i18n.t(self.BLURB), size=13,
                                  colour=theme.NEUTRAL[600], wrap=True))
        self._col.addLayout(head)
        self.build()
        self._col.addStretch(1)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    def build(self):
        raise NotImplementedError


class GuidePanel(_Page):
    TITLE = "How to use Prism"
    BLURB = "For someone who has never used AI before."
    MAX_W = 760

    CARDS = [
        ("Describe a job in your own words",
         "“Write a proposal for a 40-camera CCTV project.” Prism works out "
         "which AI tools are needed, uses them in order, and hands you the "
         "finished result."),
        ("Review the plan before it runs",
         "Every stage is shown as a plain-English step. Drop any you don't "
         "want, or send a step to a different tool."),
        ("The add-ons are purpose-built",
         "Email automation, BOQ and Email are dedicated tools for recurring "
         "jobs — they don't need a plan, just your files."),
        ("Prism's own language, and the AI's, are separate",
         "Set them independently in Settings — a Gujarati-speaking owner may "
         "still want the output in English."),
        # Not in the design, but the single most common support question: the
        # tools run in the customer's own Chrome, signed in as them, and
        # nobody guesses that from the outside.
        ("It drives your own browser",
         "Prism opens your Chrome and works the tools as you, using the "
         "accounts you already pay for. Nothing is sent to a Prism server."),
    ]

    def build(self):
        for title, body in self.CARDS:
            card = Card()
            col = card.body((20, 18, 20, 18), spacing=0)
            col.addWidget(_label(i18n.t(title), "h6"))
            col.addSpacing(6)
            col.addWidget(_label(i18n.t(body), size=13,
                                 colour=theme.NEUTRAL[700], wrap=True))
            self._col.addWidget(card)


class CatalogPanel(_Page):
    TITLE = "AI tools"
    BLURB = "Prism drives these in your own Chrome, signed in as you."

    open_directory = Signal()

    def build(self):
        grid = QVBoxLayout()
        grid.setSpacing(16)
        categories = CB.agents.CATEGORIES
        chosen = dict(self.cfg.get("agents") or {})
        # One card per category, naming the tool this copy is set up to use.
        # The design's grid is per-tool; per-category is the more useful cut
        # here because it is the same list Settings → Agents edits, so what
        # you read on one screen is what you change on the other.
        row = None
        for i, stage in enumerate(CB.agents.PIPELINE_ORDER):
            if stage == "summary":
                continue
            meta = categories.get(stage, {})
            if i % 3 == 0:
                row = QHBoxLayout()
                row.setSpacing(16)
                grid.addLayout(row)
            row.addWidget(self._tool_card(meta, chosen.get(stage)))
        if row is not None:
            for _ in range(3 - row.count()):
                row.addStretch(1)
        self._col.addLayout(grid)

    def _tool_card(self, meta: dict, tool: str | None) -> QWidget:
        card = Card()
        col = card.body((18, 18, 18, 18), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(10)
        if tool:
            head.addWidget(ToolBadge(tool, 28))
        head.addWidget(_label(tool or i18n.t("Not picked"), size=14.5,
                              weight=600), stretch=1)
        head.addWidget(Pill(i18n.t("In use") if tool else i18n.t("None"),
                            "accent" if tool else "quiet"))
        col.addLayout(head)
        col.addSpacing(10)
        col.addWidget(_label(meta.get("label", ""), size=12,
                             colour=theme.NEUTRAL[600], weight=600))
        col.addSpacing(2)
        col.addWidget(_label(meta.get("desc", ""), size=12.5,
                             colour=theme.NEUTRAL[600], wrap=True))
        return card


class HistoryPanel(_Page):
    TITLE = "History"
    BLURB = "Every past run, re-rendered out of its stored record."

    open_run = Signal(str)          # path of the run record

    def build(self):
        runs = DATA.recent_runs(self.cfg, 40)
        card = Card()
        col = card.body((0, 0, 0, 0), spacing=0)
        if not runs:
            empty = _label(
                i18n.t("No runs saved yet. Once Prism finishes a task, it "
                       "turns up here."), wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {theme.NEUTRAL[500]}; font-size: 13px;"
                " padding: 40px 20px;")
            col.addWidget(empty)
            self._col.addWidget(card)
            return
        for i, run in enumerate(runs):
            if i:
                col.addWidget(_hairline())
            col.addWidget(self._row(run))
        self._col.addWidget(card)

    def _row(self, run: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        wrap.setCursor(Qt.PointingHandCursor)
        wrap.mousePressEvent = lambda _e, p=run["path"]: self.open_run.emit(p)
        line = QHBoxLayout(wrap)
        line.setContentsMargins(18, 13, 18, 13)
        line.setSpacing(14)
        stack = QVBoxLayout()
        stack.setSpacing(1)
        title = _label(run["title"], size=13.5, weight=500)
        title.setToolTip(run["title"])
        stack.addWidget(title)
        stack.addWidget(_label(" · ".join(run["tools"]) or
                               i18n.t("No tool recorded"), "faint"))
        line.addLayout(stack, stretch=1)
        when = _label(run["when"], "faint")
        when.setFixedWidth(96)
        line.addWidget(when)
        line.addWidget(Pill(i18n.t("Done") if run["ok"] else i18n.t("Failed"),
                            "accent" if run["ok"] else "err"))
        return wrap


class _AddonFrontDoor(_Page):
    """A one-card front door: what the add-on does, and the way in."""

    ICON = "file"
    HUE = None
    HEADLINE = ""
    DETAIL = ""
    ACTION = ""
    MAX_W = 900

    opened = Signal()

    def build(self):
        card = Card(radius=theme.R_HERO)
        col = card.body((30, 40, 30, 44), spacing=0)
        col.setAlignment(Qt.AlignHCenter)
        col.addWidget(IconPad(self.ICON, self.HUE or theme.ACCENT, 56, 14, 26),
                      alignment=Qt.AlignHCenter)
        col.addSpacing(16)
        col.addWidget(_label(i18n.t(self.HEADLINE), size=15, weight=500),
                      alignment=Qt.AlignHCenter)
        col.addSpacing(6)
        detail = _label(i18n.t(self.DETAIL), size=13,
                        colour=theme.NEUTRAL[500], wrap=True)
        detail.setAlignment(Qt.AlignCenter)
        detail.setMaximumWidth(420)
        col.addWidget(detail, alignment=Qt.AlignHCenter)
        col.addSpacing(20)
        btn = QPushButton(i18n.t(self.ACTION))
        btn.setObjectName("primaryBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.opened.emit)
        col.addWidget(btn, alignment=Qt.AlignHCenter)
        self._col.addWidget(card)


class BoqPanel(_AddonFrontDoor):
    TITLE = "BOQ"
    BLURB = ("Quantities off a CAD drawing, or a written spec. Prism counts "
             "and measures — you price it.")
    ICON = "file"
    HEADLINE = "Attach a drawing or spec to begin"
    DETAIL = "DXF, PDF, or a written list of what's needed."
    ACTION = "Attach a file"

    def build(self):
        self.HUE = theme.ACCENT
        super().build()


class EmailPanel(_AddonFrontDoor):
    TITLE = "Email"
    BLURB = ("Draft & send from your own account — recipients from a CSV, or "
             "from the goal text.")
    ICON = "mail"
    HEADLINE = "Nothing drafted yet"
    DETAIL = "Attach a recipient list, or describe who this is for."
    ACTION = "Start a draft"

    def build(self):
        self.HUE = theme.WARN
        super().build()
