"""A slim, always-visible progress indicator: Task -> Review -> Run -> Output.
Sits above the dock area so the user always knows where they are in the
pipeline, no matter how the dock widgets get dragged/floated/closed around
it. Purely presentational — main_window drives state via set_step()."""
from __future__ import annotations
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from widgets.effects import apply_glow

STEPS = [
    ("task", "Task"),
    ("review", "Review"),
    ("run", "Run"),
    ("output", "Output"),
]


class StepBar(QWidget):
    step_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stepBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 12, 2, 12)  # top/bottom room for the glow bloom
        row.setSpacing(6)

        self._chips: dict[str, QPushButton] = {}
        self._current = "task"
        self._done: set[str] = set()

        for i, (key, label) in enumerate(STEPS):
            chip = QPushButton(label)
            chip.setObjectName("stepChip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setFlat(True)
            # Fixed to its text width so the label never truncates when the
            # central column is narrow — only the connectors give up space.
            # (QSS padding isn't counted in sizeHint, so size it by hand.)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            chip.setFixedHeight(34)
            chip.setFixedWidth(QFontMetrics(chip.font()).horizontalAdvance(label) + 28)
            chip.clicked.connect(lambda _=False, k=key: self.step_clicked.emit(k))
            self._chips[key] = chip
            row.addWidget(chip)
            if i < len(STEPS) - 1:
                line = QLabel()
                line.setObjectName("stepConnector")
                line.setFixedHeight(2)
                line.setMinimumWidth(6)
                row.addWidget(line, stretch=1)

        row.addStretch(0)
        self._refresh()

    def set_step(self, key: str, done_before: bool = True):
        """Mark `key` as the active step. Every step before it in STEPS is
        marked done (unless done_before=False, e.g. resetting to "task")."""
        self._current = key
        if key == "task":
            self._done = set()
        elif done_before:
            idx = [k for k, _ in STEPS].index(key)
            self._done = {k for k, _ in STEPS[:idx]}
        self._refresh()

    def mark_done(self, key: str):
        self._done.add(key)
        self._refresh()

    def _refresh(self):
        for key, chip in self._chips.items():
            if key == self._current:
                state = "active"
            elif key in self._done:
                state = "done"
            else:
                state = "pending"
            chip.setProperty("state", state)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            # violet bloom follows the active step; cleared elsewhere
            if state == "active":
                apply_glow(chip, blur=26, alpha=130)
            else:
                chip.setGraphicsEffect(None)
