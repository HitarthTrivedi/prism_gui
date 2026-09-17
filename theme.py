"""Industry design-system tokens, in Python.

style.qss is the source of truth for anything QSS can express. This module
mirrors the same tokens for the parts Qt stylesheets *can't* reach — the
custom-painted widgets (blueprint registration marks, the toggle switch, the
tool chip badges) all need real QColor values, and they must land on exactly
the same palette as the stylesheet or the seams show.

Keep the two in sync: every constant here has a twin in style.qss.

Four scales live here, and between them they are meant to be the whole
vocabulary — a screen that reaches outside them is what makes an app stop
looking like one product:

    colour    the NEUTRAL and ACCENT ramps, six surface roles, four semantics
    type      eight levels (TYPE / T_*), nothing else
    spacing   SPACE_1..SPACE_7 on a 4px base, plus four page-layout constants
    radius    R_CHIP / R_CONTROL / R_CARD, plus the R_PILL special case

Nothing is ever removed from this module. Nine other files import from it, so
a retired token is aliased onto its replacement rather than deleted — see
R_HERO and R_MODAL, which are now both R_CARD."""
from __future__ import annotations
import os
from PySide6.QtGui import QColor, QFont, QFontDatabase

import paths

# ── tonal ramps (one shared lightness scale, so step N of any role matches) ──
# Declared first because nearly every surface and semantic token below is a
# step of one of these rather than a hand-picked hex. That is the whole reason
# the two ramps exist: a value that is "a step" can be reasoned about, and a
# value that is a one-off cannot.
NEUTRAL = {
    100: "#f5f5f7", 200: "#e5e5ea", 300: "#d1d1d6", 400: "#a1a1aa",
    500: "#71717a", 600: "#52525b", 700: "#3f3f46", 800: "#27272a",
    900: "#09090b",
}
ACCENT_RAMP = {
    100: "rgba(0, 0, 0, 0.04)", 200: "rgba(0, 0, 0, 0.07)", 300: "rgba(0, 0, 0, 0.12)", 400: "#a1a1aa",
    500: "#71717a", 600: "#52525b", 700: "#3f3f46", 800: "#27272a",
    900: "#09090b",
}

# ── core roles ──────────────────────────────────────────────────────────────
TEXT = "#09090b"
ACCENT = "#09090b"
ACCENT_2 = "#27272a"

# ── the six surfaces, one value each ────────────────────────────────────────
CANVAS = "transparent"               # pure transparent canvas over dashboard wallpaper
CARD = "rgba(255, 255, 255, 0.65)"   # light frosted glassmorphism card surface
WELL = "rgba(0, 0, 0, 0.03)"         # inset subtle well inside a card
HAIRLINE = "rgba(0, 0, 0, 0.07)"     # hairline: card borders, row separators
DIVIDER = "rgba(0, 0, 0, 0.12)"      # divider: the heavier rule between regions
BORDER = "rgba(0, 0, 0, 0.10)"       # border: the drawn edge of a control
RAIL = "transparent"                 # transparent glass navbar

# Retired duplicates, kept as names because other files import them.
BG = CANVAS
SURFACE = NEUTRAL[200]
CARD_LINE = HAIRLINE
NEUTRAL_350 = "#9ca3af"

# ── semantic roles ──────────────────────────────────────────────────────────
OK = "#16a34a"
OK_INK = "#15803d"
OK_BG = "rgba(22, 163, 74, 0.14)"
WARN = "#ca8a04"
WARN_INK = "#a16207"
WARN_BG = "rgba(202, 138, 4, 0.14)"
ERR = "#dc2626"
ERR_INK = "#b91c1c"
ERR_BG = "rgba(220, 38, 38, 0.14)"
ERR_LINE = "rgba(220, 38, 38, 0.30)"

INFO = "#0284c7"
INFO_INK = "#0369a1"
INFO_BG = "rgba(2, 132, 199, 0.14)"

TAG_TONES = {
    "tagAccent": ("rgba(0, 0, 0, 0.06)", "#09090b"),
    "tagOutline": ("rgba(255, 255, 255, 0.85)", "#09090b"),
    "tagNeutral": ("rgba(0, 0, 0, 0.05)", "#27272a"),
    "tagOk": (OK_BG, OK_INK),
    "tagWarn": (WARN_BG, WARN_INK),
    "tagErr": (ERR_BG, ERR_INK),
}

