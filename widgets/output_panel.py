"""Panel: live per-stage output as the pipeline runs. Each stage gets its own
card with a Copy button and an Open link — if a later stage fails or an agent
isn't cooperating, the user can grab the last good stage's text (or open the
tool tab) and continue by hand instead of losing the whole run."""
from __future__ import annotations
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QFrame, QScrollArea, QApplication, QGraphicsOpacityEffect,
)


class StageCard(QFrame):
    def __init__(self, stage: str, agent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stageCard")
        self.stage = stage
        self._url = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(stage.upper())
        self.title.setObjectName("panelTitle")
        head.addWidget(self.title)
        self.agent_pill = QLabel(agent)
        self.agent_pill.setObjectName("pillInfo")
        head.addWidget(self.agent_pill)
        head.addStretch(1)
        self.status = QLabel("queued…")
        self.status.setObjectName("pillWarn")
        head.addWidget(self.status)
        root.addLayout(head)

        self.body = QTextEdit()
        self.body.setObjectName("stageBody")
        self.body.setReadOnly(True)
        self.body.setMaximumHeight(150)
        root.addWidget(self.body)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.copy_btn = QPushButton("⧉  Copy output")
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)
        self.open_btn = QPushButton("Open in tool  ↗")
        self.open_btn.setObjectName("linkBtn")
        self.open_btn.setCursor(self.copy_btn.cursor())
        self.open_btn.clicked.connect(self._open)
        self.open_btn.setVisible(False)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        root.addLayout(row)

        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade_anim = QPropertyAnimation(effect, b"opacity", self)
        self._fade_anim.setDuration(220)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._fade_anim.start()

    def _set_status(self, text: str, pill: str):
        self.status.setText(text)
        self.status.setObjectName(pill)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _set_url(self, url: str):
        self._url = url or ""
        self.open_btn.setVisible(bool(url))

    def set_waiting(self, seconds: int):
        self._set_status(f"⏳ waiting up to {seconds}s…", "pillWarn")

    def set_done(self, texts: list[str], url: str):
        self._set_url(url)
        text = "\n\n———\n\n".join(texts) if texts else ""
        if texts:
            self.body.setPlainText(text)
            self._set_status("✅ done", "pillOk")
            self.copy_btn.setEnabled(True)
        else:
            # scrape missed the response — point the user at the live tab
            self.body.setPlainText(
                "Prism couldn't read the response off the page.\n"
                "Open the tool to grab the result manually — the run "
                "finished, only the scrape missed it." if url else
                "No response was captured for this stage.")
            self._set_status("⚠️ no response scraped", "pillWarn")
            self.copy_btn.setEnabled(False)

    def set_error(self, error: str):
        self._set_status("❌ failed", "pillErr")
        self.body.setPlainText(error)
        self.copy_btn.setEnabled(True)

    def _copy(self):
        QApplication.clipboard().setText(self.body.toPlainText())
        self.copy_btn.setText("✓  Copied")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("⧉  Copy output"))

    def _open(self):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))


class OutputPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._cards: dict[str, StageCard] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(6)
        title = QLabel("Pipeline Output")
        title.setObjectName("panelTitle")
        root.addWidget(title)
        sub = QLabel("Live per-stage results — copy any stage, or open its tool tab.")
        sub.setObjectName("panelSubtitle")
        root.addWidget(sub)

        self.empty = QLabel("Run the pipeline to see live output here.")
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self.cards_box = QVBoxLayout(inner)
        self.cards_box.setContentsMargins(0, 2, 0, 2)
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
        self.empty.setVisible(True)

    def stage_started(self, stage: str, agent: str):
        self.empty.setVisible(False)
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
