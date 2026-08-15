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
import i18n
import theme
from widgets import icons
from widgets.controls import StepMark, ToolChip, elevate, heading, meta

# stage -> (icon, plain title, plain one-liner)
STAGE_COPY = {
    "research":     ("search",  "Look things up",   "Find the facts and sources this needs"),
    "leads":        ("user",    "Find the people",  "Companies to approach, with verified emails"),
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
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        elevate(self, theme.SHADOW_CARD)

        icon_name, title, blurb = STAGE_COPY.get(
            stage, ("grid", meta_data.get("label", stage), meta_data.get("desc", "")))

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)

        self.mark = StepMark(included)
        self.mark.setToolTip("Click to leave this step out of the run")
        row.addWidget(self.mark)

        self._icon_name = icon_name
        self.glyph = QLabel()
        self.glyph.setPixmap(icons.pixmap(icon_name, 18, theme.ACCENT))
        row.addWidget(self.glyph)

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
        self.blurb = QLabel(blurb)
        self.blurb.setObjectName("meta")
        self.blurb.setWordWrap(True)
        text.addWidget(self.blurb)
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
        self.name.setStyleSheet(
            "" if included else f"color: {theme.NEUTRAL[500]};")
        self.chip.setEnabled(included)
        self.blurb.setStyleSheet(
            "" if included else f"color: {theme.NEUTRAL[400]};")
        self.glyph.setPixmap(icons.pixmap(
            self._icon_name, 18,
            theme.ACCENT if included else theme.NEUTRAL[400]))
        # The row keeps its card shape and loses its lift instead. Swapping it
        # for an outlined box changed the shape of the list every time a step
        # was dropped, which made the plan feel like it was being rebuilt
        # rather than edited.
        #
        # Expressed in colour, not opacity: a widget can hold only one
        # QGraphicsEffect, and the shadow is already using it.
        effect = self.graphicsEffect()
        if effect is not None:
            effect.setEnabled(included)
        self.setStyleSheet(
            "" if included
            else f"#row {{ background: {theme.NEUTRAL[100]};"
                 f" border-radius: 11px; }}")

    def selected_agent(self) -> str | None:
        return self.chip.current()

    def is_checked(self) -> bool:
        return self._included


class AgentsPanel(QWidget):
    run_requested = Signal()
    discard_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[PlanRow] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(11)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(heading(i18n.t("Your plan"), level=5), stretch=1)
        self.count = meta("")
        head.addWidget(self.count)
        root.addLayout(head)

        self.empty = QLabel(i18n.t(
            "Describe a task above and press Make a plan — Prism will lay "
            "them out here, and you can drop any of them before it runs."))
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        rows_wrap = QWidget()
        self.rows_box = QVBoxLayout(rows_wrap)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(9)
        root.addWidget(rows_wrap)

        self.run_btn = QPushButton(f"  {i18n.t('Start the work')}")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setMinimumHeight(44)
        icons.button_icon(self.run_btn, "play", 15, "#ffffff")
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip(i18n.t(
            "Make a plan first — this fills in once Prism picks the steps."))
        self.run_btn.clicked.connect(self.run_requested.emit)

        # "Start the work" is the commitment; this is the way back out of it.
        # Without it a plan you did not want could only be escaped by editing
        # the task and re-planning over the top, which is not obviously
        # possible and leaves the old plan armed in the meantime.
        # A widget, not a bare layout, so the window can lift it out of the
        # scrolling column and pin it — see main_window._work_column.
        self.cta = QWidget()
        cta = QHBoxLayout(self.cta)
        cta.setContentsMargins(0, 0, 0, 0)
        cta.setSpacing(9)
        cta.addWidget(self.run_btn, stretch=1)
        self.discard_btn = QPushButton(f" {i18n.t('Discard')}")

        self.discard_btn.setCursor(Qt.PointingHandCursor)
        self.discard_btn.setMinimumHeight(44)
        self.discard_btn.setToolTip(
            "Throws these steps away and clears the task, ready for a new "
            "one. Your attached files stay.")
        icons.button_icon(self.discard_btn, "trash", 15, theme.NEUTRAL[600])
        self.discard_btn.clicked.connect(self.discard_requested.emit)
        self.discard_btn.setVisible(False)
        cta.addWidget(self.discard_btn)
        root.addWidget(self.cta)

    # ── state ─────────────────────────────────────────────────────────────
    def set_run_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled)
        self.run_btn.setToolTip(
            i18n.t("Runs every step still switched on.") if enabled else
            i18n.t("Make a plan first — this fills in once Prism picks the "
                   "steps."))
        # Discard only exists while there are steps to discard.
        self.discard_btn.setVisible(enabled)
        # The whole bar goes with it: pinned to the foot of the column, an
        # always-present Start button on an empty bench is a dead control
        # occupying the most valuable strip on the screen.
        self.cta.setVisible(enabled)

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
            # Assembled through t() rather than as an f-string: by the time an
            # f-string reaches setText the sentence is already built and
            # matches nothing in the catalogue. Two forms because the singular
            # and plural are different sentences in most languages, and the
            # placeholders are named so a translator can reorder them.
            # Both literals sit inside a t() call rather than being chosen
            # into a variable first: devtools/extract_strings.py reads the
            # source, so a key it cannot see never reaches a translator.
            self.count.setText(
                (i18n.t("{n} step of {total}") if on == 1
                 else i18n.t("{n} steps of {total}")
                 ).format(n=on, total=len(self._rows)))
        self.set_run_enabled(on > 0)

    def selected_agents(self) -> dict:
        """{stage: agent_name} for every step still switched on — feed straight
        into automation.run() as the run's agent overrides."""
        return {r.stage: r.selected_agent() for r in self._rows if r.is_checked()}
