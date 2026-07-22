"""Custom-painted controls the stylesheet can't produce.

Three shapes in the design have no Qt equivalent to style: the square sliding
switch, the tool chip with its filled initial-badge, and the small filled
check-square used as a step marker. Each is painted here against the same
tokens style.qss uses, plus the plain-QLabel helpers (kicker, heading, meta)
that every panel repeats."""
from __future__ import annotations
from PySide6.QtCore import (
    Qt, Signal, QSize, QRect, QPropertyAnimation, QEasingCurve, Property,
)
from PySide6.QtGui import QPainter, QPen, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy,
)

import theme
from widgets import icons


# ── text helpers ────────────────────────────────────────────────────────────
def track(widget, em: float):
    """Apply letter-spacing. QSS has no letter-spacing property, and this
    system leans on tracked uppercase condensed labels everywhere, so the
    spacing has to be set on the QFont directly."""
    font = widget.font()
    font.setLetterSpacing(QFont.PercentageSpacing, 100 + em * 100)
    widget.setFont(font)
    return widget


def kicker(text: str, muted: bool = False) -> QLabel:
    """Condensed, tracked, uppercase section label (.kick)."""
    lbl = QLabel(text.upper())
    lbl.setObjectName("kickMuted" if muted else "kick")
    return track(lbl, 0.12)


def heading(text: str, level: int = 4) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(f"h{level}")
    return track(lbl, -0.015)


def meta(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("meta")
    return lbl


def icon_label(icon_name: str, text: str, size: int = 16,
               color: str = None) -> QFrame:
    """A line icon next to a caption — the system's replacement for the
    emoji-prefixed labels the app used to carry."""
    wrap = QFrame()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    glyph = QLabel()
    glyph.setPixmap(icons.pixmap(icon_name, size, color or theme.ACCENT))
    row.addWidget(glyph)
    row.addWidget(QLabel(text), stretch=1)
    return wrap


class Chip(QFrame):
    """A small status tag with a leading line icon. A QLabel can show a pixmap
    or text but never both, so the pair needs its own two-label box."""

    def __init__(self, text: str = "", icon_name: str = "", style: str = "tagOk",
                 parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 3, 9, 3)
        row.setSpacing(5)
        self._icon = QLabel()
        row.addWidget(self._icon)
        self._text = QLabel()
        row.addWidget(self._text)
        self.set(text, icon_name, style)

    def set(self, text: str, icon_name: str = "", style: str = "tagOk"):
        color = {
            "tagOk": theme.ACCENT_RAMP[700],
            "tagWarn": theme.NEUTRAL[600],
            "tagErr": "#8a2f2f",
            "tagAccent": theme.ACCENT_RAMP[800],
            "tagOutline": theme.ACCENT_RAMP[700],
        }.get(style, theme.NEUTRAL[600])
        self._text.setText(text)
        self._text.setStyleSheet(f"font-size: 11.5px; color: {color};")
        if icon_name:
            self._icon.setPixmap(icons.pixmap(icon_name, 13, color))
        self._icon.setVisible(bool(icon_name))
        self.setObjectName(style)
        self.style().unpolish(self)
        self.style().polish(self)


# ── switch ──────────────────────────────────────────────────────────────────
class ToggleSwitch(QAbstractButton):
    """The 34×20 square switch. Off: hairline outline, knob left. On: filled
    accent, knob right. Square — no pill, no radius; this system has none."""

    W, H = 34, 20
    KNOB = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        self._pos = 2.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(float(self.W - self.KNOB - 2 if on else 2))
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float):
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self) -> QSize:
        return QSize(self.W, self.H)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        on = self.isChecked()
        # Off, the track has to carry the whole shape on its own — against the
        # sidebar's surface the 16%-ink divider all but disappears, so the
        # outline steps up to neutral-400 and the knob down to neutral-500.
        painter.setPen(QPen(theme.c(theme.ACCENT if on else theme.NEUTRAL[400]), 1))
        painter.setBrush(theme.c(theme.ACCENT) if on else theme.c(theme.BG))
        painter.drawRect(0, 0, self.W - 1, self.H - 1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c(theme.BG if on else theme.NEUTRAL[500]))
        painter.drawRect(QRect(int(self._pos), 3, self.KNOB, self.KNOB))


