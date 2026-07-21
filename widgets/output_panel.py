"""Panel: live per-stage output as the pipeline runs. Each stage gets its own
card with a Copy button — if a later stage fails or an agent isn't
cooperating, the user can grab the last good stage's text and paste it into
the next tool by hand instead of losing the whole run."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QFrame, QScrollArea, QApplication,
)


class StageCard(QFrame):
    def __init__(self, stage: str, agent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stageCard")
        self.stage = stage
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self.title = QLabel(f"{stage.upper()} · {agent}")
        self.title.setObjectName("panelTitle")
        head.addWidget(self.title, stretch=1)
        self.status = QLabel("queued…")
        self.status.setObjectName("dim")
        head.addWidget(self.status)
        root.addLayout(head)

        self.body = QTextEdit()
        self.body.setReadOnly(True)
        self.body.setMaximumHeight(140)
        root.addWidget(self.body)

        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy output")
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)
        self.link_lbl = QLabel("")
        self.link_lbl.setObjectName("dim")
        self.link_lbl.setTextInteractionFlags(self.link_lbl.textInteractionFlags())
        row.addWidget(self.link_lbl, stretch=1)
        root.addLayout(row)

    def set_waiting(self, seconds: int):
        self.status.setText(f"⏳ waiting up to {seconds}s…")

    def set_done(self, texts: list[str], url: str):
        text = "\n\n---\n\n".join(texts) if texts else ""
        self.body.setPlainText(text or "(no response text captured)")
        self.status.setText("✅ done" if texts else "⚠️ no response scraped")
        self.link_lbl.setText(url)
        self.copy_btn.setEnabled(bool(text))

    def set_error(self, error: str):
        self.status.setText("❌ failed")
        self.body.setPlainText(error)
        self.copy_btn.setEnabled(True)

    def _copy(self):
        QApplication.clipboard().setText(self.body.toPlainText())


class OutputPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._cards: dict[str, StageCard] = {}
        root = QVBoxLayout(self)
        title = QLabel("Pipeline Output (copy-and-paste fallback)")
        title.setObjectName("panelTitle")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.cards_box = QVBoxLayout(inner)
        self.cards_box.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll)

    def clear(self):
        self._cards = {}
        while self.cards_box.count():
            item = self.cards_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards_box.addStretch(1)

    def stage_started(self, stage: str, agent: str):
        card = StageCard(stage, agent)
        self._cards[stage] = card
        self.cards_box.insertWidget(self.cards_box.count() - 1, card)

    def stage_waiting(self, stage: str, seconds: int):
        card = self._cards.get(stage)
        if card:
            card.set_waiting(seconds)

    def stage_done(self, stage: str, texts: list[str], url: str):
        card = self._cards.get(stage)
        if card:
            card.set_done(texts, url)

    def stage_error(self, stage: str, error: str):
        card = self._cards.get(stage)
        if card:
            card.set_error(error)
