"""Shown once the pipeline finishes: a description of what each stage
produced, with an "Open" button per stage so the user opens only the ones
they actually need instead of scrolling through everything."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QFrame, QApplication, QDialogButtonBox,
)


class StageResultDialog(QDialog):
    """One stage's full output, popped out into its own window."""

    def __init__(self, stage: str, agent: str, text: str, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{stage.upper()} · {agent}")
        self.resize(640, 480)
        root = QVBoxLayout(self)
        if url:
            link = QLabel(f'<a href="{url}">{url}</a>')
            link.setOpenExternalLinks(True)
            root.addWidget(link)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(text or "(no response text captured)")
        root.addWidget(body)
        row = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(body.toPlainText()))
        row.addWidget(copy_btn)
        row.addStretch(1)
        root.addLayout(row)


class _StageRow(QFrame):
    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("mentionRow")
        row = QHBoxLayout(self)
        ok = info.get("ok", True)
        pill = QLabel("done" if ok else "failed")
        pill.setObjectName("pillOk" if ok else "pillErr")
        pill.setAlignment(Qt.AlignCenter)
        pill.setFixedSize(58, 24)
        row.addWidget(pill)
        label = QLabel(f"<b>{info['stage'].upper()}</b> · {info['agent']}"
                       f"<br><span style='color:#9CA0AA'>{info.get('snippet', '')}</span>")
        label.setWordWrap(True)
        row.addWidget(label, stretch=1)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda: StageResultDialog(
            info["stage"], info["agent"], info.get("text", ""), info.get("url", ""),
            self.window()).exec())
        row.addWidget(open_btn)


class CompletionDialog(QDialog):
    def __init__(self, stage_infos: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pipeline finished")
        self.resize(560, 420)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "<b>✅ Prism finished this pipeline.</b><br>"
            "Here's what each stage produced — open only the ones you need:"))
        for info in stage_infos:
            root.addWidget(_StageRow(info))
        root.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addWidget(buttons)
