"""The design system's line icons, as real vectors.

Industry draws every icon as a 24×24 stroked path — 1.6px, round caps, round
joins, no fill — so the icon weight matches the hairline borders around it.
Emoji can't do that: they arrive pre-coloured, pre-filled, and at whatever
weight the platform font vendor chose, which is why the old dark theme's 📊/🔑
glyphs would look pasted-on here.

Paths are lifted verbatim from the design file. `icon()` returns a QIcon and
`pixmap()` a device-pixel-ratio-correct QPixmap, both tinted to any token
colour, both cached — these get requested once per repaint of a list row."""
from __future__ import annotations
from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

import theme

# name -> list of "d" attributes, stroked.
_STROKED: dict[str, list[str]] = {
    "prism":      ["M12 3l8 9-8 9-8-9z", "M12 3v18"],
    "check":      ["M4 12l5 5L20 6"],
    "search":     ["M4 11a7 7 0 1 0 14 0 7 7 0 1 0-14 0z", "M21 21l-4.3-4.3"],
    "pencil":     ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
    "present":    ["M3 4h18v12H3z", "M12 16v4", "M8 20h8"],
    "chevron-down":  ["M6 9l6 6 6-6"],
    "chevron-right": ["M9 6l6 6-6 6"],
    "chevron-left":  ["M15 6l-6 6 6 6"],
    "home":       ["M4 11l8-7 8 7", "M6 10v9h12v-9"],
    "grid":       ["M4 4h7v7H4z", "M13 4h7v7h-7z", "M4 13h7v7H4z", "M13 13h7v7h-7z"],
    "clock":      ["M4 12a8 8 0 1 0 16 0 8 8 0 1 0-16 0z", "M12 8v4l3 2"],
    "sliders":    ["M4 8h9", "M17 8h3", "M13 8a2 2 0 1 0 4 0 2 2 0 1 0-4 0z",
                   "M4 16h3", "M11 16h9", "M7 16a2 2 0 1 0 4 0 2 2 0 1 0-4 0z"],
    "folder":     ["M3 6h6l2 2h10v11H3z"],
    "file":       ["M6 3h8l4 4v14H6z", "M14 3v4h4"],
    "mic":        ["M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z",
                   "M6 11a6 6 0 0 0 12 0", "M12 17v4", "M8 21h8"],
    "paperclip":  ["M20 11l-8 8a4.5 4.5 0 0 1-6.4-6.4l8.4-8.4a3 3 0 0 1 4.3 "
                   "4.3l-8.3 8.3a1.5 1.5 0 0 1-2.2-2.1l7.5-7.5"],
    "plus":       ["M12 5v14", "M5 12h14"],
    "minus":      ["M5 12h14"],
    "help":       ["M4 12a8 8 0 1 0 16 0 8 8 0 1 0-16 0z",
                   "M9.6 9.4a2.5 2.5 0 0 1 4.2-1.2c1 .9.7 2-.3 2.7-.8.5-1.5 1-1.5 2",
                   "M12 16.5h.01"],
    "mail":       ["M3 6h18v12H3z", "M3 7l9 6 9-6"],
    "key":        ["M14 7a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M14 11h7", "M18 11v3"],
    "book":       ["M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z", "M8 7h7"],
    "globe":      ["M4 12a8 8 0 1 0 16 0 8 8 0 1 0-16 0z", "M4 12h16",
                   "M12 4a12 12 0 0 1 0 16 12 12 0 0 1 0-16z"],
    "lock":       ["M6 11h12v9H6z", "M9 11V8a3 3 0 0 1 6 0v3"],
    "chart":      ["M5 19V9", "M12 19V5", "M19 19v-6", "M3 21h18"],
    "archive":    ["M4 7h16v13H4z", "M3 3h18v4H3z", "M10 11h4"],
    "user":       ["M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M5 21a7 7 0 0 1 14 0"],
    "copy":       ["M9 9h11v11H9z", "M5 15V4h11"],
    "external":   ["M14 4h6v6", "M20 4l-9 9", "M18 14v6H4V6h6"],
    "trash":      ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13"],
    "x":          ["M6 6l12 12", "M18 6L6 18"],
    "alert":      ["M12 4l9 16H3z", "M12 10v4", "M12 17h.01"],
    "spinner":    ["M12 4v4", "M12 16v4", "M4 12h4", "M16 12h4"],
    "bulb":       ["M12 3a6 6 0 0 1 3.5 10.9V17h-7v-3.1A6 6 0 0 1 12 3z",
                   "M10 20h4"],
    "image":      ["M3 5h18v14H3z", "M3 16l5-5 4 4 3-3 6 6",
                   "M8 9a1.3 1.3 0 1 0 2.6 0A1.3 1.3 0 0 0 8 9z"],
    "video":      ["M3 6h12v12H3z", "M15 10l6-4v12l-6-4"],
    "code":       ["M9 8l-5 4 5 4", "M15 8l5 4-5 4"],
    "list":       ["M4 7h16", "M4 12h16", "M4 17h10"],
    "arrow-right": ["M4 12h15", "M13 6l6 6-6 6"],
    "arrow-up":   ["M12 20V5", "M6 11l6-6 6 6"],
    "stop":       ["M6 6h12v12H6z"],
}

# Icons the design fills rather than strokes.
_FILLED: dict[str, list[str]] = {
    "play": ["M7 5l12 7-12 7z"],
}

_cache: dict[tuple, QPixmap] = {}


def _svg(name: str, color: str, stroke: float) -> bytes:
    if name in _FILLED:
        body = "".join(
            f'<path d="{d}" fill="{color}" stroke="none"/>' for d in _FILLED[name])
    else:
        paths = _STROKED.get(name)
        if paths is None:
            raise KeyError(f"unknown icon {name!r}")
        body = "".join(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>' for d in paths)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'width="24" height="24">{body}</svg>').encode()


def pixmap(name: str, size: int = 18, color: str = theme.TEXT,
           stroke: float = 1.6) -> QPixmap:
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = (name, size, color, stroke, dpr)
    hit = _cache.get(key)
    if hit is not None:
        return hit

    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(_svg(name, color, stroke))).render(painter)
    painter.end()
    _cache[key] = px
    return px


def icon(name: str, size: int = 18, color: str = theme.TEXT,
         stroke: float = 1.6) -> QIcon:
    return QIcon(pixmap(name, size, color, stroke))


def button_icon(btn, name: str, size: int = 16, color: str = theme.TEXT,
                stroke: float = 1.6):
    """Set an icon on a button at its true pixel size (Qt otherwise scales to
    a 16px default that softens the 1.6px strokes)."""
    btn.setIcon(icon(name, size, color, stroke))
    btn.setIconSize(QSize(size, size))
    return btn
