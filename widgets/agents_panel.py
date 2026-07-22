"""The plan — what Prism is going to do, as a list of steps you can edit.

This is direction 1b's centre of gravity: one row per stage, each with a
square include-marker, a line icon, a plain-English name, one line of what it
means, and the tool that will run it as a clickable chip. Everything the old
checkbox+combo row did, minus the form-ness.

The stage keys are the engine's own (research / brains / content / …); the
titles here are the human translation the design asks for — a step is named
after what it does for you, not after the category it came from."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QPushButton,
)

import core_bridge as CB
import theme
from widgets import icons
from widgets.controls import StepMark, ToolChip, heading, meta

# stage -> (icon, plain title, plain one-liner)
STAGE_COPY = {
    "research":     ("search",  "Look things up",   "Find the facts and sources this needs"),
    "brains":       ("bulb",    "Think it through", "Work out the angle and the argument"),
    "content":      ("pencil",  "Write it up",      "Turn the thinking into clear words"),
    "visual":       ("image",   "Make the images",  "Generate the artwork to go with it"),
    "media":        ("video",   "Make the video",   "Produce the video or audio piece"),
    "development":  ("code",    "Build the tool",   "Stand up the app or page itself"),
    "presentation": ("present", "Build the slides", "A clean deck, ready to present"),
    "summary":      ("list",    "Pull it together", "Fold every step into one answer"),
}


class PlanRow(QFrame):
    toggled = Signal()

    def __init__(self, stage: str, meta_data: dict, current: str, included: bool,
                 suggested: str | None, forced: str | None, parent=None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("row")
        self.setCursor(Qt.PointingHandCursor)

        icon_name, title, blurb = STAGE_COPY.get(
            stage, ("grid", meta_data.get("label", stage), meta_data.get("desc", "")))

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(13)

        self.mark = StepMark(included)
        self.mark.setToolTip("Click to leave this step out of the run")
        row.addWidget(self.mark)

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 18, theme.ACCENT))
        row.addWidget(glyph)

        text = QVBoxLayout()
        text.setSpacing(1)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.name = QLabel(title)
        self.name.setObjectName("h5")
        head.addWidget(self.name)
        if forced:
            head.addWidget(self._tag("You picked this", "tagOutline"))
        elif suggested and suggested != current:
            head.addWidget(self._tag("Suggested", "tagAccent"))
        head.addStretch(1)
        text.addLayout(head)
        blurb_label = QLabel(blurb)
        blurb_label.setObjectName("meta")
        blurb_label.setWordWrap(True)
        text.addWidget(blurb_label)
        row.addLayout(text, stretch=1)

        tools = meta_data.get("agents", []) or ([current] if current else [])
        self.chip = ToolChip(tools, forced or current, suggested or "")
        self.chip.setToolTip("Click to run this step with a different tool")
        row.addWidget(self.chip)

        self._included = included

    @staticmethod
    def _tag(text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName(style)
        return lbl

    def mousePressEvent(self, event):
        """The whole row is the switch — clicking anywhere but the tool chip
        includes or drops the step."""
        if event.button() == Qt.LeftButton:
            self.set_included(not self._included)
            self.toggled.emit()
        super().mousePressEvent(event)

    def set_included(self, included: bool):
        self._included = included
        self.mark.set_included(included)
        self.setObjectName("row" if included else "rowMuted")
        self.style().unpolish(self)
        self.style().polish(self)
        self.name.setStyleSheet(
            "" if included else f"color: {theme.NEUTRAL[500]};")
        self.chip.setEnabled(included)

    def selected_agent(self) -> str | None:
        return self.chip.current()

    def is_checked(self) -> bool:
        return self._included


class AgentsPanel(QWidget):
    run_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[PlanRow] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(11)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(heading("Your plan"), stretch=1)
        self.count = meta("")
        head.addWidget(self.count)
        root.addLayout(head)

        self.empty = QLabel(
            "Describe a task above and press Make a plan — Prism will lay out "
            "the steps here, and you can drop any of them before it runs.")
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        rows_wrap = QWidget()
        self.rows_box = QVBoxLayout(rows_wrap)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(9)
        root.addWidget(rows_wrap)

        self.run_btn = QPushButton("  Start the work")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setMinimumHeight(44)
        icons.button_icon(self.run_btn, "play", 16, theme.BG)
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip("Make a plan first — this fills in once Prism picks the steps.")
        self.run_btn.clicked.connect(self.run_requested.emit)
        root.addWidget(self.run_btn)

    # ── state ─────────────────────────────────────────────────────────────
    def set_run_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled)
        self.run_btn.setToolTip(
            "Runs every step still switched on." if enabled else
            "Make a plan first — this fills in once Prism picks the steps.")

    def clear(self):
        self._rows = []
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.empty.setVisible(True)
        self.count.setText("")
        # With no rows there is nothing to run — leaving the CTA armed after a
        # wipe is exactly the stale-plan trap this clear() exists to avoid.
        # set_content re-enables it once the new rows are in.
        self.set_run_enabled(False)

    def set_content(self, routing: dict, agents_cfg: dict):
        self.clear()
        A = CB.agents
        suggestions = {s["stage"]: s["suggested"] for s in (routing.get("_suggestions") or [])}
        forced = routing.get("_named_tools") or {}
        for stage in A.PIPELINE_ORDER:
            if stage == "summary":
                continue
            data = routing.get(stage) or {}
            current = agents_cfg.get(stage)
            if not current:
                continue   # user never assigned a tool to this category at all
            needed = bool(data.get("needed") and data.get("questions"))
            row = PlanRow(stage, A.CATEGORIES.get(stage, {}), current, needed,
                          suggestions.get(stage), forced.get(stage))
            row.toggled.connect(self._refresh_count)
            self.rows_box.addWidget(row)
            self._rows.append(row)
        self.empty.setVisible(not self._rows)
        self.set_run_enabled(bool(self._rows))
        self._refresh_count()

    def _refresh_count(self):
        on = sum(1 for r in self._rows if r.is_checked())
        if not self._rows:
            self.count.setText("")
        else:
            self.count.setText(f"{on} step{'' if on == 1 else 's'} of {len(self._rows)}")
        self.set_run_enabled(on > 0)

    def selected_agents(self) -> dict:
        """{stage: agent_name} for every step still switched on — feed straight
        into automation.run() as the run's agent overrides."""
        return {r.stage: r.selected_agent() for r in self._rows if r.is_checked()}
