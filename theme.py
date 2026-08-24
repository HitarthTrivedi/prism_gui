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
    100: "#f5f5f8", 200: "#e7e7ea", 300: "#d4d4d7", 400: "#b7b7ba",
    500: "#98989b", 600: "#7a7a7d", 700: "#5d5d60", 800: "#424244",
    900: "#2b2b2d",
}
ACCENT_RAMP = {
    100: "#eff6fe", 200: "#d8ebfd", 300: "#b6d9fc", 400: "#7ebcf9",
    500: "#5e9eda", 600: "#457eb7", 700: "#306191", 800: "#1f456a",
    900: "#142d46",
}

# ── core roles ──────────────────────────────────────────────────────────────
TEXT = "#1d1f20"
ACCENT = "#4480bb"
ACCENT_2 = "#628fbb"

# ── the six surfaces, one value each ────────────────────────────────────────
# The census found seventeen distinct greys shipping in the stylesheet with no
# rule about which meant what — three near-identical hairlines, two wells, two
# page greys. A reader cannot tell a deliberate step from a typo when the two
# look the same, so each of the six jobs below now has exactly one hex and
# every other near-duplicate is an alias onto it.
#
# RAIL is ACCENT_RAMP[900] deliberately, not a separate navy. It has to keep
# rotating with the role like everything else — a manager who switches profile
# should see the rail change too, and hardcoding a navy here would leave one
# permanently blue element in an otherwise green or amber copy.
CANVAS = "#f4f5f6"             # page background — the workspace behind cards
CARD = "#ffffff"               # card surface
WELL = "#f7f8f9"               # inset well inside a card
HAIRLINE = "#ececee"           # hairline: card borders, row separators
DIVIDER = "#d0d0d1"            # divider: the heavier rule between regions
BORDER = NEUTRAL[200]          # border: the drawn edge of a control
RAIL = ACCENT_RAMP[900]

# Retired duplicates, kept as names because other files import them.
# BG was #f2f2f3 and SURFACE #e9e9ea — a second page grey two units off CANVAS
# and a second border grey two units off NEUTRAL[200]. Neither difference was
# visible; both were reachable by accident.
BG = CANVAS
SURFACE = NEUTRAL[200]
CARD_LINE = HAIRLINE           # was #f0f0f1 — a third hairline, now the one
NEUTRAL_350 = "#c2c2c5"        # keyboard hints, inactive step numerals

# ── semantic roles ──────────────────────────────────────────────────────────
# Deliberately outside the accent ramp: these must NOT rotate with the role.
# "Won" has to stay green and "Lost" has to stay red in every profile, or the
# register stops being readable at a glance — which is the one thing it is for.
#
# Every _INK/_BG pair below clears WCAG AA (4.5:1) against its own tint. Two
# did not before this pass: WARN_INK #8a6d1f sat at 4.63 with no headroom, and
# OK_INK #1a7a5e at 4.88 — both close enough to the line that any future nudge
# to the tint would have pushed them under it without anyone noticing. They are
# now 6.15 and 5.96. The hue is unchanged in both cases; only the value moved.
OK = "#1DA487"
OK_INK = "#186b53"             # 5.96:1 on OK_BG (was #1a7a5e, 4.88:1)
OK_BG = "#eafaf3"
WARN = "#c9971f"
WARN_INK = "#755a14"           # 6.15:1 on WARN_BG (was #8a6d1f, 4.63:1)
WARN_BG = "#fff8e8"
ERR = "#8a2f2f"
ERR_INK = ERR                  # 7.37:1 on ERR_BG — named for symmetry
ERR_BG = "#fdeeee"
ERR_LINE = "#eecccc"

# INFO is the fourth semantic, and the only one that DOES rotate: "this is
# information" is the accent's own job, so it is three steps of the accent
# ramp rather than a separate blue. Because all three are already ramp steps
# they are already in _ACCENT_HEXES below and already rotate — no new hex has
# been introduced, which is the safest possible way to add a rotating role.
INFO = ACCENT_RAMP[600]
INFO_INK = ACCENT_RAMP[800]    # 9.11:1 on INFO_BG
INFO_BG = ACCENT_RAMP[100]

