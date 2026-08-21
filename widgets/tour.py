"""The six-step tour: a dimmed overlay with a hole cut around one thing at a
time, and a card in the corner explaining it.

The design does this with a fixed backdrop and an outline on the highlighted
element. That translates directly: one translucent child widget laid over the
whole window, painting a dark wash everywhere except a rounded cut-out around
the target, plus the accent outline the design draws.

Why a cut-out rather than just outlining: an outline alone leaves the other
five things on screen at full strength competing for attention, which is the
opposite of what a tour is for. Dimming everything else is what makes the step
readable in one look.

The tour is opt-in from the rail and offered once on first run. It never blocks
— Skip is always visible, and Escape closes it.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

import i18n
import theme

# (attribute path on MainWindow, title, body). The attribute is resolved
# lazily so a step whose widget does not exist in this build — an add-on the
# rail hides, say — is skipped rather than crashing the tour.
STEPS = [
    ("sidebar.new_task_btn", "Start something new",
     "Every job begins here — describe it in plain words and Prism works out "
     "the rest."),
    ("sidebar", "Your everyday tools",
     "Email automation, BOQ and Email are ready-made for jobs you do all "
     "the time — no plan needed, just your files."),
    ("home_panel", "Describe or pick a quick-start",
     "Type your own task, or tap a quick-start chip to jump straight into an "
     "add-on."),
    ("home_panel", "Watch it work",
     "Once something's running, you'll see live progress here — which tool is "
     "on it, and what it's doing."),
    ("home_panel", "Jump back in anytime",
     "See what's waiting in each add-on, right from Home."),
    ("sidebar", "Everything else lives in Settings",
     "Your licence, agents and profile — one click away, always in the same "
     "place."),
]


class TourOverlay(QWidget):
    """Covers the window, dims it, and cuts a hole around the current step."""

    finished = Signal()

    def __init__(self, host, parent=None):
        super().__init__(parent or host)
        self._host = host
        self._step = 0
        self._target: QWidget | None = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.StrongFocus)

        self._card = QWidget(self)
        self._card.setObjectName("tourCard")
        self._card.setFixedWidth(300)
        self._card.setAttribute(Qt.WA_StyledBackground, True)
        self._card.setStyleSheet(
            "#tourCard { background: #ffffff; border-radius: 12px; }")
        col = QVBoxLayout(self._card)
        col.setContentsMargins(20, 18, 20, 18)
        col.setSpacing(0)

        self._kicker = QLabel()
        self._kicker.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 10.5px;"
            f" font-weight: 600; color: {theme.NEUTRAL[500]};")
        col.addWidget(self._kicker)
        col.addSpacing(8)
        self._title = QLabel()
        self._title.setObjectName("h6")
        self._title.setWordWrap(True)
        col.addWidget(self._title)
        col.addSpacing(6)
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            f"font-size: 12.5px; color: {theme.NEUTRAL[700]};")
        col.addWidget(self._body)
        col.addSpacing(14)

        dots = QHBoxLayout()
        dots.setSpacing(4)
        self._dots = []
        for _ in STEPS:
            dot = QLabel()
            dot.setFixedSize(16, 3)
            dots.addWidget(dot)
        self._dots = [dots.itemAt(i).widget() for i in range(dots.count())]
        dots.addStretch(1)
        col.addLayout(dots)
        col.addSpacing(14)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        skip = QPushButton(i18n.t("Skip"))
        skip.setFlat(True)
        skip.setCursor(Qt.PointingHandCursor)
        skip.setStyleSheet(
            f"border: none; background: transparent; font-size: 12px;"
            f" color: {theme.NEUTRAL[500]}; padding: 4px;")
        skip.clicked.connect(self.stop)
        actions.addWidget(skip)
        actions.addStretch(1)
        self._back = QPushButton(i18n.t("Back"))
        self._back.setObjectName("smallBtn")
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.clicked.connect(self.previous)
        actions.addWidget(self._back)
        self._next = QPushButton(i18n.t("Next"))
        self._next.setObjectName("primaryBtn")
        self._next.setCursor(Qt.PointingHandCursor)
        self._next.setStyleSheet("font-size: 12.5px; padding: 7px 14px;")
        self._next.clicked.connect(self.advance)
        actions.addWidget(self._next)
        col.addLayout(actions)

        host.installEventFilter(self)

    # ── control ───────────────────────────────────────────────────────────
    def start(self):
        self._step = 0
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._apply()

    def advance(self):
        if self._step + 1 >= len(STEPS):
            self.stop()
            return
        self._step += 1
        self._apply()

    def previous(self):
        if self._step > 0:
            self._step -= 1
            self._apply()

    def stop(self):
        self.hide()
        self.finished.emit()

    # ── layout ────────────────────────────────────────────────────────────
    def _resolve(self, path: str) -> QWidget | None:
        node = self._host
        for part in path.split("."):
            node = getattr(node, part, None)
            if node is None:
                return None
        return node if isinstance(node, QWidget) and node.isVisible() else None

    def _apply(self):
        path, title, body = STEPS[self._step]
        self._target = self._resolve(path)
        self._kicker.setText(i18n.t("STEP {n} OF {total}").format(
            n=self._step + 1, total=len(STEPS)))
        self._title.setText(i18n.t(title))
        self._body.setText(i18n.t(body))
        self._back.setVisible(self._step > 0)
        self._next.setText(i18n.t("Finish") if self._step + 1 >= len(STEPS)
                           else i18n.t("Next"))
        for i, dot in enumerate(self._dots):
            dot.setStyleSheet(
                f"background: {theme.ACCENT if i <= self._step else theme.NEUTRAL[200]};"
                " border-radius: 1px;")
        self._place_card()
        self.update()

    def _hole(self) -> QRect | None:
        if self._target is None:
            return None
        top_left = self._target.mapTo(self._host, QPoint(0, 0))
        return QRect(top_left, self._target.size()).adjusted(-6, -6, 6, 6)

    def _place_card(self):
        """Beside the highlight when there is room, else the opposite corner —
        the card must never sit on top of the thing it is describing."""
        self._card.adjustSize()
        size = self._card.sizeHint()
        margin = 26
        hole = self._hole()
        x = self.width() - size.width() - margin
        y = self.height() - size.height() - margin
        if hole is not None:
            if hole.right() < self.width() // 2:
                # Target on the left (the rail) — put the card to its right,
                # vertically near it rather than pinned to the bottom.
                x = min(hole.right() + 22,
                        self.width() - size.width() - margin)
                y = max(margin, min(hole.top(),
                                    self.height() - size.height() - margin))
            elif hole.bottom() + size.height() + margin < self.height():
                x = max(margin, min(hole.left(),
                                    self.width() - size.width() - margin))
                y = hole.bottom() + 16
        self._card.move(int(x), int(y))

    # ── paint ─────────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        wash = QPainterPath()
        wash.addRect(QRectF(self.rect()))
        hole = self._hole()
        if hole is not None:
            cut = QPainterPath()
            cut.addRoundedRect(QRectF(hole), 10, 10)
            wash = wash.subtracted(cut)
        painter.fillPath(wash, QColor(15, 20, 26, 130))
        if hole is not None:
            painter.setPen(QPen(theme.c(theme.ACCENT), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(hole), 10, 10)

    # ── events ────────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        if obj is self._host and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(self._host.rect())
            self._place_card()
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.stop()
        elif event.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self.advance()
        elif event.key() == Qt.Key_Left:
            self.previous()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Clicking the dimmed area steps forward; clicking the highlight does
        nothing, so a tour step cannot fire the button it is pointing at."""
        hole = self._hole()
        if hole is not None and hole.contains(event.pos()):
            return
        if not self._card.geometry().contains(event.pos()):
            self.advance()
