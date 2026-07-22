"""Live per-stage output, shown in the centre column while the run is on.

Same contract as before — one card per stage, Copy and Open-in-tool on each —
restyled onto the blueprint frame so a running step reads as the same kind of
object as the plan step it came from. Per-stage copy matters: if a later stage
fails, the user can still take the last good text and finish by hand."""
from __future__ import annotations
from html import escape as _escape
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QApplication, QGraphicsOpacityEffect,
)

import theme
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.blueprint import BlueprintFrame
from widgets.controls import Chip, heading
from widgets.markdown import render_markdown


class StageCard(BlueprintFrame):
    def __init__(self, stage: str, agent: str, parent=None):
        super().__init__(parent, padding=(16, 13, 16, 13), surface=True)
        self.stage = stage
        self._url = ""
        self._raw = ""   # raw text kept for copy, even when the body is rich

        icon_name, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))

        head = QHBoxLayout()
        head.setSpacing(9)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 18, theme.ACCENT))
        head.addWidget(glyph)
        name = QLabel(title)
        name.setObjectName("h5")
        head.addWidget(name)
        tool = QLabel(agent)
        tool.setObjectName("tagNeutral")
        head.addWidget(tool)
        head.addStretch(1)
        self.status = Chip("queued…", "clock", "tagWarn")
        head.addWidget(self.status)
        self.content.addLayout(head)

        self.body = QTextEdit()
        self.body.setObjectName("stageBody")
        self.body.setReadOnly(True)
        # Sized to its content, capped — a queued or waiting stage has nothing
        # to show, and a fixed box would park an empty rectangle on screen for
        # however long the tool takes to answer.
        self.body.document().documentLayout().documentSizeChanged.connect(
            self._autosize)
        self.body.setVisible(False)
        self.content.addWidget(self.body)

        # Actions hide with the body: while a stage is queued or waiting there
        # is nothing to copy and no tab to open, and a row of dead buttons
        # under an empty box reads as broken rather than pending.
        self.actions = QWidget()
        self.actions.setVisible(False)
        row = QHBoxLayout(self.actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.copy_btn = QPushButton(" Copy output")
        self.copy_btn.setObjectName("smallBtn")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        icons.button_icon(self.copy_btn, "copy", 14, theme.TEXT)
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)
        self.open_btn = QPushButton(" Open in tool")
        self.open_btn.setObjectName("linkBtn")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        icons.button_icon(self.open_btn, "external", 14, theme.ACCENT_RAMP[700])
        self.open_btn.clicked.connect(self._open)
        self.open_btn.setVisible(False)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        self.content.addWidget(self.actions)

        # The fade goes on the frame's inner panel — a widget holds only one
        # QGraphicsEffect, and the frame itself must stay free to paint its
        # registration marks.
        effect = QGraphicsOpacityEffect(self.panel)
        self.panel.setGraphicsEffect(effect)
        self._fade_anim = QPropertyAnimation(effect, b"opacity", self)
        self._fade_anim.setDuration(220)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._fade_anim.start()

    def _autosize(self):
        has_content = bool(self.body.toPlainText().strip())
        self.body.setVisible(has_content)
        self.actions.setVisible(has_content)
        if has_content:
            height = int(self.body.document().size().height()) + 22
            self.body.setFixedHeight(max(56, min(230, height)))

    def _set_url(self, url: str):
        self._url = url or ""
        self.open_btn.setVisible(bool(url))

    def set_waiting(self, seconds: int):
        self.status.set(f"waiting up to {seconds}s", "clock", "tagWarn")

    def set_done(self, texts: list[str], url: str):
        self._set_url(url)
        if texts:
            self._raw = "\n\n———\n\n".join(texts)
            # render the AI's response as formatted markdown (it's a document),
            # but keep the raw text for copy so paste-elsewhere is verbatim
            self.body.setHtml(render_markdown(self._raw))
            self.status.set("done", "check", "tagOk")
            self.copy_btn.setEnabled(True)
        else:
            # scrape missed the response — point the user at the live tab
            self._raw = ""
            self.body.setHtml(
                f"<p style='color:{theme.NEUTRAL[600]};line-height:150%'>Prism "
                "couldn't read the response off the page.<br>Open the tool to "
                "grab the result manually — the run finished, only the scrape "
                "missed it.</p>"
                if url else
                f"<p style='color:{theme.NEUTRAL[600]}'>No response was "
                "captured for this step.</p>")
            self.status.set("no response", "alert", "tagWarn")
            self.copy_btn.setEnabled(False)

    def set_error(self, error: str):
        self.status.set("failed", "alert", "tagErr")
        self._raw = error
        self.body.setHtml(
            f"<p style='color:#8a2f2f;line-height:150%'>{_escape(error)}</p>")
        self.copy_btn.setEnabled(True)

    def _copy(self):
        QApplication.clipboard().setText(self._raw or self.body.toPlainText())
        self.copy_btn.setText(" Copied")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText(" Copy output"))

    def _open(self):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))


class OutputPanel(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, StageCard] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(11)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("ghostBtn")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_requested.emit)
        head.addWidget(self.back_btn)
        self.set_finished(False)
        head.addStretch(1)
        root.addLayout(head)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(heading("The work"), stretch=1)
        root.addLayout(title_row)
        sub = QLabel("Live results, step by step. Copy any of them, or open "
                     "the tool that produced it.")
        sub.setObjectName("meta")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.empty = QLabel("Nothing has run yet.")
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self.cards_box = QVBoxLayout(inner)
        self.cards_box.setContentsMargins(0, 2, 0, 2)
        self.cards_box.setSpacing(6)
        self.cards_box.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def set_finished(self, finished: bool):
        """Once the run is done the plan behind this page is spent, and going
        back clears it — so the button has to say so. Mid-run (or after a
        failure, where the plan is still worth retrying) it stays a plain
        back link."""
        if finished:
            self.back_btn.setText(" Start something new")
            icons.button_icon(self.back_btn, "plus", 15, theme.ACCENT_RAMP[700])
            self.back_btn.setToolTip("Clears this plan and the task, ready for the next one")
        else:
            self.back_btn.setText(" Back to the plan")
            icons.button_icon(self.back_btn, "chevron-left", 15, theme.ACCENT_RAMP[700])
            self.back_btn.setToolTip("Your plan is still there — nothing is lost")

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
