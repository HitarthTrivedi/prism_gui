"""Industry design-system tokens, in Python.

style.qss is the source of truth for anything QSS can express. This module
mirrors the same tokens for the parts Qt stylesheets *can't* reach — the
custom-painted widgets (blueprint registration marks, the toggle switch, the
tool chip badges) all need real QColor values, and they must land on exactly
the same palette as the stylesheet or the seams show.

Keep the two in sync: every constant here has a twin in style.qss."""
from __future__ import annotations
import os
from PySide6.QtGui import QColor, QFontDatabase

import paths

# ── core roles ──────────────────────────────────────────────────────────────
BG = "#f2f2f3"
SURFACE = "#e9e9ea"
TEXT = "#1d1f20"
ACCENT = "#5980a6"
ACCENT_2 = "#728fab"

# ── tonal ramps (one shared lightness scale, so step N of any role matches) ──
NEUTRAL = {
    100: "#f5f5f8", 200: "#e7e7ea", 300: "#d4d4d7", 400: "#b7b7ba",
    500: "#98989b", 600: "#7a7a7d", 700: "#5d5d60", 800: "#424244",
    900: "#2b2b2d",
}
ACCENT_RAMP = {
    100: "#eef6ff", 200: "#d6ebff", 300: "#b5d9fd", 400: "#94bce3",
    500: "#749dc4", 600: "#597ea3", 700: "#416180", 800: "#2c455d",
    900: "#1d2d3d",
}

# --color-divider: 16% ink over the canvas.
DIVIDER = "#d0d0d1"

# ── type ────────────────────────────────────────────────────────────────────
FONT_BODY = "Barlow"
FONT_HEADING = "Barlow Condensed"
_FONT_DIR = paths.resource("assets", "fonts")


def load_fonts() -> None:
    """Register the vendored Barlow family. The whole system is built on the
    Barlow / Barlow Condensed pairing — without it Qt silently falls back to a
    default sans and every heading loses its condensed proportions, so the
    fonts ship with the app rather than being assumed present on the box."""
    if not os.path.isdir(_FONT_DIR):
        return
    for name in sorted(os.listdir(_FONT_DIR)):
        if name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(_FONT_DIR, name))


# ── helpers for painted widgets ─────────────────────────────────────────────
def c(hex_or_role: str, alpha: float = 1.0) -> QColor:
    """QColor from a token, optionally at partial alpha (the QSS equivalent of
    color-mix(… N%, transparent))."""
    col = QColor(hex_or_role)
    if alpha < 1.0:
        col.setAlphaF(alpha)
    return col


# Tool badges. The mock assigns each tool a dark square with its initial; the
# named ones keep the exact swatch from the design, anything else is dealt a
# stable colour off the ramps so a new tool never renders un-styled.
_TOOL_BADGES = {
    "perplexity": ACCENT_RAMP[800],
    "chatgpt": NEUTRAL[700],
    "gamma": ACCENT_RAMP[600],
}
_BADGE_CYCLE = [ACCENT_RAMP[800], NEUTRAL[700], ACCENT_RAMP[600],
                ACCENT_RAMP[700], NEUTRAL[800], "#486077"]


def badge_color(tool: str) -> str:
    key = (tool or "?").strip().lower()
    if key in _TOOL_BADGES:
        return _TOOL_BADGES[key]
    return _BADGE_CYCLE[sum(map(ord, key)) % len(_BADGE_CYCLE)]
