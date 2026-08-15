"""Live per-stage output, shown in the centre column while the run is on.

Same contract as before — one card per stage, Copy and Open-in-tool on each —
but laid out as the design's run timeline: a dot-and-line rail down the left,
so the stack of stages reads as a sequence with a position in it rather than as
a pile of identical panels.

Per-stage copy matters: if a later stage fails, the user can still take the last
good text and finish by hand."""
from __future__ import annotations
import os
from html import escape as _escape
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRectF, QTimer, QUrl, Signal,
)
from PySide6.QtGui import QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QApplication, QGraphicsOpacityEffect, QSizePolicy,
)

import i18n
import paths
import theme
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import Card, Pill, heading
from widgets.markdown import render_markdown


class TimelineDot(QWidget):
    """The circle and the line beneath it, down the left of a run.

    This is what turns a stack of stage cards into a *sequence*. The old
    layout gave every stage an identical frame, so "which one is Prism on"
    could only be read by finding the one chip that said working — on a
    four-stage run that is a search, not a glance. Here the filled dots are
    behind you, the pulsing one is now, and the hollow ones are still to come.
    """

    SIZE = 30

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._state = "queued"
        self._last = False
        self.setFixedWidth(self.SIZE)
        self.setMinimumHeight(self.SIZE)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.MinimumExpanding)

    def set_state(self, state: str, last: bool = False):
        self._state, self._last = state, last
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        done = self._state == "done"
        running = self._state == "running"
        failed = self._state == "failed"

        if failed:
            fill, ink = theme.ERR_BG, theme.ERR
        elif done:
            fill, ink = theme.ACCENT, "#ffffff"
        elif running:
            fill, ink = theme.ACCENT_RAMP[100], theme.ACCENT_RAMP[700]
        else:
            fill, ink = theme.NEUTRAL[100], theme.NEUTRAL[400]

        # The running dot is ramp-100 on a ramp-adjacent canvas, which is very
        # nearly the same value — the design gets away with it because the dot
        # is also pulsing. Static, it needs a ring, or the one stage you most
        # want to find is the one that disappears.
        if running:
            painter.setPen(QPen(theme.c(theme.ACCENT, 0.45), 1.5))
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c(fill))
        inset = 0.75 if running else 0
        painter.drawEllipse(QRectF(inset, inset, self.SIZE - inset * 2,
                                   self.SIZE - inset * 2))
        glyph = icons.pixmap(
            "check" if done else ("alert" if failed else self._icon_name),
            15, ink)
        painter.drawPixmap(int((self.SIZE - 15) / 2),
                           int((self.SIZE - 15) / 2), glyph)

        # The connector only reaches the next dot, so the last stage does not
        # trail a line into empty space.
        if not self._last and self.height() > self.SIZE:
            painter.setBrush(theme.c(theme.ACCENT if done else theme.NEUTRAL[200]))
            painter.drawRect(QRectF((self.SIZE - 2) / 2, self.SIZE, 2,
                                    self.height() - self.SIZE))


