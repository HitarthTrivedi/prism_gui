"""The conversation itself: message bubbles, day separators, delivery ticks,
and the composer.

Two decisions worth knowing:

  · A bubble's WIDTH is computed from its text, not left to the layout. A
    word-wrapped QLabel inside a stretching layout takes the full column and
    leaves every short message ("Ok, thanks") as a wide pale bar. Measuring the
    wrapped text and fixing the label to that width gives bubbles that hug what
    was said — and fixing the width is also what makes the label's height
    follow it, so nothing clips.
  · A send is OPTIMISTIC. The bubble appears the instant Enter is pressed,
    marked "sending", and settles to sent or to a red "Failed · Retry" — the
    person never sits watching a button while a request travels to a server
    and on to n8n and Meta.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp.chat import clock, day_label, parse_ts
from widgets import controls as C
from widgets import icons

_MAX_TEXT = 4096                      # the licence server's bound on a reply
_GROUP_GAP = timedelta(minutes=3)


def _font(px: int, weight: int = 400) -> QFont:
    f = QFont(theme.FONT_BODY)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    return f


# Delivery state -> (icon, how many, colour, tooltip). Drawn as icons, not the
# ✓ characters: Barlow has no such glyph, and the fallback font's version came
# out as a broken box on the machine this was checked on. Anything the server
# has not said about is treated as plain "sent" — n8n logging the message means
# it was accepted, which is all one tick claims.
def _tick(status: str) -> tuple:
    """(icon, how many, colour, tooltip) for a delivery state. Literal i18n.t
    calls, for the string extractor."""
    return {
        "sending":   ("clock", 1, theme.NEUTRAL[500], i18n.t("Sending…")),
        "sent":      ("check", 1, theme.NEUTRAL[500], i18n.t("Sent")),
        "delivered": ("check", 2, theme.NEUTRAL[500], i18n.t("Delivered")),
        "read":      ("check", 2, theme.INFO_INK,     i18n.t("Read")),
    }.get(status or "sent") or ("check", 1, theme.NEUTRAL[500], i18n.t("Sent"))


class _Meta(QFrame):
    """The time + tick line under a bubble's text. Clickable only when the
    send failed — that click is the retry."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.time = QLabel()
        self.time.setFont(_font(11, 500))
        row.addWidget(self.time)
        self._tick_box = QWidget()
        self._ticks = QHBoxLayout(self._tick_box)
        self._ticks.setContentsMargins(0, 0, 0, 0)
        self._ticks.setSpacing(-7)              # overlap: two ticks read as one mark
        row.addWidget(self._tick_box)
        self._retry = False

    def _set_ticks(self, name: str, count: int, colour: str):
        while self._ticks.count():
            w = self._ticks.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for _ in range(count):
            lab = QLabel()
            lab.setPixmap(icons.pixmap(name, 14, colour))
            lab.setFixedSize(14, 14)
            self._ticks.addWidget(lab)
        self._tick_box.setVisible(count > 0)

    def show_state(self, stamp: str, outbound: bool, status: str):
        self._retry = False
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("")
        if status == "failed":
            self._retry = True
            self.setCursor(Qt.PointingHandCursor)
            self._set_ticks("check", 0, "")
            self.time.setText(i18n.t("Failed · Retry"))
            self.time.setStyleSheet(f"color: {theme.ERR_INK}; font-weight: 700;")
            self.setToolTip(i18n.t("It didn't send. Click to try again."))
            return
        self.time.setText(clock(stamp))
        if not outbound:
            self.time.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
            self._set_ticks("check", 0, "")
            return
        icon, count, colour, tip = _tick(status)
        self.time.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        self._set_ticks(icon, count, colour)
        self.setToolTip(tip)

    def mousePressEvent(self, event):
        if self._retry and event.button() == Qt.LeftButton:
            self.clicked.emit()
        else:
            super().mousePressEvent(event)


