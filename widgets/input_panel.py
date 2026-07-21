"""Top panel: the query box + speak/attach/route controls."""
from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
)


class InputPanel(QWidget):
    route_clicked = Signal(str)
    mic_toggle_clicked = Signal()
    attach_file_clicked = Signal()
    attach_folder_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        root.addWidget(self._title("Your Task"))

        self.text = QTextEdit()
        self.text.setPlaceholderText(
            "Describe what you want done — mention any file or folder in "
            "plain words, Prism will find it. e.g. \"make a slide deck "
            "pitching the brochure in my Documents folder to investors\"")
        self.text.setFixedHeight(110)
        root.addWidget(self.text)

        row = QHBoxLayout()
        self.mic_btn = QPushButton("🎤  Speak")
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self.mic_toggle_clicked.emit)
        row.addWidget(self.mic_btn)

        attach_file_btn = QPushButton("📄  Attach file")
        attach_file_btn.clicked.connect(self.attach_file_clicked.emit)
        row.addWidget(attach_file_btn)

        attach_folder_btn = QPushButton("📁  Attach folder")
        attach_folder_btn.clicked.connect(self.attach_folder_clicked.emit)
        row.addWidget(attach_folder_btn)

        row.addStretch(1)

        self.route_btn = QPushButton("Route →")
        self.route_btn.setObjectName("primaryBtn")
        self.route_btn.clicked.connect(lambda: self.route_clicked.emit(self.text.toPlainText()))
        row.addWidget(self.route_btn)

        root.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("dim")
        root.addWidget(self.status)

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

    def set_busy(self, busy: bool):
        self.route_btn.setEnabled(not busy)
        self.route_btn.setText("Routing…" if busy else "Route →")