# The tag/pill tone table, as (background, ink). ONE table, because the census
# found controls.Chip carrying its own Python colour dict alongside the #tagXxx
# rules in style.qss and the two disagreeing for half the tones — a "warning"
# chip rendered grey-on-amber and a "success" chip blue-on-green. Both the
# painted path and the stylesheet now name these, so they cannot drift again.
# The keys are the QSS object names; TONES in controls.Pill maps onto the same
# values under its own shorter names.
TAG_TONES = {
    "tagAccent": (ACCENT_RAMP[100], ACCENT_RAMP[800]),
    "tagOutline": (CARD, ACCENT_RAMP[700]),
    "tagNeutral": (NEUTRAL[200], NEUTRAL[800]),
    "tagOk": (OK_BG, OK_INK),
    "tagWarn": (WARN_BG, WARN_INK),
    "tagErr": (ERR_BG, ERR_INK),
}

# ── execution states ────────────────────────────────────────────────────────
# The single status vocabulary for the whole app: name -> (label, ink, bg,
# dot). controls.StatusBadge is the only thing that should read it, and every
# surface that shows a state should use that badge, so "running" looks the same
# on the run screen, on Home and in History.
#
# WHAT IS DELIBERATELY ABSENT. The workbench audit enumerated which states the
# engine can actually produce, and two of the seven rows in the design brief
# cannot happen today:
#
#   paused            there is no pause primitive anywhere. AutomationWorker
#                     has stop() and nothing else — a one-way threading.Event.
#   waiting-for-user  every human gate is pre-run. Once automation.run() is on
#                     its thread, on_event is fire-and-forget and no callback
#                     can ask a question and block.
#
# Designing a badge for either would be inventing a state the product cannot
# enter, so neither is here. Both need an engine change first.
#
# One row IS here that nothing emits yet: `streaming`. The data behind it
# already exists — _smart_wait polls the response length every five seconds
# and holds the character count — it is simply never emitted. It is defined
# here so that when the one-line emit lands there is no second, differently
# coloured "streaming" invented alongside it.
STATUS = {
    # name              label            ink            bg            dot
    # The neutral states tint with NEUTRAL[200], not [100]. Step 100 is #f5f5f8
    # and the canvas is #f4f5f6 — one unit apart, so a "Queued" badge sitting on
    # the page rather than on a card had no visible fill at all. Step 200 reads
    # as a tint on white and on the canvas both.
    "idle":         ("IDLE",         NEUTRAL[700], NEUTRAL[200], "hollow"),
    "queued":       ("QUEUED",       NEUTRAL[700], NEUTRAL[200], "hollow"),
    "planning":     ("PLANNING",     INFO_INK,     INFO_BG,      "pulse"),
    "running":      ("RUNNING",      INFO_INK,     INFO_BG,      "pulse"),
    "streaming":    ("STREAMING",    INFO_INK,     INFO_BG,      "pulse"),
    # Waiting is neutral and dashed, NOT accent — the audit's tenth defect is
    # that "waiting" and "running" ship in the same colour with the same dot,
    # so the one state meaning "Prism is doing nothing but counting" looks
    # exactly like the state meaning "the tool is answering".
    "waiting":      ("WAITING",      NEUTRAL[800], NEUTRAL[200], "dashed"),
    "needs_review": ("NEEDS REVIEW", WARN_INK,     WARN_BG,      "solid"),
    "retrying":     ("RETRYING",     WARN_INK,     WARN_BG,      "spinner"),
    "completed":    ("COMPLETED",    OK_INK,       OK_BG,        "check"),
    "failed":       ("FAILED",       ERR_INK,      ERR_BG,       "cross"),
    "cancelled":    ("CANCELLED",    NEUTRAL[700], NEUTRAL[200], "square"),
    "skipped":      ("SKIPPED",      NEUTRAL[700], NEUTRAL[200], "dash"),
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
SHADOW_INK = "#141e28"
SHADOW_CARD = (10, 1, 0.05)     # resting card
SHADOW_RAISED = (44, 18, 0.16)  # hero card, modals
SHADOW_HOVER = (24, 10, 0.18)   # stat card under the cursor
SHADOW_ACCENT = (18, 8, 0.55)   # primary button glow, in the accent hue

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
    "PAGE_TITLE": (FONT_HEADING,    24,   600,  TEXT),
    "SECTION":    (FONT_HEADING,    18,   600,  TEXT),
    "CARD_TITLE": (FONT_HEADING,    15,   600,  TEXT),
    "BODY":       (FONT_BODY,       14,   400,  TEXT),
    "SUPPORT":    (FONT_BODY,       13,   400,  NEUTRAL[700]),
    "META":       (FONT_BODY,       12,   500,  NEUTRAL[600]),
    "LABEL":      (FONT_HEADING,    11,   600,  ACCENT_RAMP[700]),
    "MONO":       (FONT_MONO,       12,   500,  NEUTRAL[800]),
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
    """Point this module's accent constants at the role's hue.

    The painted widgets (toggle switch, tool chips, registration marks) read
    ACCENT and ACCENT_RAMP directly, so they have to move with the stylesheet
    or the seams show — which is the same reason this module exists at all.

    Everything derived from the ramp at import time has to be re-derived here.
    RAIL always was; INFO, the accent half of TAG_TONES, the STATUS rows in the
    accent tone and the unnamed-tool badge cycle are all in the same position
    and are rebuilt below. A derived constant that is not on this list is a
    latent bug: it will keep Prism's blue in a role that moved everything else.
    """
    global ACCENT, ACCENT_2, ACCENT_RAMP, RAIL
    global INFO, INFO_INK, INFO_BG, TAG_TONES, STATUS, _BADGE_CYCLE
    if hue == 210:                      # Prism's own blue: nothing to do
        return
    ACCENT = recolour("#4480bb", hue)
    ACCENT_2 = recolour("#628fbb", hue)
    ACCENT_RAMP = {step: recolour(value, hue)
                   for step, value in _BASE_ACCENT.items()}
    # Derived from the ramp at import time, so it has to be re-derived here or
    # the rail stays Prism blue in a role that has moved everything else.
    RAIL = ACCENT_RAMP[900]
    INFO = ACCENT_RAMP[600]
    INFO_INK = ACCENT_RAMP[800]
    INFO_BG = ACCENT_RAMP[100]
    TAG_TONES = dict(TAG_TONES)
    TAG_TONES["tagAccent"] = (ACCENT_RAMP[100], ACCENT_RAMP[800])
    TAG_TONES["tagOutline"] = (CARD, ACCENT_RAMP[700])
    STATUS = dict(STATUS)
    for key in ("planning", "running", "streaming"):
        label, _ink, _bg, dot = STATUS[key]
        STATUS[key] = (label, INFO_INK, INFO_BG, dot)
    _BADGE_CYCLE = [ACCENT_RAMP[800], NEUTRAL[700], ACCENT_RAMP[600],
                    ACCENT_RAMP[700], NEUTRAL[800], "#486077"]


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


# ── helpers for painted widgets ─────────────────────────────────────────────
def c(hex_or_role: str, alpha: float = 1.0) -> QColor:
    """QColor from a token, optionally at partial alpha (the QSS equivalent of
    color-mix(… N%, transparent))."""
    col = QColor(hex_or_role)
    if alpha < 1.0:
        col.setAlphaF(alpha)
    return col


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque hexes.

    Here rather than in a test because the status tones are the one part of
    this palette a future change can quietly break: a tint nudged two steps
    lighter still looks fine and its ink silently drops under 4.5:1. Anyone
    adding a tone should print this for the pair before shipping it. Every
    _INK/_BG pair in this module is >= 4.5.
    """
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


# Tool badges. Each tool now wears its own brand colour rather than a swatch
# off Prism's ramp. That is the point of the badge: on a run card showing four
# stages, the colour is how you tell at a glance that research went to
# Perplexity and the deck went to Gamma — which a row of near-identical blues
# could never do. These are other companies' brand colours, so they sit
# outside the accent ramp and do not rotate with the role.
#
# They are also, deliberately, 16-20px of the screen and never more: a tool's
# brand may fill a badge and may not fill a card, a header, a button or a
# border. The app belongs to Prism.
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


def over(alpha: float, fg: str = "#ffffff", bg: str = None) -> str:
    """`fg` at `alpha` composited onto `bg`, as a solid hex.

    The rail's text and glyphs are all white at some fraction. QSS takes
    rgba() happily, but the icons are rendered by handing a colour string to
    QSvgRenderer, and rgba() there is not dependable across Qt's SVG backends —
    a glyph that silently renders black on navy is invisible, which is the
    worst possible failure for a nav icon. Flattening against the rail gives
    the identical pixel with no renderer to trust.

    Defaults to the current RAIL, so it follows the role's hue like everything
    else. Callers wanting a fixed background pass one.
    """
    base = bg or RAIL
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