class StageCard(QWidget):
    def __init__(self, stage: str, agent: str, parent=None):
        super().__init__(parent)
        self.stage = stage
        self._url = ""
        self._raw = ""   # raw text kept for copy, even when the body is rich

        icon_name, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))

        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(14)
        # No alignment: the dot column must fill this row's full height so its
        # connector reaches the next stage. Top-aligning it collapsed the
        # widget to its own sizeHint — which for a bare QWidget is zero — and
        # nothing painted at all.
        self.dot = TimelineDot(icon_name)
        shell.addWidget(self.dot)

        card = Card()
        self.panel = card
        # The gap between stages lives inside this row rather than between
        # rows, so the dot column spans it and the connector stays unbroken.
        # With the spacing in the parent layout the line came out dashed.
        gapped = QVBoxLayout()
        gapped.setContentsMargins(0, 0, 0, 14)
        gapped.addWidget(card)
        shell.addLayout(gapped, stretch=1)
        self.content = card.body((16, 14, 16, 14), spacing=0)

        head = QHBoxLayout()
        head.setSpacing(9)
        name = QLabel(title)
        name.setObjectName("h6")
        head.addWidget(name, stretch=1)
        self.tool = Pill(agent, "neutral")
        head.addWidget(self.tool)
        self.status = Pill(i18n.t("Queued"), "quiet")
        head.addWidget(self.status)
        self.content.addLayout(head)
        self.content.addSpacing(6)

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
        # Only ever shown for a file result: it lands in ~/.prism/runs, which
        # Finder hides, so "here is the path" is not an answer on its own.
        self.reveal_btn = QPushButton(" Show in folder")
        self.reveal_btn.setObjectName("smallBtn")
        self.reveal_btn.setCursor(Qt.PointingHandCursor)
        icons.button_icon(self.reveal_btn, "folder", 14, theme.TEXT)
        self.reveal_btn.clicked.connect(lambda: paths.reveal_result(self._url))
        self.reveal_btn.setVisible(False)
        row.addWidget(self.reveal_btn)
        row.addStretch(1)
        self.content.addWidget(self.actions)

        # The card owns its one QGraphicsEffect slot for the drop shadow, so
        # the entrance fade goes on this outer widget instead. Same effect on
        # screen — the whole row fades in together, dot and all, which is
        # actually truer to a stage arriving than fading the card alone was.
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade_anim = QPropertyAnimation(effect, b"opacity", self)
        self._fade_anim.setDuration(220)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._fade_anim.start()

    def _set_status(self, text: str, tone: str, dot: str):
        """One call for the pill and the timeline dot, so the two can never
        disagree about what this stage is doing."""
        self.status.setText(text)
        self.status.set_tone(tone)
        self.dot.set_state(dot, self._last)

    _last = False

    def set_last(self, last: bool):
        self._last = last
        self.dot.set_state(self.dot._state, last)

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
        # A local agent's result is a file, not a tab. Say so on the button —
        # "Open in tool" over a rendered MP4 reads as a link to somewhere else,
        # and the user never learns the video is already on their machine.
        local = paths.is_local_result(self._url)
        self.reveal_btn.setVisible(local)
        if local:
            video = self._url.lower().endswith((".mp4", ".mov", ".m4v", ".webm"))
            self.open_btn.setText(" Play video" if video else " Open file")
            icons.button_icon(self.open_btn, "play" if video else "folder", 14,
                              theme.ACCENT_RAMP[700])
        elif url:
            self.open_btn.setText(" Open in tool")
            icons.button_icon(self.open_btn, "external", 14, theme.ACCENT_RAMP[700])

    def set_waiting(self, seconds: int):
        self._set_status(i18n.t("Waiting up to {n}s").format(n=seconds), "warn",
                         "running")

    def set_done(self, texts: list[str], url: str, timed_out: bool = False):
        self._set_url(url)
        note = ""
        if timed_out:
            # Our clock ran out, not the tool's: it is still generating in that
            # tab and will land the finished deck/doc/app there. Saying "done"
            # here would send the user away from the only place the real
            # result appears, so the link is the headline.
            note = (f"<p style='color:{theme.NEUTRAL[600]};line-height:150%'>"
                    "Prism stopped waiting, but the tool is still working — "
                    "open it to pick up the finished result.</p>")
        elif paths.is_local_result(url):
            # The whole result IS the file. Without this the card printed the
            # engine's one-line note and nothing else, so a finished render
            # looked like a step that had produced nothing. Copy gives the
            # path, since that is the only thing worth pasting anywhere.
            size = ""
            try:
                size = f" · {os.path.getsize(url) / 1e6:.1f} MB"
            except OSError:
                pass
            self._raw = url
            self.body.setHtml(
                f"<p style='line-height:150%'>Made on this machine — "
                f"<b>{_escape(os.path.basename(url))}</b>{size}<br>"
                f"<span style='color:{theme.NEUTRAL[600]}'>"
                f"{_escape(os.path.dirname(url))}</span></p>")
            self._set_status(i18n.t("Done"), "accent", "done")
            self.copy_btn.setEnabled(True)
            return
        if texts:
            self._raw = "\n\n———\n\n".join(texts)
            # render the AI's response as formatted markdown (it's a document),
            # but keep the raw text for copy so paste-elsewhere is verbatim
            self.body.setHtml(note + render_markdown(self._raw))
            if timed_out:
                self._set_status(i18n.t("Still generating"), "warn", "running")
            else:
                self._set_status(i18n.t("Done"), "accent", "done")
            self.copy_btn.setEnabled(True)
        else:
            # scrape missed the response — point the user at the live tab
            self._raw = ""
            self.body.setHtml(
                note if note else
                f"<p style='color:{theme.NEUTRAL[600]};line-height:150%'>Prism "
                "couldn't read the response off the page.<br>Open the tool to "
                "grab the result manually — the run finished, only the scrape "
                "missed it.</p>"
                if url else
                f"<p style='color:{theme.NEUTRAL[600]}'>No response was "
                "captured for this step.</p>")
            self._set_status(
                i18n.t("Still generating") if timed_out else i18n.t("No response"),
                "warn", "running" if timed_out else "failed")
            self.copy_btn.setEnabled(False)

    def set_error(self, error: str, url: str = ""):
        self._set_status(i18n.t("Failed"), "err", "failed")
        self._raw = error
        # A failed step can still leave a live tab behind — the tool often
        # finishes on its own after Prism loses the thread. Offer it.
        self._set_url(url)
        tail = (f"<p style='color:{theme.NEUTRAL[600]};line-height:150%'>The "
                "tool's tab is still on the job — open it to see whether it "
                "finished without Prism.</p>") if url else ""
        self.body.setHtml(
            f"<p style='color:#8a2f2f;line-height:150%'>{_escape(error)}</p>{tail}")
        self.copy_btn.setEnabled(True)

    def _copy(self):
        QApplication.clipboard().setText(self._raw or self.body.toPlainText())
        self.copy_btn.setText(" Copied")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText(" Copy output"))

    def _open(self):
        if self._url:
            paths.open_result(self._url)