class Bubble(QFrame):
    retry = Signal(object)                  # this bubble

    def __init__(self, msg: dict, tail: bool, caption: str = "", parent=None):
        super().__init__(parent)
        self.msg = msg
        self.outbound = msg.get("direction") == "out"
        self.setObjectName("waBubble")
        self.setAttribute(Qt.WA_StyledBackground, True)
        radius, small = 16, 4
        corners = {"tl": radius, "tr": radius, "bl": radius, "br": radius}
        if tail:
            corners["br" if self.outbound else "bl"] = small
        bg = "rgba(22, 163, 74, 0.17)" if self.outbound else "rgba(255, 255, 255, 0.94)"
        border = "transparent" if self.outbound else theme.HAIRLINE
        self.setStyleSheet(
            f"#waBubble {{ background: {bg}; border: 1px solid {border};"
            f" border-top-left-radius: {corners['tl']}px;"
            f" border-top-right-radius: {corners['tr']}px;"
            f" border-bottom-left-radius: {corners['bl']}px;"
            f" border-bottom-right-radius: {corners['br']}px; }}")

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 8, 12, 6)
        col.setSpacing(2)
        if caption:
            cap = QLabel(caption)
            cap.setFont(_font(11, 700))
            cap.setStyleSheet(f"color: {theme.OK_INK}; background: transparent;")
            col.addWidget(cap)
        self.body = QLabel(msg.get("text") or "")
        self.body.setFont(_font(14))
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        col.addWidget(self.body)
        self.meta = _Meta()
        self.meta.clicked.connect(lambda: self.retry.emit(self))
        col.addWidget(self.meta, alignment=Qt.AlignRight)
        self.set_status(msg.get("status") or "")

    def set_status(self, status: str):
        self.msg["status"] = status
        self.meta.show_state(self.msg.get("created_at", ""), self.outbound, status)

    def fit(self, max_bubble: int):
        """Shrink-wrap the text: the widest line that fits, capped."""
        max_text = max(120, max_bubble - 26)
        text = self.body.text()
        fm = QFontMetrics(self.body.font())
        rect = fm.boundingRect(QRect(0, 0, max_text, 100000),
                               Qt.TextWordWrap | Qt.AlignLeft, text)
        meta_w = self.meta.sizeHint().width() + 4
        self.body.setFixedWidth(max(min(max_text, rect.width() + 4), meta_w))