# ── step marker ─────────────────────────────────────────────────────────────
class StepMark(QLabel):
    """The square that leads a plan row: filled accent + white tick when the
    step is in the run, hairline outline when it's been switched off."""

    SIZE = 22

    def __init__(self, included: bool = True, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._included = included
        self._refresh()

    def set_included(self, included: bool):
        if included != self._included:
            self._included = included
            self._refresh()

    def _refresh(self):
        self.setPixmap(icons.pixmap("check", 14,
                                    "#ffffff" if self._included else theme.NEUTRAL[400]))
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("on", self._included)
        self.setObjectName("stepMark")
        self.style().unpolish(self)
        self.style().polish(self)


# ── tool chip ───────────────────────────────────────────────────────────────
class ToolChip(QAbstractButton):
    """`.tool` — a hairline chip carrying a filled square badge with the
    tool's initial, its name, and a chevron. Clicking opens the list of every
    tool available for that stage, so the chip *is* the agent picker."""

    changed = Signal(str)
    BADGE = 19
    _PAD_L, _PAD_R, _GAP = 4, 9, 8

    def __init__(self, tools: list[str], current: str = "", suggested: str = "",
                 parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._tools = list(tools)
        self._suggested = suggested
        self._current = current or (self._tools[0] if self._tools else "")
        self._font = QFont(theme.FONT_BODY, 10)
        self._badge_font = QFont(theme.FONT_HEADING, 9)
        self._badge_font.setWeight(QFont.DemiBold)
        self.clicked.connect(self._open_menu)
        self._resize_to_text()

    # -- state ------------------------------------------------------------
    def current(self) -> str:
        return self._current

    def set_current(self, tool: str):
        if tool and tool != self._current:
            self._current = tool
            self._resize_to_text()
            self.update()

    def _resize_to_text(self):
        width = (self._PAD_L + self.BADGE + self._GAP
                 + QFontMetrics(self._font).horizontalAdvance(self._current)
                 + 6 + 15 + self._PAD_R)
        self.setFixedSize(width, 29)

    def _open_menu(self):
        if not self._tools:
            return
        menu = QMenu(self)
        for name in self._tools:
            label = f"{name}  ★ suggested" if name == self._suggested else name
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(name == self._current)
            action.triggered.connect(lambda _=False, n=name: self._pick(n))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _pick(self, name: str):
        if name != self._current:
            self.set_current(name)
            self.changed.emit(name)

    # -- paint ------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        if not self.isEnabled():
            # A chip on a dropped step keeps its shape but stops competing —
            # painted state, so QSS :disabled can't reach it.
            painter.setOpacity(0.4)

        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(rect, theme.c(theme.SURFACE))
        hovered = self.underMouse()
        painter.setPen(QPen(theme.c(theme.TEXT, 0.4 if hovered else 0.16), 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        badge = QRect(self._PAD_L, (rect.height() - self.BADGE) // 2,
                      self.BADGE, self.BADGE)
        painter.fillRect(badge, theme.c(theme.badge_color(self._current)))
        painter.setPen(theme.c("#ffffff"))
        painter.setFont(self._badge_font)
        painter.drawText(badge, Qt.AlignCenter,
                         (self._current[:1] or "?").upper())

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(theme.c(theme.TEXT))
        painter.setFont(self._font)
        text_x = badge.right() + self._GAP
        painter.drawText(QRect(text_x, 0, rect.width() - text_x - self._PAD_R - 15,
                               rect.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self._current)

        chevron = icons.pixmap("chevron-down", 15, theme.NEUTRAL[500])
        painter.drawPixmap(rect.width() - self._PAD_R - 15,
                           (rect.height() - 15) // 2, chevron)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)
