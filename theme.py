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

# ── Soft Industry surfaces ──────────────────────────────────────────────────
# The redesign moves off the flat blueprint sheet: content now sits on white
# cards floating over a slightly cooler canvas, and the rail is the accent's
# own darkest step rather than a lighter shade of the page.
#
# RAIL is ACCENT_RAMP[900] deliberately, not a separate navy. It has to keep
# rotating with the role like everything else — a manager who switches profile
# should see the rail change too, and hardcoding a navy here would leave one
# permanently blue element in an otherwise green or amber copy.
CANVAS = "#f4f5f6"
CARD = "#ffffff"
CARD_LINE = "#f0f0f1"          # hairline between rows inside a card
RAIL = ACCENT_RAMP[900]
HAIRLINE = "#ececee"           # column separators on the canvas
WELL = "#f7f8f9"               # inset panel inside a card
NEUTRAL_350 = "#c2c2c5"        # keyboard hints, inactive step numerals

# ── semantic roles ──────────────────────────────────────────────────────────
# Deliberately outside the accent ramp: these must NOT rotate with the role.
# "Won" has to stay green and "Lost" has to stay red in every profile, or the
# register stops being readable at a glance — which is the one thing it is for.
OK = "#1DA487"
OK_INK = "#1a7a5e"
OK_BG = "#eafaf3"
WARN = "#c9971f"
WARN_INK = "#8a6d1f"
WARN_BG = "#fff8e8"
ERR = "#8a2f2f"
ERR_BG = "#fdeeee"
ERR_LINE = "#eecccc"

# ── elevation ───────────────────────────────────────────────────────────────
# QSS has no box-shadow, so these are consumed by QGraphicsDropShadowEffect
# (see widgets.controls.elevate) rather than by the stylesheet. Kept as tokens
# anyway so the two cards that need a deeper shadow ask for it by name.
# (blur, y-offset, alpha) against ink #141e28.
SHADOW_INK = "#141e28"
SHADOW_CARD = (10, 1, 0.05)     # resting card
SHADOW_RAISED = (44, 18, 0.16)  # hero card, modals
SHADOW_HOVER = (24, 10, 0.18)   # stat card under the cursor
SHADOW_ACCENT = (18, 8, 0.55)   # primary button glow, in the accent hue

# ── radii ───────────────────────────────────────────────────────────────────
R_CHIP = 7
R_CONTROL = 9
R_CARD = 12
R_HERO = 14
R_MODAL = 16
R_PILL = 999

# ── per-role accent ─────────────────────────────────────────────────────────
# A company running Prism has one copy per person, and the fastest way to know
# whose copy you are looking at — or which profile a manager has switched into
# — is that the whole app is a different colour.
#
# Only the HUE moves. Every swatch keeps the lightness and saturation of the
# blue it replaces, so contrast against text and canvas is identical in every
# role and nothing has to be re-checked for legibility. That is why this
# generates the ramp instead of listing nine hand-picked palettes: nine
# palettes drift, and one of them ends up with grey-on-grey somewhere.
_BASE_ACCENT = dict(ACCENT_RAMP)
_BASE_ACCENT_KEYS = ("ACCENT", "ACCENT_2")

# Everything the stylesheet says in the accent hue. Rewritten at load time by
# role_stylesheet(); the keys are the shipped blues, the values are what they
# become. Kept as a list so a hex that appears in more than one role of the
# design (ACCENT and ramp 600 are close but distinct) each map correctly.
_ACCENT_HEXES = ("#5980a6", "#728fab", "#eef6ff", "#d6ebff", "#b5d9fd",
                 "#94bce3", "#749dc4", "#597ea3", "#416180", "#2c455d",
                 "#1d2d3d")


def _hex_to_hls(value: str) -> tuple[float, float, float]:
    import colorsys
    value = value.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def _hls_to_hex(h: float, l: float, s: float) -> str:
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def recolour(value: str, hue: int) -> str:
    """One accent swatch, rotated to `hue`, keeping its lightness exactly."""
    _h, lightness, saturation = _hex_to_hls(value)
    return _hls_to_hex((hue % 360) / 360.0, lightness, saturation)


def role_palette(hue: int) -> dict[str, str]:
    """{shipped blue -> the role's version of it}, for every accent swatch."""
    return {value: recolour(value, hue) for value in _ACCENT_HEXES}


def apply_role(hue: int) -> None:
    """Point this module's accent constants at the role's hue.

    The painted widgets (toggle switch, tool chips, registration marks) read
    ACCENT and ACCENT_RAMP directly, so they have to move with the stylesheet
    or the seams show — which is the same reason this module exists at all.
    """
    global ACCENT, ACCENT_2, ACCENT_RAMP, RAIL
    if hue == 210:                      # Prism's own blue: nothing to do
        return
    ACCENT = recolour("#5980a6", hue)
    ACCENT_2 = recolour("#728fab", hue)
    ACCENT_RAMP = {step: recolour(value, hue)
                   for step, value in _BASE_ACCENT.items()}
    # Derived from the ramp at import time, so it has to be re-derived here or
    # the rail stays Prism blue in a role that has moved everything else.
    RAIL = ACCENT_RAMP[900]


def role_stylesheet(qss: str, hue: int) -> str:
    """Rewrite every accent hex in the stylesheet to the role's hue.

    A blunt string swap rather than a QSS parser, and safe because these
    eleven hexes are only ever used as the accent — the neutrals, the canvas
    and the one error red are separate values and are left alone, so the app
    keeps its identity and only the accent changes.
    """
    if hue == 210:
        return qss
    for original, replacement in role_palette(hue).items():
        qss = qss.replace(original, replacement)
        qss = qss.replace(original.upper(), replacement)
    return qss

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


# Tool badges. Each tool now wears its own brand colour rather than a swatch
# off Prism's ramp. That is the point of the badge: on a run card showing four
# stages, the colour is how you tell at a glance that research went to
# Perplexity and the deck went to Gamma — which a row of near-identical blues
# could never do. These are other companies' brand colours, so they sit
# outside the accent ramp and do not rotate with the role.
_TOOL_BADGES = {
    "perplexity": "#1FB8CD",
    "chatgpt": "#10A37F",
    "openai": "#10A37F",
    "claude": "#D97757",
    "anthropic": "#D97757",
    "gamma": "#9333EA",
    "apollo": "#2563EB",
    "notebooklm": "#4285F4",
    "gemini": "#4285F4",
}
# Anything unnamed is dealt a stable colour off the ramps, so a tool added
# later never renders un-styled — and never collides with a brand colour.
_BADGE_CYCLE = [ACCENT_RAMP[800], NEUTRAL[700], ACCENT_RAMP[600],
                ACCENT_RAMP[700], NEUTRAL[800], "#486077"]


def badge_color(tool: str) -> str:
    key = (tool or "?").strip().lower()
    if key in _TOOL_BADGES:
        return _TOOL_BADGES[key]
    return _BADGE_CYCLE[sum(map(ord, key)) % len(_BADGE_CYCLE)]


def badge_initial(tool: str) -> str:
    """The single letter on a tool badge. NotebookLM is 'N', not 'No'."""
    return (tool or "?").strip()[:1].upper() or "?"


def tint(hex_colour: str, alpha_hex: str = "1f") -> str:
    """A brand colour at low opacity, for the pad behind its own icon.

    The design writes these as 8-digit hexes (#1DA487 + '1f'). Qt's stylesheet
    parser does not accept #RRGGBBAA, so this returns the rgba() form it does.
    """
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{int(alpha_hex, 16) / 255:.3f})"
