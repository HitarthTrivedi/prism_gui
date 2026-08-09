"""The task card — top of the workbench column.

A blueprint frame holding the kicker, a live state chip, the task itself as
plain 16px text you can edit in place, and the row of things you can do to it.
The mock shows the task as settled text with an [Edit] button; here the text
*is* the editor, so the button disappears and the affordance is just a caret."""
from __future__ import annotations
from PySide6.QtCore import Signal, QTimer, Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QTextEdit, QPushButton,
    QSizePolicy,
)

import theme
from widgets import icons
from widgets.blueprint import BlueprintFrame
from widgets.controls import Chip, kicker

# state key -> (chip text, icon, objectName)
_STATES = {
    "empty":   ("Waiting on you", "help",  "tagWarn"),
    "ready":   ("Ready to plan",  "check", "tagOk"),
    "routing": ("Planning…",      "clock", "tagWarn"),
    "planned": ("Ready to run",   "check", "tagOk"),
    "running": ("Working…",       "clock", "tagOk"),
    "done":    ("Finished",       "check", "tagOk"),
}


def _action(label: str, icon_name: str, tip: str = "") -> QPushButton:
    btn = QPushButton(f" {label}")
    btn.setObjectName("smallBtn")
    btn.setCursor(Qt.PointingHandCursor)
    icons.button_icon(btn, icon_name, 15, theme.TEXT)
    if tip:
        btn.setToolTip(tip)
    return btn