class _DayChip(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(_font(11, 700))
        self.setStyleSheet(
            f"color: {theme.NEUTRAL[700]}; background: rgba(0, 0, 0, 0.06);"
            f" border-radius: 10px; padding: 3px 12px;")
        self.setAlignment(Qt.AlignCenter)


class MessageThread(QScrollArea):
    """A scrolling column of bubbles, pinned to the newest message."""

    retryRequested = Signal(str, object)    # text, the failed bubble

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(18, 14, 18, 14)
        self._col.setSpacing(0)
        self._bubbles: list[Bubble] = []
        self._signature = None
        # Messages typed here that the server has not confirmed. A FAILED one
        # must outlive a redraw: it is not in the server's thread, the composer
        # was already cleared, and dropping it would lose the person's words.
        self._pending_msgs: list[dict] = []

    # -- content ----------------------------------------------------------------
    def _clear(self):
        while self._col.count():
            item = self._col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._bubbles = []

    def show_note(self, text: str, tone: str = "muted"):
        self._clear()
        self._signature = None
        colour = theme.ERR_INK if tone == "error" else theme.NEUTRAL[600]
        self._col.addStretch(1)
        lab = C.label(text, level="SUPPORT", colour=colour, wrap=True)
        lab.setAlignment(Qt.AlignCenter)
        self._col.addWidget(lab)
        self._col.addStretch(1)

    def set_messages(self, messages: list) -> bool:
        """Rebuild the thread. Returns False when nothing changed (so a poll
        that finds the same messages does not flicker or lose the scroll)."""
        sig = tuple((m.get("created_at"), m.get("text"), m.get("status"))
                    for m in messages)
        if sig == self._signature:
            return False
        stick = self._at_bottom() or self._signature is None
        self._signature = sig
        self._clear()
        failed = [m for m in self._pending_msgs if m.get("status") == "failed"]
        self._pending_msgs = failed
        if not messages and not failed:
            self.show_note(i18n.t("No messages yet — say hello."))
            self._signature = sig
            return True

        prev_dt, prev_dir = None, None
        n = len(messages)
        for i, m in enumerate(messages):
            dt = parse_ts(m.get("created_at", ""))
            outbound = m.get("direction") == "out"
            new_day = dt is not None and (prev_dt is None or dt.date() != prev_dt.date())
            if new_day:
                self._add_row(_DayChip(day_label(dt)), Qt.AlignCenter, gap=14 if i else 0)
            grouped = (not new_day and prev_dt is not None and dt is not None
                       and prev_dir == outbound and dt - prev_dt <= _GROUP_GAP)
            nxt = messages[i + 1] if i + 1 < n else None
            nxt_dt = parse_ts(nxt.get("created_at", "")) if nxt else None
            tail = not (nxt is not None and nxt_dt is not None and dt is not None
                        and (nxt.get("direction") == "out") == outbound
                        and nxt_dt.date() == dt.date() and nxt_dt - dt <= _GROUP_GAP)
            caption = ""
            if outbound and not grouped:
                who = (m.get("sender") or "").strip()
                caption = i18n.t("Auto-reply") if who.lower() == "bot" else who
            bubble = Bubble(dict(m), tail=tail, caption=caption)
            bubble.retry.connect(self._on_retry)
            self._bubbles.append(bubble)
            self._add_row(bubble, Qt.AlignRight if outbound else Qt.AlignLeft,
                          gap=(3 if grouped else 12) if i else 0)
            prev_dt, prev_dir = dt, outbound
        for m in failed:                        # unsent messages stay at the bottom
            bubble = Bubble(m, tail=True)
            bubble.retry.connect(self._on_retry)
            self._bubbles.append(bubble)
            self._add_row(bubble, Qt.AlignRight, gap=12 if self._bubbles[:-1] else 0)
        self._col.addStretch(0)
        self._refit()
        if stick:
            QTimer.singleShot(0, self.scroll_to_bottom)
        return True

    def _add_row(self, widget: QWidget, align, gap: int = 0):
        if gap:
            self._col.addSpacing(gap)
        self._col.addWidget(widget, alignment=align)

    # -- optimistic sends ---------------------------------------------------------
    def add_pending(self, text: str, sender: str = "") -> Bubble:
        now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        # a placeholder replaced by the first real message must not linger
        if not self._bubbles:
            self._clear()
        msg = {"direction": "out", "sender": sender, "text": text,
               "created_at": now, "status": "sending"}
        self._pending_msgs.append(msg)
        bubble = Bubble(msg, tail=True)
        bubble.retry.connect(self._on_retry)
        self._bubbles.append(bubble)
        if self._col.count() and self._col.itemAt(self._col.count() - 1).spacerItem():
            self._col.takeAt(self._col.count() - 1)
        self._add_row(bubble, Qt.AlignRight, gap=12 if len(self._bubbles) > 1 else 0)
        self._signature = None              # the next poll should redraw truthfully
        self._refit()
        QTimer.singleShot(0, self.scroll_to_bottom)
        return bubble

    def _on_retry(self, bubble: Bubble):
        self.retryRequested.emit(bubble.body.text(), bubble)

    # -- geometry -----------------------------------------------------------------
    def _refit(self):
        avail = self.viewport().width() - 36
        cap = max(220, min(int(avail * 0.72), 560))
        for b in self._bubbles:
            b.fit(cap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 24

    def scroll_to_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class _Entry(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                not (event.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class Composer(QFrame):
    """The reply box: grows with the text (one line to five), Enter sends,
    Shift+Enter is a new line."""

    submitted = Signal(str)

    MIN_H, MAX_H = 44, 136

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("waComposer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#waComposer {{ background: rgba(255,255,255,0.94);"
            f" border: 1px solid {theme.BORDER}; border-radius: 22px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 4, 6, 4)
        row.setSpacing(theme.SPACE_2)
        self.edit = _Entry()
        self.edit.setFrameShape(QFrame.NoFrame)
        self.edit.setFont(_font(14))
        self.edit.setPlaceholderText(i18n.t("Type a message — Enter to send, Shift+Enter for a new line"))
        self.edit.setStyleSheet("background: transparent; border: none;")
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.edit.submitted.connect(self._submit)
        self.edit.textChanged.connect(self._grow)
        row.addWidget(self.edit, stretch=1)
        self.count = QLabel("")
        self.count.setFont(_font(11, 600))
        self.count.setStyleSheet(f"color: {theme.ERR_INK}; background: transparent;")
        self.count.hide()
        row.addWidget(self.count)
        self.send_btn = C.button(i18n.t("Send"), "primary", on_click=self._submit)
        row.addWidget(self.send_btn, alignment=Qt.AlignBottom)
        self._grow()

    def _grow(self):
        doc = self.edit.document()
        h = int(doc.size().height()) + 14
        self.setFixedHeight(max(self.MIN_H + 8, min(self.MAX_H, h + 8)))
        n = len(self.edit.toPlainText())
        over = n > _MAX_TEXT
        self.count.setVisible(n > _MAX_TEXT - 300)
        self.count.setText(f"{n}/{_MAX_TEXT}")
        self.send_btn.setEnabled(bool(self.edit.toPlainText().strip()) and not over
                                 and self.edit.isEnabled())

    def _submit(self):
        text = self.edit.toPlainText().strip()
        if not text or len(text) > _MAX_TEXT or not self.edit.isEnabled():
            return
        self.edit.clear()
        self.submitted.emit(text)

    def set_active(self, active: bool, placeholder: str = ""):
        self.edit.setEnabled(active)
        self.send_btn.setEnabled(active and bool(self.edit.toPlainText().strip()))
        if placeholder:
            self.edit.setPlaceholderText(placeholder)

    def focus(self):
        self.edit.setFocus(Qt.OtherFocusReason)

    def restore(self, text: str):
        """Put text back after a failed send that the person chose not to retry."""
        self.edit.setPlainText(text)
        self.focus()


class Banner(QLabel):
    """A one-line notice above the composer — the 24-hour window, an opt-out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setFont(_font(12, 600))
        self.hide()

    def show_note(self, text: str, tone: str = "warn"):
        ink, bg = {"warn": (theme.WARN_INK, "rgba(202, 138, 4, 0.14)"),
                   "info": (theme.INFO_INK, "rgba(2, 132, 199, 0.12)"),
                   "err": (theme.ERR_INK, "rgba(220, 38, 38, 0.12)")}[tone]
        self.setStyleSheet(f"color: {ink}; background: {bg}; border-radius: 10px;"
                           f" padding: 8px 12px;")
        self.setText(text)
        self.show()