# ── execution states ────────────────────────────────────────────────────────
STATUS = {
    "idle":         ("IDLE",         "#52525b", "rgba(0, 0, 0, 0.05)", "hollow"),
    "queued":       ("QUEUED",       "#52525b", "rgba(0, 0, 0, 0.05)", "hollow"),
    "planning":     ("PLANNING",     INFO_INK,  INFO_BG,               "pulse"),
    "running":      ("RUNNING",      INFO_INK,  INFO_BG,               "pulse"),
    "streaming":    ("STREAMING",    INFO_INK,  INFO_BG,               "pulse"),
    "waiting":      ("WAITING",      "#3f3f46", "rgba(0, 0, 0, 0.05)", "dashed"),
    "needs_review": ("NEEDS REVIEW", WARN_INK,  WARN_BG,               "solid"),
    "retrying":     ("RETRYING",     WARN_INK,  WARN_BG,               "spinner"),
    "completed":    ("COMPLETED",    OK_INK,    OK_BG,                 "check"),
    "failed":       ("FAILED",       ERR_INK,   ERR_BG,                "cross"),
    "cancelled":    ("CANCELLED",    "#71717a", "rgba(0, 0, 0, 0.05)", "square"),
    "skipped":      ("SKIPPED",      "#71717a", "rgba(0, 0, 0, 0.05)", "dash"),
}

# The words the engine and the existing panels already use for these states.
# Call sites should not have to translate: status("Done") and status("done")
# and status("completed") are the same row.
_STATUS_ALIASES = {
    "done": "completed", "complete": "completed", "ok": "completed",
    "success": "completed", "finished": "completed",
    "error": "failed", "failure": "failed", "err": "failed",
    "stopped": "cancelled", "aborted": "cancelled", "stopping": "cancelled",
    "pending": "queued", "not_started": "idle", "new": "idle",
    "routing": "planning", "thinking": "planning",
    "working": "running", "in_progress": "running", "active": "running",
    "blocked": "needs_review", "exhausted": "needs_review",
    "timed_out": "needs_review", "no_response": "needs_review",
    "review": "needs_review", "partial": "needs_review",
    "retry": "retrying", "failover": "retrying",
    "waiting_for_tool": "waiting",
}


def status(name: str) -> tuple[str, str, str, str]:
    """One STATUS row, tolerant of however the caller spells the state.

    The engine, the run screen and History each grew their own spelling of the
    same handful of states ("Done", "done", "completed"), which is how the app
    ended up with two different-looking success pills. Everything normalises
    through here instead: case, spaces and hyphens are all the same, unknown
    names fall back to idle rather than raising, and the caller never has to
    know which vocabulary produced the string.
    """
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = _STATUS_ALIASES.get(key, key)
    return STATUS.get(key, STATUS["idle"])


def status_key(name: str) -> str:
    """The canonical STATUS key for a state name — see status()."""
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = _STATUS_ALIASES.get(key, key)
    return key if key in STATUS else "idle"


# ── elevation ───────────────────────────────────────────────────────────────
# QSS has no box-shadow, so these are consumed by QGraphicsDropShadowEffect
# (see widgets.controls.elevate) rather than by the stylesheet. Kept as tokens
# anyway so the two cards that need a deeper shadow ask for it by name.
# (blur, y-offset, alpha) against ink #141e28.
#
# A hairline border is the default separator in this system and shadow is
# reserved for things that genuinely float — modals, dropdowns, a dragged row.
# A resting card in a grid gets no shadow: shadow on everything is what makes
# every element look like it is hovering, and it is also the reason
# shadows_enabled() defaults off.
SHADOW_INK = "#09090b"
SHADOW_CARD = (26, 8, 0.08)     # resting card
SHADOW_RAISED = (48, 16, 0.12)  # hero card, modals
SHADOW_HOVER = (32, 10, 0.14)   # stat card under the cursor
SHADOW_ACCENT = (20, 8, 0.25)   # primary button glow, in monochrome tone

