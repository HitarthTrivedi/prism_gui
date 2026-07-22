"""The blueprint frame — the system's signature container.

In the design system a component is a *wireframe object*: a square, hairline-
bordered box with four registration crosshairs sitting half in and half out of
its corners (`.blueprint` + `.corner` in styles.css). CSS gets those marks from
pseudo-elements positioned outside the box; Qt stylesheets have no equivalent,
so the frame paints them itself.

Geometry, matched to the CSS: each crosshair is an 11px cross centred exactly
on a corner of the box, i.e. arms reaching 5px inward and 5px outward. The
widget therefore reserves MARK px of dead space on every side for the outward
half — content goes in `.content`, which is already inset past it."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

import theme

_ARM = 5          # crosshair arm length, each side of the corner
MARK = _ARM + 2   # dead space reserved so the outward arm isn't clipped


class BlueprintFrame(QFrame):
    def __init__(self, parent=None, padding=(18, 16, 18, 16), surface=False):
        """padding is (left, top, right, bottom) *inside* the hairline border.
        surface=True fills the box with --color-surface (the plan card on a
        white-ish canvas); the default leaves it transparent."""
        super().__init__(parent)
        self.setObjectName("blueprint")
        self._surface = surface
        self._marks = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARK, MARK, MARK, MARK)
        outer.setSpacing(0)
        # Named `panel`, not `body` — subclasses (the output stage card) use
        # `body` for their own text view, and a silent shadow here would
        # break the frame's painting.
        self.panel = QWidget(self)
        self.panel.setAttribute(Qt.WA_TranslucentBackground)
        outer.addWidget(self.panel)

        self.content = QVBoxLayout(self.panel)
        self.content.setContentsMargins(*padding)
        self.content.setSpacing(8)

    def set_marks(self, on: bool):
        """Turn the registration crosshairs off for a plain hairline box."""
        self._marks = on
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        box = self.panel.geometry()

        if self._surface:
            painter.fillRect(box, theme.c(theme.SURFACE))

        painter.setPen(QPen(theme.c(theme.DIVIDER), 1))
        # A 1px pen straddles the path, so shrink by one device pixel to keep
        # the stroke inside the box the layout actually measured.
        painter.drawRect(box.adjusted(0, 0, -1, -1))

        if not self._marks:
            return
        painter.setPen(QPen(theme.c(theme.TEXT, 0.55), 1))
        for x, y in ((box.left(), box.top()), (box.right(), box.top()),
                     (box.left(), box.bottom()), (box.right(), box.bottom())):
            painter.drawLine(x, y - _ARM, x, y + _ARM)
            painter.drawLine(x - _ARM, y, x + _ARM, y)