class OutputPanel(QWidget):
    back_requested = Signal()
    stop_requested = Signal()

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
        head.addStretch(1)

        # A run is tens of minutes of browser automation. Without this the
        # only way out is force-quitting the app, which loses every step that
        # had already finished — the engine has supported stopping cleanly all
        # along, and nothing here was calling it.
        self.stop_btn = QPushButton(" Stop the run")
        self.stop_btn.setObjectName("smallBtn")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setToolTip(
            "Finishes the step that's running, keeps everything already done, "
            "and stops there.")
        icons.button_icon(self.stop_btn, "stop", 14, "#8a2f2f")
        self.stop_btn.clicked.connect(self._on_stop)
        head.addWidget(self.stop_btn)

        self.set_finished(False)
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
        # Zero: each StageCard carries its own bottom gap so the timeline
        # connector runs unbroken between one dot and the next.
        self.cards_box.setSpacing(0)
        self.cards_box.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _on_stop(self):
        # Latch immediately so a second click can't queue a second stop, and
        # so the label stops claiming an action that is already under way. The
        # engine finishes the current step before it winds up, which can take
        # a moment, and silence there reads as the button not having worked.
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText(" Stopping…")
        self.stop_requested.emit()

    def set_running(self, running: bool):
        """Show Stop only while there is something to stop."""
        self.stop_btn.setVisible(running)
        if running:
            self.stop_btn.setEnabled(True)
            self.stop_btn.setText(" Stop the run")
            icons.button_icon(self.stop_btn, "stop", 14, "#8a2f2f")

    def set_finished(self, finished: bool):
        """Once the run is done the plan behind this page is spent, and going
        back clears it — so the button has to say so. Mid-run (or after a
        failure, where the plan is still worth retrying) it stays a plain
        back link."""
        if finished:
            self.set_running(False)
            self.back_btn.setText(" Start something new")
            icons.button_icon(self.back_btn, "plus", 15, theme.ACCENT_RAMP[700])
            self.back_btn.setToolTip("Clears these steps and the task, ready for the next one")
        else:
            self.back_btn.setText(" Back to the steps")
            icons.button_icon(self.back_btn, "chevron-left", 15, theme.ACCENT_RAMP[700])
            self.back_btn.setToolTip("Your steps are still there — nothing is lost")

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
        # Cards arrive one per stage as the run reaches them, so the newest is
        # always the tail of the timeline. Un-tail the one before it, or the
        # connector stops at the second-to-last dot and the chain looks broken.
        for existing in self._cards.values():
            existing.set_last(False)
        card = StageCard(stage, agent)
        card.set_last(True)
        card._set_status(i18n.t("Working…"), "warn", "running")
        self._cards[stage] = card
        self.cards_box.insertWidget(self.cards_box.count() - 1, card)

    def stage_waiting(self, stage: str, seconds: int):
        card = self._cards.get(stage)
        if card:
            card.set_waiting(seconds)

    def stage_done(self, stage: str, texts: list[str], url: str,
                   timed_out: bool = False):
        card = self._cards.get(stage)
        if card:
            card.set_done(texts, url, timed_out)

    def stage_error(self, stage: str, error: str, url: str = ""):
        card = self._cards.get(stage)
        if card:
            card.set_error(error, url)