# ── radii ───────────────────────────────────────────────────────────────────
# Three values, not six. The census counted thirteen distinct radii painting
# against six declared tokens — R_MODAL was used nowhere at all, R_CHIP had
# zero Python call sites, and 10px was the second most common radius in the
# stylesheet with no name whatsoever. Three steps is enough to say "chip",
# "control" and "card", and a fourth step is indistinguishable at these sizes.
#
# R_HERO and R_MODAL are aliases rather than deletions: four files import them
# and this module never removes a name.
R_CHIP = 6                      # pills, chips, badges, step marks, menu items
R_CONTROL = 8                   # buttons, inputs, rows, small cards
R_CARD = 12                     # panels, cards, modals, dialogs
R_HERO = R_CARD                 # was 14 — a hero card is a card
R_MODAL = R_CARD                # was 16 — a modal is a card
R_PILL = 999                    # the special case: a true pill, any height
# Not a scale step: half the width of a 4-8px bar, i.e. the radius that makes a
# progress bar or a scrollbar handle a capsule. Reach for R_CHIP for anything
# with content inside it.
R_MICRO = 4

# ── spacing ─────────────────────────────────────────────────────────────────
# A 4px base, seven steps, nothing between them. The census found 37 distinct
# content-margin tuples and 20 distinct layout spacings across the panels —
# 8, 9, 10 and 11 all shipping side by side, which no eye can distinguish and
# no reader can justify.
SPACE_1 = 4                     # inside a chip; icon to its own label
SPACE_2 = 8                     # between two controls in a row
SPACE_3 = 12                    # between rows inside a card
SPACE_4 = 16                    # between cards
SPACE_5 = 20                    # inside a card, edge to content
SPACE_6 = 28                    # page padding
SPACE_7 = 40                    # between major regions of a page

# The four page-layout constants every screen uses, named so a panel does not
# have to remember which SPACE step the scaffold called for.
PAGE_PAD = SPACE_6              # 28 — page edge to content, every screen
CARD_PAD = SPACE_5              # 20 — card edge to content
CARD_GAP = SPACE_4              # 16 — gutter between cards in a grid
ROW_GAP = SPACE_3               # 12 — between rows inside one card

# ── type ────────────────────────────────────────────────────────────────────
FONT_BODY = "Barlow"
FONT_HEADING = "Barlow Condensed"
# No mono face is vendored — it is wanted for ids, keys, device codes and
# paths, which are short and rare, and shipping a fourth font file to set nine
# characters of licence id is not worth the bundle size. A stack is used
# instead; every desktop this runs on has at least one of these.
FONT_MONO = "DejaVu Sans Mono"
FONT_MONO_STACK = ('"JetBrains Mono", "DejaVu Sans Mono", "Menlo", '
                   '"Consolas", monospace')
_FONT_DIR = paths.resource("assets", "fonts")

# Eight levels and nothing else.
#
# Twenty distinct font sizes shipped before this pass, nine of them inside a
# single 4px band — 11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15 — almost all
# introduced by ad hoc size= arguments rather than by any named role. Half a
# pixel of difference is not a decision anyone can see; it is only noise that
# stops the app reading as one system.
#
# Headings take their weight from condensation, not from size: Barlow
# Condensed at 600 reads as a heading at 15px, so nothing here is oversized.
# The old #h1 was 30px, which on a 900px-tall window was a sixth of the
# vertical budget spent on a greeting.
#
# Each entry is (family, pixel size, CSS weight, colour). Pixels, not points,
# because style.qss speaks pixels and the painted widgets have to land on the
# same metric — see font() below, which sets a pixel size on the QFont for
# exactly that reason. PT_ values are provided for the handful of call sites
# that already construct QFont(family, points).
TYPE = {
    # level          family         px  weight  colour
    "PAGE_TITLE": (FONT_HEADING,    24,   600,  "#09090b"),
    "SECTION":    (FONT_HEADING,    18,   600,  "#09090b"),
    "CARD_TITLE": (FONT_HEADING,    15,   600,  "#09090b"),
    "BODY":       (FONT_BODY,       14,   400,  "#18181b"),
    "SUPPORT":    (FONT_BODY,       13,   400,  "#3f3f46"),
    "META":       (FONT_BODY,       12,   500,  "#71717a"),
    "LABEL":      (FONT_HEADING,    11,   600,  "#52525b"),
    "MONO":       (FONT_MONO,       12,   500,  "#18181b"),
}

