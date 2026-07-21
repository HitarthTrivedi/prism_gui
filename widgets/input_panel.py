"""Top panel: the query box + speak/attach/route controls."""
from __future__ import annotations
from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
)

from widgets.effects import apply_glow


def _fit(btn: QPushButton, pad: int = 34):
    """QSS horizontal padding isn't in sizeHint, so text clips at tight
    widths — set a text-derived minimum so labels always show in full."""
    btn.setMinimumWidth(QFontMetrics(btn.font()).horizontalAdvance(btn.text()) + pad)


class InputPanel(QWidget):
    route_clicked = Signal(str)
    mic_toggle_clicked = Signal()
    attach_file_clicked = Signal()
    attach_folder_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(8)
        root.addWidget(self._title("Your Task"))

        self.text = QTextEdit()
        self.text.setPlaceholderText(
            "Describe what you want done — mention any file or folder in "
            "plain words, Prism will find it. e.g. \"make a slide deck "
            "pitching the brochure in my Documents folder to investors\"")
        self.text.setFixedHeight(130)
        root.addWidget(self.text)

        # Attach/speak controls on their own row so they never compete with
        # the primary CTA for width when the central column is narrow
        # (docks on both sides can squeeze this down a lot).
        attach_row = QHBoxLayout()
        attach_row.setSpacing(8)
        self.mic_dot = QLabel("●")
        self.mic_dot.setObjectName("recDot")
        self.mic_dot.setVisible(False)
        attach_row.addWidget(self.mic_dot)
        self.mic_btn = QPushButton("🎤  Speak")
        self.mic_btn.setObjectName("compactBtn")
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self.mic_toggle_clicked.emit)
        _fit(self.mic_btn)
        attach_row.addWidget(self.mic_btn)

        attach_file_btn = QPushButton("📄  File")
        attach_file_btn.setObjectName("compactBtn")
        attach_file_btn.setToolTip("Attach a file")
        attach_file_btn.clicked.connect(self.attach_file_clicked.emit)
        _fit(attach_file_btn)
        attach_row.addWidget(attach_file_btn)

        attach_folder_btn = QPushButton("📁  Folder")
        attach_folder_btn.setObjectName("compactBtn")
        attach_folder_btn.setToolTip("Attach a folder")
        attach_folder_btn.clicked.connect(self.attach_folder_clicked.emit)
        _fit(attach_folder_btn)
        attach_row.addWidget(attach_folder_btn)
        attach_row.addStretch(1)
        root.addLayout(attach_row)

        cta_row = QHBoxLayout()
        cta_row.setSpacing(8)
        self.status = QLabel("")
        self.status.setObjectName("dim")
        cta_row.addWidget(self.status, stretch=1)
        self.route_btn = QPushButton("Route  →")
        self.route_btn.setObjectName("primaryBtn")
        self.route_btn.clicked.connect(lambda: self.route_clicked.emit(self.text.toPlainText()))
        _fit(self.route_btn, 44)
        apply_glow(self.route_btn)
        cta_row.addWidget(self.route_btn)
        root.addLayout(cta_row)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(600)
        self._blink_timer.timeout.connect(
            lambda: self.mic_dot.setVisible(not self.mic_dot.isVisible()))

    def _title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("panelTitle")
        return lbl

    def set_query_text(self, text: str):
        self.text.setPlainText(text)

    def append_status(self, text: str):
        self.status.setText(text)

    def set_recording(self, on: bool):
        self.mic_btn.setChecked(on)
        self.mic_btn.setText("⏹  Stop" if on else "🎤  Speak")
        if on:
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self.mic_dot.setVisible(False)

    def set_busy(self, busy: bool):
        self.route_btn.setEnabled(not busy)
        self.route_btn.setText("Routing…" if busy else "Route →")
