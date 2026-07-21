"""Panel: which agent runs each stage — a checkbox to run/skip the stage and
a dropdown of every tool in that category. The router's suggestion (if any)
is starred in the dropdown and pre-selected; an explicitly-named tool
("using NotebookLM…") is pre-selected and flagged as a direct request."""
from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QFrame,
    QPushButton,
)

import core_bridge as CB


class _StageRow(QFrame):
    def __init__(self, stage: str, meta: dict, current: str, needed: bool,
                 suggested: str | None, forced: str | None, parent=None):
        super().__init__(parent)
        self.stage = stage
        row = QHBoxLayout(self)
        self.checkbox = QCheckBox(f"{meta.get('emoji','')} {meta.get('label', stage)}")
        self.checkbox.setChecked(needed)
        row.addWidget(self.checkbox, stretch=1)

        self.combo = QComboBox()
        names = meta.get("agents", [])
        for n in names:
            label = n
            if n == suggested:
                label = f"★ {n} (suggested)"
            self.combo.addItem(label, n)
        pick = forced or current
        idx = names.index(pick) if pick in names else (names.index(current) if current in names else 0)
        if names:
            self.combo.setCurrentIndex(idx)
        row.addWidget(self.combo, stretch=2)

        if forced:
            note = QLabel("🗣️ you asked for this")
            note.setObjectName("dim")
            row.addWidget(note)
        elif suggested and suggested != current:
            note = QLabel("💡 router suggestion available")
            note.setObjectName("dim")
            row.addWidget(note)

    def selected_agent(self) -> str | None:
        return self.combo.currentData()

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()


class AgentsPanel(QWidget):
    run_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._rows: list[_StageRow] = []
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("Agents For This Task")
        title.setObjectName("panelTitle")
        head.addWidget(title, stretch=1)
        self.run_btn = QPushButton("▶  Run Pipeline")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.run_requested.emit)
        head.addWidget(self.run_btn)
        root.addLayout(head)
        self.rows_box = QVBoxLayout()
        wrap = QWidget()
        wrap.setLayout(self.rows_box)
        root.addWidget(wrap)

    def set_run_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled)

    def clear(self):
        self._rows = []
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

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
            row = _StageRow(stage, A.CATEGORIES.get(stage, {}), current, needed,
                            suggestions.get(stage), forced.get(stage))
            self.rows_box.addWidget(row)
            self._rows.append(row)
        self.set_run_enabled(bool(self._rows))

    def selected_agents(self) -> dict:
        """{stage: agent_name} for every CHECKED stage — feed straight into
        automation.run() as the run's agent overrides."""
        return {r.stage: r.selected_agent() for r in self._rows if r.is_checked()}