# The same eight as flat constants, for `from theme import T_BODY`.
T_PAGE_TITLE = TYPE["PAGE_TITLE"]
T_SECTION = TYPE["SECTION"]
T_CARD_TITLE = TYPE["CARD_TITLE"]
T_BODY = TYPE["BODY"]
T_SUPPORT = TYPE["SUPPORT"]
T_META = TYPE["META"]
T_LABEL = TYPE["LABEL"]
T_MONO = TYPE["MONO"]

# Which qss object name each level owns. The stylesheet keeps every one of the
# old names working — six heading levels collapse onto three real sizes — so
# no panel has to be edited for the scale to take effect.
TYPE_ROLE = {
    "PAGE_TITLE": "h2",         # also h1, #stat
    "SECTION": "h4",            # also h3, #statSm
    "CARD_TITLE": "h6",         # also h5
    "BODY": "",                 # the global default
    "SUPPORT": "body",          # also #lead
    "META": "meta",             # also #dim, #faint
    "LABEL": "kick",            # also #colHead
    "MONO": "mono",
}

_WEIGHT_TO_QT = {300: QFont.Light, 400: QFont.Normal, 500: QFont.Medium,
                 600: QFont.DemiBold, 700: QFont.Bold}


def type_pt(level: str) -> float:
    """A level's size in points, for QFont(family, points) call sites.

    Qt's point size is resolved against the screen's DPI and the stylesheet's
    is not, so the two agree only at 96dpi. Prefer font() below, which sets a
    pixel size and therefore matches style.qss on every display.
    """
    return TYPE.get(level, T_BODY)[1] * 0.75


def font(level: str = "BODY", weight: int = 0) -> QFont:
    """The QFont for one type level, sized in pixels.

    Pixels rather than points on purpose. A painted widget that asked for
    "10pt" and a stylesheet rule that asked for "13px" agree on one machine and
    diverge on the next, and the seam shows as a heading one step off the label
    beside it — which is the whole failure this module exists to prevent.
    """
    family, px, css_weight, _colour = TYPE.get(level, T_BODY)
    out = QFont(family)
    out.setPixelSize(px)
    out.setWeight(_WEIGHT_TO_QT.get(weight or css_weight, QFont.Normal))
    return out


def type_css(level: str = "BODY", colour: str = "") -> str:
    """One type level as a QSS fragment, for the widgets that set their own
    stylesheet. Always use this rather than retyping a size — a bare
    `font-size: 12.5px` is how the twenty-size sprawl happened."""
    family, px, weight, ink = TYPE.get(level, T_BODY)
    stack = FONT_MONO_STACK if level == "MONO" else f"'{family}'"
    return (f"font-family: {stack}; font-size: {px}px; "
            f"font-weight: {weight}; color: {colour or ink};")


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
#
# THIS TUPLE IS THE CONTRACT. Any accent-coloured hex written into style.qss
# must be one of these eleven or it will not rotate, and one permanently blue
# button in an otherwise green copy is worse than no rotation at all. Equally,
# any hex that must NOT rotate — every neutral, every semantic, every tool
# brand colour — has to be distinct from all eleven. The INFO role added above
# is composed entirely of ramp steps for exactly this reason: it rotates and it
# needed no new entry here.
_ACCENT_HEXES = ("#4480bb", "#628fbb", "#eff6fe", "#d8ebfd", "#b6d9fc",
                 "#7ebcf9", "#5e9eda", "#457eb7", "#306191", "#1f456a",
                 "#142d46")


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
    """Keep theme monochrome and consistent across all roles."""
    global ACCENT, ACCENT_2, ACCENT_RAMP, RAIL
    global INFO, INFO_INK, INFO_BG, TAG_TONES, STATUS, _BADGE_CYCLE
    ACCENT = "#09090b"
    ACCENT_2 = "#27272a"
    ACCENT_RAMP = {
        100: "rgba(0, 0, 0, 0.04)", 200: "rgba(0, 0, 0, 0.07)", 300: "rgba(0, 0, 0, 0.12)", 400: "#a1a1aa",
        500: "#71717a", 600: "#52525b", 700: "#3f3f46", 800: "#27272a",
        900: "#09090b",
    }
    RAIL = "#ffffff"
    INFO = "#27272a"
    INFO_INK = "#09090b"
    INFO_BG = "rgba(0, 0, 0, 0.04)"
    TAG_TONES = dict(TAG_TONES)
    TAG_TONES["tagAccent"] = ("rgba(0, 0, 0, 0.05)", "#09090b")
    TAG_TONES["tagOutline"] = (CARD, "#09090b")
    STATUS = dict(STATUS)
    for key in ("planning", "running", "streaming"):
        label, _ink, _bg, dot = STATUS[key]
        STATUS[key] = (label, INFO_INK, INFO_BG, dot)
    _BADGE_CYCLE = ["#18181b", "#27272a", "#3f3f46", "#52525b", "#71717a"]


