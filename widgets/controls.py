"""Custom-painted controls the stylesheet can't produce.

Three shapes in the design have no Qt equivalent to style: the square sliding
switch, the tool chip with its filled initial-badge, and the small filled
check-square used as a step marker. Each is painted here against the same
tokens style.qss uses, plus the plain-QLabel helpers (kicker, heading, meta)
that every panel repeats."""
from __future__ import annotations
import os

from PySide6.QtCore import (
    Qt, Signal, QSize, QRect, QRectF, QPropertyAnimation, QEasingCurve, Property,
)
from PySide6.QtGui import (
    QPainter, QPen, QFont, QFontMetrics, QBrush, QColor, QPainterPath,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QMenu, QSizePolicy, QVBoxLayout, QWidget,
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


# ── elevation ───────────────────────────────────────────────────────────────
def shadows_enabled() -> bool:
    """Whether to hang a QGraphicsDropShadowEffect off every card. OFF by
    default, and that default is the fix for the blank-panels bug.

    A widget carrying a QGraphicsEffect is painted through a separate pipeline
    — and that pipeline draws the WHOLE widget, background and children
    included, not just the shadow. On some setups (software rasterisers,
    virtual machines, remote desktop, older drivers) it produces nothing at
    all. The card then reserves its space in the layout and never paints, so
    the screen shows correctly-sized gaps where the content should be, while
    everything WITHOUT an effect — headings, the timeline dots — draws
    normally. It reads as the app having lost your work rather than as a
    graphics fault, which is what made it so hard to report.

    A soft shadow is not worth that. Cards now read as cards from their white
    fill and hairline border, which are ordinary QSS and paint everywhere,
    and the design's own predecessor used hairline borders anyway.

    Opt back in per machine if you want the lift and know it works there:

        PRISM_SHADOWS=1           one run
        ~/.prism/config.json      "shadows": true, to make it stick
    """
    if os.environ.get("PRISM_SHADOWS"):
        return True
    try:
        import core_bridge as CB
        if (CB.config.load() or {}).get("shadows"):
            return True
    except Exception:
        pass                    # unreadable config must not turn them back on
    return False


def elevate(widget: QWidget, spec=None, hue: str = None) -> QWidget:
    """Give a widget the design's soft drop shadow.

    QSS has no box-shadow, so every card in the Soft Industry direction gets
    its lift from a QGraphicsDropShadowEffect instead. The design's shadows are
    all large-blur, low-alpha and offset downward — `0 20px 44px -18px
    rgba(20,30,40,0.16)` and friends. Qt has no spread, so the negative spread
    is absorbed by using the blur radius the design's spread implies rather
    than its literal value; the visual weight matches.

    Note the caller must leave margin around the widget for the shadow to fall
    into, or the parent layout clips it. Cards are laid out with that in mind.

    Returns the widget either way, so callers never have to care whether the
    shadow was actually applied — see shadows_enabled().
    """
    if not shadows_enabled():
        return widget
    blur, dy, alpha = spec or theme.SHADOW_CARD
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    effect.setColor(theme.c(hue or theme.SHADOW_INK, alpha))
    widget.setGraphicsEffect(effect)
    return widget


class Card(QFrame):
    """The one surface this redesign is built out of: a white rounded panel
    floating over the canvas.

    `stripe` paints the 3px accent bar across the top that replaces the
    blueprint registration marks the old design cornered its panels with. The
    marks said "engineering drawing"; the stripe says the same thing in a way
    that survives being put on a rounded card, which is what the whole
    direction turns on.
    """

    def __init__(self, stripe: bool = False, radius: int = theme.R_CARD,
                 raised: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._radius = radius
        self._stripe = stripe
        self.setAttribute(Qt.WA_StyledBackground, True)
        # The border is what separates a card from the canvas now that the drop
        # shadow is off by default — see shadows_enabled(). Plain QSS, so it
        # paints through the ordinary path on every machine, which the shadow
        # did not.
        self.setStyleSheet(
            f"#card {{ background: {theme.CARD}; border-radius: {radius}px; "
            f"border: 1px solid {theme.HAIRLINE}; }}")
        elevate(self, theme.SHADOW_RAISED if raised else theme.SHADOW_CARD)

    def body(self, margins=(20, 20, 20, 20), spacing: int = 0) -> QVBoxLayout:
        """The card's own column, inset past the stripe."""
        col = QVBoxLayout(self)
        top = margins[1] + (3 if self._stripe else 0)
        col.setContentsMargins(margins[0], top, margins[2], margins[3])
        col.setSpacing(spacing)
        return col

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._stripe:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Clipped to the card's own rounded rect so the bar picks up the top
        # two corners instead of squaring them off.
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        painter.setClipPath(clip)
        painter.fillRect(QRect(0, 0, self.width(), 3), theme.c(theme.ACCENT))


class Pill(QLabel):
    """The rounded status tag the design uses everywhere — "Done", "Quoted",
    "3 waiting". Tone names map to the semantic roles, not the accent, so a
    "Won" pill stays green in every role."""

    TONES = {
        "accent": (theme.ACCENT_RAMP[100], theme.ACCENT_RAMP[800]),
        "neutral": (theme.NEUTRAL[100], theme.NEUTRAL[700]),
        "ok": (theme.OK_BG, theme.OK_INK),
        "warn": (theme.WARN_BG, theme.WARN_INK),
        "err": (theme.ERR_BG, theme.ERR),
        "quiet": (theme.NEUTRAL[100], theme.NEUTRAL[500]),
    }

    def __init__(self, text: str = "", tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str):
        bg, ink = self.TONES.get(tone, self.TONES["neutral"])
        self.setStyleSheet(
            f"background: {bg}; color: {ink}; border-radius: {theme.R_PILL}px;"
            f" font-size: 11px; padding: 3px 11px;")


class ToolBadge(QLabel):
    """The rounded square carrying a tool's initial in its own brand colour."""

    def __init__(self, tool: str, size: int = 28, radius: int = 7, parent=None):
        super().__init__(theme.badge_initial(tool), parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background: {theme.badge_color(tool)}; color: #ffffff;"
            f" border-radius: {radius}px; font-family: '{theme.FONT_HEADING}';"
            f" font-weight: 700; font-size: {max(9, int(size * 0.43))}px;")


class IconPad(QLabel):
    """A line icon on a soft tinted pad — the design's standard leading glyph
    for a stat card, an add-on row or a timeline dot."""

    def __init__(self, icon_name: str, hue: str = None, size: int = 30,
                 radius: int = 8, glyph: int = 15, parent=None):
        super().__init__(parent)
        hue = hue or theme.ACCENT
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(icons.pixmap(icon_name, glyph, hue))
        self.setStyleSheet(
            f"background: {theme.tint(hue)}; border-radius: {radius}px;")


class Avatar(QLabel):
    """Circular initial. The rail, the profile row and every register line use
    the same one so a customer reads the same in all three."""

    def __init__(self, name: str, size: int = 28, hue: str = None, parent=None):
        super().__init__((name or "?").strip()[:1].upper() or "?", parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background: {hue or theme.ACCENT}; color: #ffffff;"
            f" border-radius: {size // 2}px;"
            f" font-family: '{theme.FONT_HEADING}'; font-weight: 700;"
            f" font-size: {max(10, int(size * 0.42))}px;")


class Sparkline(QWidget):
    """The seven-bar mini chart on the dashboard stat cards.

    Painted rather than charted on purpose: it carries no axis, no scale and no
    tooltip, and is not meant to be read as data — it is there to say "this
    number has a direction". The last three bars take full colour and the
    earlier ones fade back, which is what gives the shape its read.
    """

    def __init__(self, values: list[float], hue: str = None, parent=None):
        super().__init__(parent)
        self._values = list(values) or [0]
        self._hue = hue or theme.ACCENT
        self.setFixedHeight(22)
        self.setMinimumWidth(len(self._values) * 6)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        top = max(self._values) or 1
        count = len(self._values)
        bar, gap = 4, 2
        span = count * bar + (count - 1) * gap
        x = self.width() - span                 # right-aligned, per the design
        for i, value in enumerate(self._values):
            height = max(2, round(self.height() * (value / top)))
            # Recent bars at full strength, older ones stepped back — two
            # tints, not a gradient, so it reads at 22px tall.
            fade = 1.0 if i >= count - 3 else (0.45 if i >= count - 5 else 0.22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(theme.c(self._hue, fade)))
            painter.drawRoundedRect(
                QRectF(x + i * (bar + gap), self.height() - height, bar, height),
                2, 2)


class ProgressBar(QWidget):
    """The 5px rounded run-progress bar on an active-run card."""

    def __init__(self, fraction: float = 0.0, hue: str = None, parent=None):
        super().__init__(parent)
        self._fraction = max(0.0, min(1.0, fraction))
        self._hue = hue or theme.ACCENT
        self.setFixedHeight(5)

    def set_fraction(self, fraction: float):
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c(theme.CARD_LINE))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._fraction <= 0:
            return
        painter.setBrush(theme.c(self._hue))
        painter.drawRoundedRect(
            QRectF(0, 0, self.width() * self._fraction, self.height()), 3, 3)


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
    """The 32×18 pill switch. Off: neutral track, knob left. On: filled accent,
    knob right.

    This used to be square, on the grounds that the system had no radius
    anywhere. The Soft Industry direction reverses that premise — everything
    now carries one — so the switch rounds to a true pill and the knob to a
    circle, and the track no longer needs an outline to hold its shape.
    """

    W, H = 32, 18
    KNOB = 12

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
        painter.setRenderHint(QPainter.Antialiasing, True)
        on = self.isChecked()
        radius = self.H / 2
        painter.setPen(Qt.NoPen)
        # The switch now lives on the dark rail, where a hairline outline over
        # neutral-200 vanishes. A filled track carries the off state instead:
        # white at 18% reads against the navy without needing a border.
        painter.setBrush(theme.c(theme.ACCENT) if on
                         else theme.c("#ffffff", 0.18))
        painter.drawRoundedRect(QRectF(0, 0, self.W, self.H), radius, radius)
        painter.setBrush(theme.c("#ffffff"))
        inset = (self.H - self.KNOB) / 2
        painter.drawEllipse(QRectF(self._pos, inset, self.KNOB, self.KNOB))


# ── step marker ─────────────────────────────────────────────────────────────
class StepMark(QLabel):
    """The rounded square that leads a plan row: filled accent + white tick
    when the step is in the run, flat neutral-200 when it's been switched off.

    The off state drops its tick entirely rather than showing a grey one. A
    faint tick still reads as "ticked" at a glance, which is exactly backwards
    for the one control on the screen whose whole job is to say this step will
    not run."""

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
        if self._included:
            self.setPixmap(icons.pixmap("check", 13, "#ffffff"))
        else:
            self.clear()
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

        # The chip is a soft well now rather than an outlined box: the plan
        # rows it sits on are already white cards, so a second hairline inside
        # one only added noise. Hover lifts the fill instead of the border.
        hovered = self.underMouse()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c(theme.NEUTRAL[200] if hovered else theme.WELL))
        painter.drawRoundedRect(QRectF(rect), 8, 8)

        badge = QRectF(self._PAD_L, (rect.height() - self.BADGE) / 2,
                       self.BADGE, self.BADGE)
        painter.setBrush(theme.c(theme.badge_color(self._current)))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(theme.c("#ffffff"))
        painter.setFont(self._badge_font)
        painter.drawText(badge, Qt.AlignCenter,
                         theme.badge_initial(self._current))

        painter.setPen(theme.c(theme.TEXT))
        painter.setFont(self._font)
        text_x = int(badge.right()) + self._GAP
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
