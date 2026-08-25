"""AgentsPicker — one combo box per pipeline category, shared by SetupDialog
and the first-run wizard so "which tool handles which kind of step" has one
implementation instead of two that can drift apart.

Deliberately owns no chrome (no Card, no kicker, no surrounding Section) —
SetupDialog wraps it in its own card, the wizard wraps it in a plain page.
Only the form of combos is this widget's job; how it's framed is the host's.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

import core_bridge as CB
from widgets.agents_panel import STAGE_COPY
from widgets.controls import icon_label

SKIP = "— skip this category —"


class AgentsPicker(QWidget):
    picked_changed = Signal()

    def __init__(self, initial: dict | None = None, parent=None):
        super().__init__(parent)
        self._combos: dict[str, QComboBox] = {}
        current = dict(initial or {})

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Pipeline order, not dict order — these rows should read in the same
        # sequence the plan lists them in.
        for cat in [c for c in CB.agents.PIPELINE_ORDER if c in CB.agents.CATEGORIES]:
            meta = CB.agents.CATEGORIES[cat]
            combo = QComboBox()
            combo.addItems(list(meta["agents"]) + [SKIP])
            default = current.get(cat)
            combo.setCurrentText(default if default in meta["agents"] else SKIP)
            # Not .connect(self.picked_changed.emit) directly: PySide6 passes
            # currentIndexChanged's int through to the connected slot, and a
            # zero-arg Signal's bound emit() raises on an unexpected argument
            # rather than dropping it, the way a plain Python slot would.
            combo.currentIndexChanged.connect(
                lambda _index=None: self.picked_changed.emit())
            combo.setToolTip(meta.get("desc", ""))
            self._combos[cat] = combo
            # The plan calls this step "Build the slides"; every picker
            # should name the same thing the same way, with the same icon.
            icon_name, title, _ = STAGE_COPY.get(cat, ("grid", meta["label"], ""))
            form.addRow(icon_label(icon_name, title), combo)

    def current_agents(self) -> dict:
        return {cat: combo.currentText() for cat, combo in self._combos.items()
                if combo.currentText() != SKIP}

    def combos(self) -> list[QComboBox]:
        return list(self._combos.values())