def tone(name: str) -> str:
    """Resolve tone tokens in monochrome palette."""
    return {"accent": ACCENT, "ok": "#18181b", "warn": "#27272a",
            "muted": "#71717a"}.get(name, ACCENT)


def role_stylesheet(qss: str, hue: int) -> str:
    """Rewrite any blue or colored accent hexes in the stylesheet to monochrome water glass tokens."""
    swaps = {
        "#4480bb": "#09090b",
        "#628fbb": "#27272a",
        "#eff6fe": "rgba(0, 0, 0, 0.04)",
        "#d8ebfd": "rgba(0, 0, 0, 0.08)",
        "#b6d9fc": "rgba(0, 0, 0, 0.14)",
        "#7ebcf9": "#a1a1aa",
        "#5e9eda": "#71717a",
        "#457eb7": "#52525b",
        "#306191": "#27272a",
        "#1f456a": "#18181b",
        "#142d46": "#ffffff",
        "#f4f5f6": "#ffffff",
    }
    for original, replacement in swaps.items():
        qss = qss.replace(original, replacement)
        qss = qss.replace(original.upper(), replacement)
    return qss


# ── helpers for painted widgets ─────────────────────────────────────────────
def c(hex_or_role: str, alpha: float = 1.0) -> QColor:
    """QColor from a token, optionally at partial alpha."""
    col = QColor(hex_or_role)
    if alpha < 1.0:
        col.setAlphaF(alpha)
    return col


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque hexes."""
    def channel(value: str) -> float:
        value = value.lstrip("#")
        out = []
        for i in (0, 2, 4):
            v = int(value[i:i + 2], 16) / 255
            out.append(v / 12.92 if v <= 0.03928
                       else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    a, b = channel(fg), channel(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


_TOOL_BADGES = {
    "perplexity": "#18181b",
    "chatgpt": "#18181b",
    "openai": "#18181b",
    "claude": "#27272a",
    "anthropic": "#27272a",
    "gamma": "#27272a",
    "apollo": "#18181b",
    "notebooklm": "#18181b",
    "gemini": "#18181b",
}
_BADGE_CYCLE = ["#18181b", "#27272a", "#3f3f46", "#52525b", "#71717a"]


def badge_color(tool: str) -> str:
    key = (tool or "?").strip().lower()
    if key in _TOOL_BADGES:
        return _TOOL_BADGES[key]
    return _BADGE_CYCLE[sum(map(ord, key)) % len(_BADGE_CYCLE)]


def badge_initial(tool: str) -> str:
    """The single letter on a tool badge. NotebookLM is 'N', not 'No'."""
    return (tool or "?").strip()[:1].upper() or "?"


def over(alpha: float, fg: str = "#09090b", bg: str = None) -> str:
    """`fg` at `alpha` composited onto `bg`, as a solid hex."""
    base = bg or "#f4f4f5"
    fv, bv = fg.lstrip("#"), base.lstrip("#")
    out = []
    for i in (0, 2, 4):
        f, b = int(fv[i:i + 2], 16), int(bv[i:i + 2], 16)
        out.append(round(f * alpha + b * (1 - alpha)))
    return "#%02x%02x%02x" % tuple(out)


def tint(hex_colour: str, alpha_hex: str = "1f") -> str:
    """A brand colour at low opacity, for the pad behind its own icon.

    The design writes these as 8-digit hexes (#1DA487 + '1f'). Qt's stylesheet
    parser does not accept #RRGGBBAA, so this returns the rgba() form it does.
    """
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{int(alpha_hex, 16) / 255:.3f})"