class _QueuedTaskRow(QFrame):
    """One task waiting its turn, with the number it will run in."""

    def __init__(self, index: int, text: str, on_remove, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        row.setSpacing(9)

        num = QLabel(str(index))
        num.setObjectName("tagNeutral")
        num.setAlignment(Qt.AlignCenter)
        num.setFixedWidth(22)
        row.addWidget(num)

        # Elide in the label rather than truncating the stored text: the queue
        # holds the real task, this only has to be recognisable at a glance.
        one_line = " ".join(text.split())
        label = QLabel(one_line if len(one_line) <= 78 else one_line[:77] + "…")
        label.setToolTip(text)
        row.addWidget(label, stretch=1)

        drop = QPushButton()
        drop.setObjectName("smallBtn")
        drop.setCursor(Qt.PointingHandCursor)
        drop.setToolTip("Remove this task")
        drop.setFixedWidth(28)
        icons.button_icon(drop, "x", 13, theme.TEXT)
        drop.clicked.connect(on_remove)
        row.addWidget(drop)


class InputPanel(BlueprintFrame):
    route_clicked = Signal(str)
    mic_toggle_clicked = Signal()
    attach_file_clicked = Signal()
    attach_folder_clicked = Signal()
    queue_changed = Signal(int)     # how many tasks are queued behind this one

    _MIN_H, _MAX_H = 46, 150

    def __init__(self, parent=None):
        super().__init__(parent, padding=(18, 15, 18, 16))

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(kicker("Your task"), stretch=1)
        self.state_chip = Chip()
        head.addWidget(self.state_chip)
        self.content.addLayout(head)
        self.content.addSpacing(6)

        self.text = QTextEdit()
        self.text.setObjectName("taskEdit")
        self.text.setFrameShape(QTextEdit.NoFrame)
        self.text.setPlaceholderText(
            "Describe what you want done — name any file or folder in plain "
            "words and Prism will go find it.")
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text.textChanged.connect(self._on_text_changed)
        # Grow with the task instead of reserving a fixed block: a one-line
        # task shouldn't leave a hole between it and the buttons.
        self.text.document().documentLayout().documentSizeChanged.connect(
            self._autosize)
        self.text.setFixedHeight(self._MIN_H)
        self.content.addWidget(self.text)
        self.content.addSpacing(10)

        # ── the queue ────────────────────────────────────────────────────────
        # Tasks the user lined up before starting. Prism plans and runs them in
        # order, so this list IS the running order — hence the numbers.
        self._queue: list[str] = []
        self.queue_box = QWidget()
        qv = QVBoxLayout(self.queue_box)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(5)
        self.queue_head = QLabel("")
        self.queue_head.setObjectName("meta")
        qv.addWidget(self.queue_head)
        self.queue_rows = QWidget()
        self._queue_layout = QVBoxLayout(self.queue_rows)
        self._queue_layout.setContentsMargins(0, 0, 0, 0)
        self._queue_layout.setSpacing(4)
        qv.addWidget(self.queue_rows)
        self.queue_box.setVisible(False)
        self.content.addWidget(self.queue_box)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.mic_btn = _action("Speak", "mic", "Dictate the task instead of typing")
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self.mic_toggle_clicked.emit)
        row.addWidget(self.mic_btn)

        file_btn = _action("Add file", "paperclip", "Attach a file")
        file_btn.clicked.connect(self.attach_file_clicked.emit)
        row.addWidget(file_btn)

        folder_btn = _action("Add folder", "folder", "Attach a whole folder")
        folder_btn.clicked.connect(self.attach_folder_clicked.emit)
        row.addWidget(folder_btn)

        self.add_task_btn = _action(
            "Add task", "plus",
            "Queue this one and type another — Prism runs them in order")
        self.add_task_btn.clicked.connect(self._queue_current)
        row.addWidget(self.add_task_btn)
        row.addStretch(1)

        self.route_btn = QPushButton(" Make a plan")
        self.route_btn.setObjectName("primaryBtn")
        self.route_btn.setCursor(Qt.PointingHandCursor)
        icons.button_icon(self.route_btn, "arrow-right", 16, theme.BG)
        self.route_btn.clicked.connect(
            lambda: self.route_clicked.emit(self.text.toPlainText()))
        row.addWidget(self.route_btn)
        self.content.addLayout(row)

        # Voice feedback ("heard: …") — hidden until there's something to say,
        # so the card keeps its shape in the common case.
        self.status = QLabel("")
        self.status.setObjectName("meta")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        self.status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.content.addWidget(self.status)

        self._blink = QTimer(self)
        self._blink.setInterval(600)
        self._blink.timeout.connect(self._pulse_mic)
        self._blink_on = False
        self._state = "empty"
        self.set_state("empty")

    # ── the task queue ────────────────────────────────────────────────────
    def _queue_current(self):
        """Move whatever is in the box onto the queue and clear it for the
        next one. Deliberately not allowed while a run is going: the queue is
        read once when the run starts, so appending mid-run would silently do
        nothing."""
        text = self.text.toPlainText().strip()
        if not text:
            self.append_status("Type the task first, then Add task.")
            return
        if self._state in ("routing", "running"):
            return
        self._queue.append(text)
        self.text.clear()
        self.append_status("")
        self._render_queue()
        self.set_state("empty")
        self.queue_changed.emit(len(self._queue))

    def _render_queue(self):
        while self._queue_layout.count():
            item = self._queue_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for i, task in enumerate(self._queue):
            self._queue_layout.addWidget(
                _QueuedTaskRow(i + 1, task,
                               lambda _=False, n=i: self._remove_task(n)))
        n = len(self._queue)
        self.queue_head.setText(
            "" if not n else
            f"{n} task{'s' if n != 1 else ''} queued — they run in this order, "
            "and the box below is the last one.")
        self.queue_box.setVisible(bool(n))

    def _remove_task(self, index: int):
        if 0 <= index < len(self._queue):
            self._queue.pop(index)
            self._render_queue()
            self.queue_changed.emit(len(self._queue))
            # Dropping the last queued task while the box is empty leaves
            # nothing to plan — put the chip back to match.
            if not self._queue and not self.text.toPlainText().strip():
                self.set_state("empty")
            elif self._state == "empty" and self._queue:
                self.set_state("ready")

    def tasks(self) -> list[str]:
        """Everything to run, in order: the queue, then whatever is still in
        the box. The box counts as the final task so the user never has to
        press Add task before Make a plan."""
        tail = self.text.toPlainText().strip()
        return self._queue + ([tail] if tail else [])

    def clear_queue(self):
        self._queue = []
        self._render_queue()
        self.queue_changed.emit(0)

    # ── state ─────────────────────────────────────────────────────────────
    def set_state(self, key: str):
        """Drive the chip. Also gates the CTA: there's nothing to plan until
        the box has words in it."""
        if key not in _STATES:
            return
        self._state = key
        label, icon_name, style = _STATES[key]
        self.state_chip.set(label, icon_name, style)
        # A queued task is enough to plan with even when the box is empty —
        # otherwise "Add task" would disable the very button it leads to.
        self.route_btn.setEnabled(
            key in ("ready", "planned", "done")
            or (key == "empty" and bool(self._queue)))
        self.add_task_btn.setEnabled(key not in ("routing", "running"))

    def _autosize(self):
        height = int(self.text.document().size().height()) + 4
        self.text.setFixedHeight(max(self._MIN_H, min(self._MAX_H, height)))

    def _on_text_changed(self):
        if self._state in ("empty", "ready"):
            self.set_state("ready" if self.text.toPlainText().strip() else "empty")

    def reset(self):
        """Empty the card for a fresh task. set_state comes last: clear()
        fires textChanged, and _on_text_changed ignores it while the state is
        still 'done'."""
        self.text.clear()
        self.append_status("")
        self.clear_queue()
        self.set_state("empty")

    def set_query_text(self, text: str):
        self.text.setPlainText(text)

    def append_status(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_recording(self, on: bool):
        self.mic_btn.setChecked(on)
        self.mic_btn.setText(" Stop" if on else " Speak")
        icons.button_icon(self.mic_btn, "stop" if on else "mic", 15,
                          theme.ACCENT_RAMP[700] if on else theme.TEXT)
        if on:
            self._blink.start()
        else:
            self._blink.stop()
            self._blink_on = False
            self.mic_btn.setStyleSheet("")

    def _pulse_mic(self):
        """Recording is the one state where nothing on screen would otherwise
        move — a slow tint pulse on the button is the whole cue."""
        self._blink_on = not self._blink_on
        self.mic_btn.setStyleSheet(
            "font-size: 13px; padding: 5px 11px;"
            + (f"background: {theme.ACCENT_RAMP[100]};"
               f"border-color: {theme.ACCENT};" if self._blink_on else ""))

    def set_busy(self, busy: bool):
        self.route_btn.setEnabled(not busy)
        self.route_btn.setText(" Planning…" if busy else " Make a plan")
        if busy:
            self.set_state("routing")
