"""Depth helpers. Qt QSS has no box-shadow, so premium glow/elevation are
applied as QGraphicsDropShadowEffect. Note: a widget can hold only ONE
QGraphicsEffect — never combine these with an opacity fade on the SAME
widget (put the fade on a child/parent instead)."""
from __future__ import annotations
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget


def apply_glow(widget: QWidget, color=(139, 92, 246), blur: int = 34, alpha: int = 150):
    """Colored bloom behind an accent element (primary buttons, active chips)."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setColor(QColor(color[0], color[1], color[2], alpha))
    eff.setOffset(0, 0)
    widget.setGraphicsEffect(eff)
    return eff


def apply_elevation(widget: QWidget, blur: int = 40, alpha: int = 120, dy: int = 14):
    """Soft downward shadow so glass panels read as floating above the canvas."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setColor(QColor(0, 0, 0, alpha))
    eff.setOffset(0, dy)
    widget.setGraphicsEffect(eff)
    return eff
