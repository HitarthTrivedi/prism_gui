"""
Leads & Outreach — lead filters, the Apollo / Sales Navigator column
─────────────────────────────────────────────────────────────────────
Who a list is for, as filters. Every facet holds values to INCLUDE and values
to EXCLUDE — "Location: anywhere, except India" — shown as chips under the
facet's name: the info tint for in, the error tint with a leading minus for
out. A click on a chip flips its side; its small x removes it. Seniority and
Function pick from fixed lists, company headcount, annual revenue and years in
the role are multi-select bands, and "changed jobs in the last 90 days" is a
switch.

The panel only EDITS a `prospector.filters.SearchSpec`. What a filter means —
which includes steer the Exa search and which are enforced on every person who
comes back — lives beside the engine, not here. Inside the panel the spec is
the single source of truth: an edit changes the spec, then every widget is
redrawn from it, so a chip can never say something a run will not ask.

No scroll area of its own. The cockpit's rail (addons/leads/cockpit.py)
scrolls it at ~280px of content width, so nothing in here may ask for more:
long values elide instead of widening the rail, and rows of chips and bands
wrap (widgets.controls.FlowLayout) instead of clipping.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QStyle, QStyleOption, QToolButton, QVBoxLayout,
    QWidget,
)

import i18n
import theme
from widgets import controls as C
from widgets import icons
from prospector.filters import (
    BAND_FACETS, CLOSED_FACETS, FACET_LABELS, GUIDES_ONLY, HEADCOUNT,
    INDUSTRY_SUGGESTIONS, LOCATION_SUGGESTIONS, REVENUE, TITLE_SUGGESTIONS,
    YEARS_IN_ROLE, SearchSpec, label_of, parse_location_text, read_place_text,
)

# The column, top to bottom. "changed_jobs_90d" is the one switch, not a facet.
_GROUPS = (
    ("People", ("locations", "job_titles", "seniority", "functions")),
    ("Company", ("industries", "headcount", "revenue", "companies", "company_hq")),
    ("Activity", ("years_in_role", "changed_jobs_90d")),
    ("Keywords", ("keywords",)),
)
# Where nearly every search starts, so these two open with the panel.
_OPEN_AT_START = frozenset({"locations", "job_titles"})
_BANDS = {"headcount": HEADCOUNT, "revenue": REVENUE, "years_in_role": YEARS_IN_ROLE}
# Bands checked on the company's record (filters.match_company). A company
# whose size is not on record is let through and counted unverified, and the
# editor says so — a band reads like a promise otherwise.
_ON_RECORD = frozenset({"headcount", "revenue"})
_PLACEHOLDERS = {
    "locations": "Add a country, region or city",
    "job_titles": "Add a job title",
    "seniority": "Find a seniority level",
    "functions": "Find a function",
    "industries": "Add an industry",
    "companies": "Add a company",
    "company_hq": "Add a country, region or city",
    "keywords": "Add a keyword",
}
_STATIC = {
    "locations": LOCATION_SUGGESTIONS, "company_hq": LOCATION_SUGGESTIONS,
    "job_titles": TITLE_SUGGESTIONS, "industries": INDUSTRY_SUGGESTIONS,
}
# Facets whose values are places. What is typed there is READ, never pasted:
# "Global except india" + Enter is a − India chip, "ger" is Germany, and text
# no gazetteer can place makes no chip — it would go to Exa word for word and
# match nobody's location.
_PLACE_FACETS = frozenset({"locations", "company_hq"})
_MAX_ROWS = 6
_MAX_LEN = 120           # filters.py keeps a value to this; so does the input
# The width a chip elides against before it has been laid out: the rail's
# content width with its scrollbar showing (cockpit._RAIL_W 320 - 9 - 2 x 16).
_RAIL_CONTENT = 279
_CHIP_X = 16              # the remove button on a chip
_MINUS = 12               # the leading minus on an excluded chip
_TEXT_INSET = 12          # where an input's text starts: 2px border + 10px padding


def _clean(text) -> str:
    """A typed value the way filters.py will keep it: inner spaces collapsed,
    trimmed, capped."""
    return " ".join(str(text or "").split())[:_MAX_LEN].strip()


def static_suggest(facet: str, text: str) -> list:
    """The typeahead before the richer lookups are wired in: the starter lists
    in prospector.filters, prefix matches first, then anything that contains
    the text (casefold). Facets with no list — companies, keywords — offer
    nothing but what was typed."""
    pool = _STATIC.get(facet, ())
    fold = _clean(text).casefold()
    if not fold:
        return list(pool)
    first = [s for s in pool if s.casefold().startswith(fold)]
    then = [s for s in pool if fold in s.casefold() and not s.casefold().startswith(fold)]
    return first + then


def _sheet() -> str:
    """Every rule the panel's parts wear, scoped by object name and set once on
    the panel. Scoped because the app stylesheet makes a QPushButton or a
    QLineEdit 34-36px tall with its own 2px border — a parent's sheet outranks
    the app's, so these win — and because an unscoped rule here would restyle
    whatever the rail hosts beside the panel. Built when the panel is, so the
    accent follows the member's role like every other surface."""
    t = theme
    heading = f"font-family:'{t.FONT_HEADING}';letter-spacing:1px;font-weight:600;"
    # 20px content + 3px padding + 1px border: a 28px target, not the app's 34.
    small = (f"border-radius:{t.R_CHIP}px;padding:3px 6px;min-height:20px;"
             f"font-size:12px;font-weight:600;")
    badge = "border-radius:8px;padding:0px 5px;font-size:11px;font-weight:700;"
    return "".join((
        f"QLabel#fkick{{color:{t.NEUTRAL[600]};{heading}font-size:11px;}}",
        f"QLabel#fgroup{{color:{t.NEUTRAL[500]};{heading}font-size:10px;}}",
        f"QLabel#fcount{{background:{t.ACCENT};color:#ffffff;{badge}}}",
        f"QLabel#ffacetCount{{background:{t.INFO_BG};color:{t.INFO_INK};{badge}}}",
        f"QLabel#fheadText{{color:{t.TEXT};font-size:13px;font-weight:600;}}",
        f"QLabel#fchipText{{font-size:12px;font-weight:600;}}",
        f"QLabel#fsugText{{color:{t.TEXT};font-size:13px;font-weight:400;}}",
        f"QLabel#fhint{{color:{t.NEUTRAL[600]};font-size:12px;font-weight:500;}}",
        # header actions
        f"QPushButton#fclearAll{{background:transparent;border:1px solid transparent;"
        f"{small}color:{t.ACCENT_RAMP[700]};}}",
        f"QPushButton#fclearAll:hover{{background:{t.INFO_BG};color:{t.INFO_INK};}}",
        f"QPushButton#fclearAll:focus{{border-color:{t.ACCENT};}}",
        f"QPushButton#fsave{{background:{t.CARD};border:1px solid {t.NEUTRAL[300]};"
        f"{small}padding:3px 10px;color:{t.NEUTRAL[800]};}}",
        f"QPushButton#fsave:hover{{background:{t.WELL};border-color:{t.NEUTRAL[400]};}}",
        f"QPushButton#fsave:pressed{{background:{t.NEUTRAL[200]};}}",
        f"QPushButton#fsave:focus{{border-color:{t.ACCENT};}}",
        # an include/exclude facet's input and its suggestions
        f"QLineEdit#finput{{padding:4px 10px;min-height:20px;font-size:13px;}}",
        f"QFrame#fsugRow{{background:transparent;border:none;border-radius:{t.R_CHIP}px;}}",
        f"QFrame#fsugRow:hover{{background:{t.WELL};}}",
        f"QPushButton#fsugInc{{background:transparent;border:1px solid transparent;"
        f"{small}color:{t.ACCENT_RAMP[700]};}}",
        f"QPushButton#fsugInc:hover{{background:{t.INFO_BG};color:{t.INFO_INK};}}",
        f"QPushButton#fsugInc:pressed{{background:{t.ACCENT_RAMP[200]};}}",
        f"QPushButton#fsugInc:focus{{border-color:{t.ACCENT};}}",
        f"QPushButton#fsugExc{{background:transparent;border:1px solid transparent;"
        f"{small}color:{t.ERR_INK};}}",
        f"QPushButton#fsugExc:hover{{background:{t.ERR_BG};}}",
        f"QPushButton#fsugExc:pressed{{background:{t.ERR_LINE};}}",
        f"QPushButton#fsugExc:focus{{border-color:{t.ERR_INK};}}",
        f"QCheckBox#fsimilar{{border:none;background:transparent;font-size:13px;"
        f"color:{t.NEUTRAL[800]};}}",
        # bands
        f"QPushButton#fband{{background:{t.WELL};border:1px solid {t.HAIRLINE};"
        f"border-radius:{t.R_CHIP}px;padding:3px 10px;min-height:20px;"
        f"font-size:12px;font-weight:500;color:{t.NEUTRAL[800]};}}",
        f"QPushButton#fband:hover{{border-color:{t.NEUTRAL[300]};}}",
        f"QPushButton#fband:checked{{background:{t.INFO_BG};color:{t.INFO_INK};"
        f"border-color:{t.ACCENT};}}",
        f"QPushButton#fband:focus{{border-color:{t.ACCENT};}}",
        # chips
        f"#fchipInc{{background:{t.INFO_BG};border:1px solid {t.INFO_BG};"
        f"border-radius:{t.R_CHIP}px;}}",
        f"#fchipInc:hover{{border-color:{t.ACCENT_RAMP[300]};}}",
        f"#fchipInc:focus{{border-color:{t.INFO_INK};}}",
        f"#fchipExc{{background:{t.ERR_BG};border:1px solid {t.ERR_BG};"
        f"border-radius:{t.R_CHIP}px;}}",
        f"#fchipExc:hover{{border-color:{t.ERR_LINE};}}",
        f"#fchipExc:focus{{border-color:{t.ERR_INK};}}",
        f"QToolButton#fchipX{{background:transparent;border:none;padding:0px;"
        f"margin:0px;border-radius:{t.R_MICRO}px;}}",
        f"#fchipInc QToolButton#fchipX:hover{{background:{t.tint(t.INFO_INK, '29')};}}",
        f"#fchipExc QToolButton#fchipX:hover{{background:{t.tint(t.ERR_INK, '29')};}}",
    ))


def _through(*widgets) -> None:
    """Let the mouse fall through to the button a part sits inside."""
    for widget in widgets:
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)


def _count_badge(name: str, parent) -> QLabel:
    badge = QLabel("0", parent)
    badge.setObjectName(name)
    badge.setAlignment(Qt.AlignCenter)
    badge.setFixedHeight(16)
    badge.setMinimumWidth(16)
    badge.hide()
    return badge


class _Elided(QLabel):
    """One line that elides to the width it is given instead of asking for its
    whole length — a sixty-character job title must not widen a 320px rail.

    Painted, and never handed to setText: i18n routes every QLabel.setText
    through the catalogue, and a value someone typed is content, not copy.
    Copy shown through this is translated by the caller."""

    def __init__(self, name: str, ink: str = theme.TEXT, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._full = ""
        self._ink = ink
        self._cap = 0                   # the widest it may ask to be; 0 = none

    def full(self) -> str:
        return self._full

    def set_full(self, text: str, ink: str = "") -> None:
        text = text or ""
        if text != self._full:
            self._full = text
            self.setAccessibleName(text)
            self.updateGeometry()
        self._ink = ink or self._ink
        self.update()

    def set_cap(self, px: int) -> None:
        if px != self._cap:
            self._cap = px
            self.updateGeometry()

    def natural(self) -> int:
        self.ensurePolished()
        return self.fontMetrics().horizontalAdvance(self._full) + 2

    def elides(self) -> bool:
        return bool(self._cap) and self.natural() > self._cap

    def sizeHint(self) -> QSize:
        width = self.natural()
        if self._cap:
            width = min(width, self._cap)
        return QSize(width, self.fontMetrics().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(min(self.sizeHint().width(), 24), self.fontMetrics().height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(theme.c(self._ink))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self._full, Qt.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)


class _Pressable(QAbstractButton):
    """A button laid out like a row — label, badge, chevron — instead of
    painting its own text, so a facet header or a chip is one focusable thing
    with `clicked`, Space and click() for free. What sits inside lets the
    mouse through (`_through`). Tab-focus only: a mouse click must not leave a
    focus ring on a header it just opened."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def sizeHint(self) -> QSize:
        lay = self.layout()
        return lay.sizeHint() if lay is not None else QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        lay = self.layout()
        return lay.minimumSize() if lay is not None else QSize(0, 0)

    def paintEvent(self, _event):
        # QSS backgrounds and borders reach a custom widget only through
        # PE_Widget; QAbstractButton itself paints nothing.
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
        painter.end()


class _Head(_Pressable):
    """A facet's header: its name, how many values it holds, and a chevron
    that says whether its editor is open."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setAccessibleName(title)
        self.setMinimumHeight(C.MIN_TARGET + 4)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 2, 6)
        row.setSpacing(theme.SPACE_2 - 2)
        self._title = QLabel(title, self)
        self._title.setObjectName("fheadText")
        self.badge = _count_badge("ffacetCount", self)
        self._chevron = QLabel(self)
        self._chevron.setFixedSize(14, 14)
        row.addWidget(self._title, 0, Qt.AlignVCenter)
        row.addWidget(self.badge, 0, Qt.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self._chevron, 0, Qt.AlignVCenter)
        _through(self._title, self.badge, self._chevron)
        self._open = False
        self._hover = False
        self._paint_chevron()

    def set_open(self, open_: bool) -> None:
        self._open = bool(open_)
        self._paint_chevron()

    def set_count(self, n: int) -> None:
        self.badge.setText(str(n))
        self.badge.setVisible(n > 0)

    def _paint_chevron(self):
        ink = theme.NEUTRAL[800] if self._hover else theme.NEUTRAL[500]
        name = "chevron-down" if self._open else "chevron-right"
        self._chevron.setPixmap(icons.pixmap(name, 14, ink))

    def enterEvent(self, event):
        self._hover = True
        self._paint_chevron()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._paint_chevron()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(theme.c(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1),
                                    theme.R_CHIP, theme.R_CHIP)


class _Chip(_Pressable):
    """One chosen value. The side reads without colour too: an excluded chip
    leads with a minus. A click on the body flips the side (when the facet has
    two), the x — or Delete — removes it."""

    removeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.value = ""
        self.side = ""
        self.flippable = True
        self._width = _RAIL_CONTENT
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 4, 4)
        row.setSpacing(theme.SPACE_1)
        self._minus = QLabel(self)
        self._minus.setFixedSize(_MINUS, _MINUS)
        self._minus.hide()
        self._text = _Elided("fchipText", theme.INFO_INK, self)
        self._x = QToolButton(self)
        self._x.setObjectName("fchipX")
        self._x.setFixedSize(_CHIP_X, _CHIP_X)
        self._x.setCursor(Qt.PointingHandCursor)
        self._x.setFocusPolicy(Qt.NoFocus)          # Delete on the chip does it
        self._x.setToolTip(i18n.t("Remove"))
        self._x.setAccessibleName(i18n.t("Remove"))
        self._x.clicked.connect(lambda _=False: self.removeRequested.emit())
        row.addWidget(self._minus, 0, Qt.AlignVCenter)
        row.addWidget(self._text, 1, Qt.AlignVCenter)
        row.addWidget(self._x, 0, Qt.AlignVCenter)
        _through(self._minus, self._text)

    def label(self) -> str:
        """What the chip shows (an option's label for seniority, function and
        the bands; the value itself otherwise)."""
        return self._text.full()

    def set_state(self, value: str, text: str, side: str, flippable: bool = True):
        self.value, self.flippable = value, flippable
        exclude = side == "exclude"
        ink = theme.ERR_INK if exclude else theme.INFO_INK
        if side != self.side:
            self.side = side
            self.setObjectName("fchipExc" if exclude else "fchipInc")
            # The sheet keys on the object name, and a renamed widget keeps its
            # old look until re-polished — so does the x, whose hover tint
            # hangs off the chip's name.
            for widget in (self, self._x):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            icons.button_icon(self._x, "x", 10, ink, stroke=2.0)
            if exclude:
                self._minus.setPixmap(icons.pixmap("minus", _MINUS, ink, stroke=2.2))
            self._minus.setVisible(exclude)
        self._text.set_full(text, ink)
        self.setCursor(Qt.PointingHandCursor if flippable else Qt.ArrowCursor)
        self.set_max_width(self._width)
        self.update()

    def set_max_width(self, width: int) -> None:
        """Elide the value so the whole chip fits `width` — the chip row's."""
        self._width = max(60, int(width))
        lay = self.layout()
        margins = lay.contentsMargins()
        chrome = margins.left() + margins.right() + _CHIP_X + lay.spacing()
        if self.side == "exclude":
            chrome += _MINUS + lay.spacing()
        self._text.set_cap(max(24, self._width - chrome))
        self._sync_tip()

    def _sync_tip(self):
        if not self.flippable:
            tip = ""
        elif self.side == "exclude":
            tip = i18n.t("Excluded — click to include")
        else:
            tip = i18n.t("Included — click to exclude")
        if self._text.elides():
            tip = f"{self._text.full()}\n{tip}".strip()
        self.setToolTip(tip)

    def minimumSizeHint(self) -> QSize:
        # Small on purpose: FlowLayout's minimum width is its widest item's
        # minimum, and that minimum becomes the rail's.
        hint = self.sizeHint()
        return QSize(min(hint.width(), 64), hint.height())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.removeRequested.emit()
            return
        super().keyPressEvent(event)


class _ChipBox(QWidget):
    """A facet's chosen values, wrapping onto new lines as they run out of
    width. Chips are pooled and restyled in place, never rebuilt: a chip's own
    x is mid-click when the redraw that hides it runs, and deleting a widget
    from inside its own signal is a crash."""

    def __init__(self, on_flip, on_remove, parent=None):
        super().__init__(parent)
        self._flow = C.FlowLayout(self, margin=0, h_space=6, v_space=6)
        self._flow.setContentsMargins(0, 0, 0, theme.SPACE_2 + 2)
        self._on_flip, self._on_remove = on_flip, on_remove
        self.chips: list = []

    def active(self) -> list:
        return [chip for chip in self.chips if not chip.isHidden()]

    def set_items(self, items) -> None:
        """items: (value, label, side, flippable), in the order to show."""
        width = self.width() if self.isVisible() else _RAIL_CONTENT
        while len(self.chips) < len(items):
            chip = _Chip(self)
            chip.clicked.connect(lambda _=False, c=chip: self._on_flip(c))
            chip.removeRequested.connect(lambda c=chip: self._on_remove(c))
            self._flow.addWidget(chip)
            self.chips.append(chip)
        for chip, (value, label, side, flippable) in zip(self.chips, items):
            chip.set_state(value, label, side, flippable)
            chip.set_max_width(width)
            chip.show()
        for chip in self.chips[len(items):]:
            chip.value = ""
            chip.hide()
        self._flow.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for chip in self.chips:
            chip.set_max_width(self.width())


class _Input(QLineEdit):
    """A facet's input. Escape empties it, the way every typeahead does."""

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.text():
            self.clear()
            return
        super().keyPressEvent(event)


class _Row(QFrame):
    """One suggestion under a facet's input: the value, then Include and
    Exclude. A click on the row itself includes, the way a typeahead picks."""

    includeRequested = Signal()
    excludeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fsugRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.value = ""
        self.label = ""
        row = QHBoxLayout(self)
        # 12px: the input's own text inset (2px border + 10px padding), so a
        # suggestion lines up under what was typed.
        row.setContentsMargins(_TEXT_INSET, 0, 0, 0)
        row.setSpacing(2)
        self._text = _Elided("fsugText", theme.TEXT, self)
        row.addWidget(self._text, 1, Qt.AlignVCenter)
        self.include_btn = QPushButton(i18n.t("Include"), self)
        self.include_btn.setObjectName("fsugInc")
        self.exclude_btn = QPushButton(i18n.t("Exclude"), self)
        self.exclude_btn.setObjectName("fsugExc")
        for btn, signal in ((self.include_btn, self.includeRequested),
                            (self.exclude_btn, self.excludeRequested)):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            btn.clicked.connect(lambda _=False, s=signal: s.emit())
            row.addWidget(btn, 0, Qt.AlignVCenter)

    def set_value(self, value: str, label: str) -> None:
        self.value, self.label = value, label
        self._text.set_full(label)
        self.setToolTip(label)
        self.include_btn.setAccessibleName(i18n.t("Include {value}").format(value=label))
        self.exclude_btn.setAccessibleName(i18n.t("Exclude {value}").format(value=label))

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.includeRequested.emit()
            return
        super().mouseReleaseEvent(event)


class _ChipEditor(QWidget):
    """The editor under an include/exclude facet: an input, up to six
    suggestions under it, and whatever the facet adds below (the similar-
    titles box, the guides-only note)."""

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.values: list = []          # what each shown row would add, in order
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, theme.SPACE_3)
        self._col.setSpacing(theme.SPACE_1 + 2)
        self.input = _Input(self)
        self.input.setObjectName("finput")
        self.input.setPlaceholderText(placeholder)
        self.input.setAccessibleName(placeholder)
        self.input.setMaxLength(_MAX_LEN)
        self._col.addWidget(self.input)
        self._rows_box = QWidget(self)
        rows = QVBoxLayout(self._rows_box)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self.rows: list = []
        for _ in range(_MAX_ROWS):
            row = _Row(self._rows_box)
            row.hide()
            rows.addWidget(row)
            self.rows.append(row)
        self._rows_box.hide()
        self._col.addWidget(self._rows_box)
        self.hint = QLabel(self)
        self.hint.setObjectName("fhint")
        # Wraps: a place hint repeats what was typed ("Press Enter for: United
        # Arab Emirates, Saudi Arabia … except India"), and an unwrapped label
        # would widen the rail past its 320px.
        self.hint.setWordWrap(True)
        self.hint.setContentsMargins(_TEXT_INSET, 0, 0, 0)      # under the rows' text
        self.hint.hide()
        self._col.addWidget(self.hint)

    def add_extra(self, widget: QWidget) -> None:
        self._col.addWidget(widget)

    def show_rows(self, rows, hint: str = "") -> None:
        """rows: (value, label) pairs, at most six. Rows are pooled for the
        same reason chips are — the Include pressed is inside the redraw."""
        self.values = [value for value, _label in rows]
        for row, (value, label) in zip(self.rows, rows):
            row.set_value(value, label)
            row.show()
        for row in self.rows[len(rows):]:
            row.value = row.label = ""
            row.hide()
        self._rows_box.setVisible(bool(rows))
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


class _BandEditor(QWidget):
    """A band facet's editor: every band as a small toggle, wrapping, and a
    note under them when the facet has one."""

    def __init__(self, options, on_click, note: str = "", parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, theme.SPACE_3)
        col.setSpacing(theme.SPACE_1 + 2)
        # The bands sit in a box of their own: a FlowLayout lays a wrapping
        # note out as one more item at its whole sentence's width.
        bands = QWidget(self)
        flow = C.FlowLayout(bands, margin=0, h_space=6, v_space=6)
        self.buttons: dict = {}
        for key, label in options:
            btn = QPushButton(i18n.t(label), bands)
            btn.setObjectName("fband")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            btn.clicked.connect(lambda on=False, k=key: on_click(k, on))
            flow.addWidget(btn)
            self.buttons[key] = btn
        col.addWidget(bands)
        self.note = None
        if note:
            self.note = C.label(note, level="META", wrap=True)
            col.addWidget(self.note)

    def set_chosen(self, keys) -> None:
        for key, btn in self.buttons.items():
            btn.setChecked(key in keys)


class _Section(QWidget):
    """One facet: header, its chips (always visible, Sales-Nav style), and the
    editor that opening the header reveals, over a hairline."""

    def __init__(self, facet: str, title: str, editor: QWidget, open_: bool,
                 on_flip, on_remove, parent=None):
        super().__init__(parent)
        self.facet = facet
        self._band = facet in BAND_FACETS
        self._open = False
        self._has_chips = False
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.head = _Head(title, self)
        self.head.clicked.connect(lambda _=False: self._toggle())
        col.addWidget(self.head)
        self.chips = _ChipBox(lambda chip: on_flip(facet, chip),
                              lambda chip: on_remove(facet, chip), self)
        self.chips.hide()
        col.addWidget(self.chips)
        self.editor = editor
        col.addWidget(editor)
        col.addWidget(C.hairline())
        self.set_open(open_)

    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool) -> None:
        self._open = bool(open_)
        self.editor.setVisible(self._open)
        self.head.set_open(self._open)
        self._sync_chips()

    def set_chips(self, items) -> None:
        self.chips.set_items(items)
        self._has_chips = bool(items)
        self._sync_chips()

    def _toggle(self):
        self.set_open(not self._open)
        field = getattr(self.editor, "input", None)
        if self._open and field is not None and self.isVisible():
            field.setFocus(Qt.OtherFocusReason)

    def _sync_chips(self):
        # An open band's checked buttons ARE its chosen values; chips above
        # them would say the same thing twice.
        self.chips.setVisible(self._has_chips and not (self._band and self._open))


class _Switch(C.ToggleSwitch):
    """The shared switch, with an off track that shows on a white rail.

    C.ToggleSwitch paints its off track white at 18% because it was drawn for
    the dark nav rail; on the white filter rail that track — and the white
    knob on it — is simply not there. The knob also sits where the state says
    whenever no animation is running, so a spec applied in code never leaves
    an "on" switch drawn off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.TabFocus)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        on = self.isChecked()
        radius = self.H / 2
        painter.setPen(QPen(theme.c(theme.ACCENT_RAMP[800]), 1.5) if self.hasFocus()
                       else Qt.NoPen)
        painter.setBrush(theme.c(theme.ACCENT if on else theme.NEUTRAL[300]))
        painter.drawRoundedRect(QRectF(0.75, 0.75, self.W - 1.5, self.H - 1.5),
                                radius, radius)
        moving = self._anim.state() == QAbstractAnimation.State.Running
        knob = self.get_knob() if moving else float(self.W - self.KNOB - 2 if on else 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c("#ffffff"))
        inset = (self.H - self.KNOB) / 2
        painter.drawEllipse(QRectF(knob, inset, self.KNOB, self.KNOB))


class _ToggleRow(_Pressable):
    """A switch with its sentence. The row answers a click as well as the
    switch does — a 32px switch alone is a small thing to hit."""

    def __init__(self, text: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)             # the switch is the tab stop
        self.setMinimumHeight(C.MIN_TARGET + 4)
        self.setToolTip(tooltip)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 2, 6)
        row.setSpacing(theme.SPACE_2)
        self.text = _Elided("fheadText", theme.TEXT, self)
        self.text.set_full(text)
        self.switch = _Switch(self)
        self.switch.setAccessibleName(text)
        row.addWidget(self.text, 1, Qt.AlignVCenter)
        row.addWidget(self.switch, 0, Qt.AlignVCenter)
        _through(self.text)
        self.clicked.connect(lambda _=False: self.switch.click())


class FilterPanel(QWidget):
    """The "Lead filters" column. Edits one SearchSpec (module docstring).

        panel = FilterPanel(suggest=lookup)     # lookup(facet, text) -> [str]
        panel.changed.connect(on_filters)       # once per edit
        panel.set_spec(SearchSpec.from_params(session_params))
        panel.spec().to_dict()

    `suggest` feeds the typeahead of the open facets (locations, job_titles,
    industries, companies, company_hq, keywords). Seniority and Function offer
    their own fixed options and never ask it."""

    changed = Signal()
    saveRequested = Signal()

    def __init__(self, suggest=None, parent=None):
        super().__init__(parent)
        self._spec = SearchSpec()
        self._suggest = suggest or static_suggest
        self._sections: dict = {}
        self.setStyleSheet(_sheet())
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(self._build_header())
        for group, names in _GROUPS:
            root.addSpacing(theme.SPACE_4)
            kick = QLabel(i18n.t(group).upper(), self)
            kick.setObjectName("fgroup")
            root.addWidget(kick)
            root.addSpacing(2)
            for name in names:
                if name == "changed_jobs_90d":
                    root.addWidget(self._build_jobs())
                else:
                    root.addWidget(self._build_section(name))
        self._render()

    # ── the public surface ────────────────────────────────────────────────────
    def spec(self) -> SearchSpec:
        """The filters as set — a copy; editing it changes nothing here."""
        return self._spec.copy()

    def set_spec(self, spec) -> None:
        """Show a SearchSpec (or its dict), read through SearchSpec.from_dict so
        a hand-edited or older file is forgiven. Clears anything half-typed;
        leaves which facets are open alone. Emits `changed` once."""
        raw = spec.to_dict() if isinstance(spec, SearchSpec) else spec
        self._spec = SearchSpec.from_dict(raw if isinstance(raw, dict) else {})
        for section in self._sections.values():
            field = getattr(section.editor, "input", None)
            if field is not None:
                field.blockSignals(True)
                field.clear()
                field.blockSignals(False)
        self._render()
        self.changed.emit()

    def clear(self) -> None:
        """"Clear all": every facet emptied, the switches back to default."""
        self.set_spec(SearchSpec())

    def active_count(self) -> int:
        return self._spec.active_count()

    def set_suggest(self, suggest) -> None:
        """Swap the typeahead lookup (None: the static starter lists)."""
        self._suggest = suggest or static_suggest
        for name in self._sections:
            self._refresh_rows(name)

    # ── building ──────────────────────────────────────────────────────────────
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2 - 2)
        kick = QLabel(i18n.t("Lead filters").upper(), self)
        kick.setObjectName("fkick")
        row.addWidget(kick, 0, Qt.AlignVCenter)
        self._badge = _count_badge("fcount", self)
        row.addWidget(self._badge, 0, Qt.AlignVCenter)
        row.addStretch(1)
        self._clear_btn = QPushButton(i18n.t("Clear all"), self)
        self._clear_btn.setObjectName("fclearAll")
        self._clear_btn.clicked.connect(lambda _=False: self.clear())
        self._save_btn = QPushButton(i18n.t("Save search"), self)
        self._save_btn.setObjectName("fsave")
        self._save_btn.setToolTip(i18n.t("Keep these filters to run again later"))
        self._save_btn.clicked.connect(lambda _=False: self.saveRequested.emit())
        for btn in (self._clear_btn, self._save_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            row.addWidget(btn, 0, Qt.AlignVCenter)
        return row

    def _build_section(self, name: str) -> _Section:
        if name in BAND_FACETS:
            note = (i18n.t("Checked against the company's record · unknown sizes "
                           "aren't dropped") if name in _ON_RECORD else "")
            editor = _BandEditor(_BANDS[name],
                                 lambda key, on, n=name: self._band(n, key, on),
                                 note, self)
        else:
            editor = _ChipEditor(i18n.t(_PLACEHOLDERS[name]), self)
            editor.input.textChanged.connect(lambda _t, n=name: self._refresh_rows(n))
            editor.input.returnPressed.connect(lambda n=name: self._enter(n))
            for row in editor.rows:
                row.includeRequested.connect(
                    lambda n=name, r=row: self._pick(n, r, "include"))
                row.excludeRequested.connect(
                    lambda n=name, r=row: self._pick(n, r, "exclude"))
            if name == "job_titles":
                self._similar = QCheckBox(i18n.t("Include similar titles"), editor)
                self._similar.setObjectName("fsimilar")
                self._similar.setToolTip(i18n.t(
                    "On: titles guide the search. Off: a person's title must "
                    "contain one of them."))
                self._similar.clicked.connect(
                    lambda on=False: self._set_flag("similar_titles", on))
                editor.add_extra(self._similar)
            if name in GUIDES_ONLY:
                # A person row carries no industry and no keywords, so an
                # include can only steer Exa; an exclude is checked (filters.py).
                editor.add_extra(C.label(
                    i18n.t("Include guides the search · Exclude is enforced"),
                    level="META", wrap=True))
        section = _Section(name, i18n.t(FACET_LABELS[name]), editor,
                           name in _OPEN_AT_START, self._flip, self._remove, self)
        self._sections[name] = section
        return section

    def _build_jobs(self) -> QWidget:
        box = QWidget(self)
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._jobs = _ToggleRow(
            i18n.t("Changed jobs in the last 90 days"),
            i18n.t("Only people whose current role started in the last 90 days"), box)
        self._jobs.switch.clicked.connect(
            lambda on=False: self._set_flag("changed_jobs_90d", on))
        col.addWidget(self._jobs)
        col.addWidget(C.hairline())
        return box

    # ── edits: change the spec, redraw from it, say so once ──────────────────
    def _edit(self, change) -> None:
        before = self._spec.to_dict()
        draft = self._spec.copy()
        change(draft)
        # Through from_dict, so the panel keeps exactly what a file would:
        # trimmed, de-duplicated, capped, never on both sides.
        after = SearchSpec.from_dict(draft.to_dict())
        edited = after.to_dict() != before
        if edited:
            self._spec = after
        self._render()                  # a refused edit still redraws the truth
        if edited:
            self.changed.emit()

    def _set_flag(self, attr: str, on) -> None:
        self._edit(lambda spec: setattr(spec, attr, bool(on)))

    def _add(self, name: str, value: str, side: str) -> None:
        self._add_many(name, [(value, side)])

    def _add_many(self, name: str, pairs) -> None:
        """(value, side) pairs onto one facet as ONE edit — "Global except
        india" is a single change, not two."""
        pairs = [(_clean(v), side) for v, side in pairs if _clean(v)]
        if not pairs:
            return
        self._clear_input(name)         # the redraw below refreshes the rows once

        def change(spec):
            facet = spec.facet(name)
            for value, side in pairs:
                fold = value.casefold()
                target = facet.exclude if side == "exclude" else facet.include
                if any(v.casefold() == fold for v in target):
                    continue
                facet.include = [v for v in facet.include if v.casefold() != fold]
                facet.exclude = [v for v in facet.exclude if v.casefold() != fold]
                (facet.exclude if side == "exclude" else facet.include).append(value)
        self._edit(change)

    def _clear_input(self, name: str) -> None:
        field = self._sections[name].editor.input
        field.blockSignals(True)
        field.clear()
        field.blockSignals(False)

    def _pick(self, name: str, row: _Row, side: str) -> None:
        if row.value:
            self._add(name, row.value, side)

    def _enter(self, name: str) -> None:
        editor = self._sections[name].editor
        typed = _clean(editor.input.text())
        if not typed:
            return
        if name in _PLACE_FACETS:
            self._enter_place(name, typed)
            return
        if not editor.values:
            return
        if name not in CLOSED_FACETS:
            facet = self._spec.facet(name)
            if typed.casefold() in {v.casefold() for v in facet.include + facet.exclude}:
                return      # already chosen: never quietly add the next suggestion
        self._add(name, editor.values[0], "include")

    def _enter_place(self, name: str, typed: str) -> None:
        """Enter in Location / Company HQ: the text is read as places. A known
        place is included; "Global except india" adds its chips on both sides;
        a half-typed name ("ger") takes the first suggestion; "Anywhere" clears
        the box (no filter IS anywhere); anything else unplaceable stays typed
        under its hint and adds nothing."""
        include, exclude, unknown = read_place_text(typed)
        facet = self._spec.facet(name)
        chosen = {v.casefold() for v in facet.include + facet.exclude}
        if unknown:
            words, out = parse_location_text(typed)
            editor = self._sections[name].editor
            if len(words) == 1 and not out and not include and editor.values:
                self._add(name, editor.values[0], "include")
            return
        if not include and not exclude:
            self._clear_input(name)
            self._refresh_rows(name)
            return
        if len(include) == 1 and not exclude:
            if include[0].casefold() in chosen:
                return      # already chosen: never quietly flip it or add another
        self._add_many(name, [(v, "include") for v in include]
                       + [(v, "exclude") for v in exclude])

    def _flip(self, name: str, chip: _Chip) -> None:
        if not chip.flippable or not chip.value:
            return
        value = chip.value

        def change(spec):
            facet = spec.facet(name)
            if value in facet.include:
                facet.include.remove(value)
                facet.exclude.append(value)
            elif value in facet.exclude:
                facet.exclude.remove(value)
                facet.include.append(value)
        self._edit(change)

    def _remove(self, name: str, chip: _Chip) -> None:
        value = chip.value
        if not value:
            return

        def change(spec):
            if name in BAND_FACETS:
                setattr(spec, name, [k for k in getattr(spec, name) if k != value])
            else:
                facet = spec.facet(name)
                facet.include = [v for v in facet.include if v != value]
                facet.exclude = [v for v in facet.exclude if v != value]
        self._edit(change)

    def _band(self, name: str, key: str, on) -> None:
        def change(spec):
            chosen = set(getattr(spec, name))
            if on:
                chosen.add(key)
            else:
                chosen.discard(key)
            setattr(spec, name, [k for k, _label in _BANDS[name] if k in chosen])
        self._edit(change)

    # ── drawing the spec ──────────────────────────────────────────────────────
    def _render(self) -> None:
        spec = self._spec
        for name, section in self._sections.items():
            if name in BAND_FACETS:
                chosen = getattr(spec, name)
                section.set_chips([(k, i18n.t(label_of(_BANDS[name], k)), "include", False)
                                   for k in chosen])
                section.editor.set_chosen(chosen)
            else:
                facet = spec.facet(name)
                options = CLOSED_FACETS.get(name)

                def shown(value, options=options):
                    return i18n.t(label_of(options, value)) if options else value
                section.set_chips([(v, shown(v), "include", True) for v in facet.include]
                                  + [(v, shown(v), "exclude", True) for v in facet.exclude])
                self._refresh_rows(name)
            section.head.set_count(spec.count(name))
        self._similar.setChecked(spec.similar_titles)
        self._jobs.switch.setChecked(spec.changed_jobs_90d)
        total = spec.active_count()
        self._badge.setText(str(total))
        self._badge.setVisible(total > 0)
        self._clear_btn.setVisible(total > 0)

    def _refresh_rows(self, name: str) -> None:
        section = self._sections.get(name)
        if section is None or name in BAND_FACETS:
            return
        rows, hint = self._suggestions(name, section.editor.input.text())
        section.editor.show_rows(rows, hint)

    def _suggestions(self, name: str, text: str):
        """(rows, hint) for a facet's input. Rows are (value, label). A value
        already chosen, on either side and in any case, is never offered."""
        typed = _clean(text)
        fold = typed.casefold()
        facet = self._spec.facet(name)
        chosen = {v.casefold() for v in facet.include + facet.exclude}
        options = CLOSED_FACETS.get(name)
        if options:
            left = [(key, i18n.t(label)) for key, label in options
                    if key.casefold() not in chosen]
            if not fold:
                more = len(left) > _MAX_ROWS
                return left[:_MAX_ROWS], (i18n.t("Type to filter") if more else "")
            first = [o for o in left if o[1].casefold().startswith(fold)]
            then = [o for o in left if fold in o[1].casefold() and o not in first]
            found = (first + then)[:_MAX_ROWS]
            return found, ("" if found else i18n.t("No match"))
        if not fold:
            return [], ""
        try:
            offered = [_clean(s) for s in (self._suggest(name, typed) or [])
                       if isinstance(s, str)]
        except Exception:                                   # noqa: BLE001
            offered = []                # a failing lookup must not stop typing
        offered = [s for s in offered if s]
        if name in _PLACE_FACETS:
            return self._place_rows(typed, offered, chosen)
        rows, seen = [], set(chosen)
        if fold not in seen:
            # The typed text leads — in the list's spelling when it names a
            # listed value ("india" offers "India").
            spelled = next((s for s in offered if s.casefold() == fold), typed)
            rows.append((spelled, spelled))
            seen.add(fold)
        for value in offered:
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            rows.append((value, value))
            if len(rows) >= _MAX_ROWS:
                break
        return rows, ""

    def _place_rows(self, typed: str, offered: list, chosen: set):
        """(rows, hint) for a place facet. The typed text leads only when it IS
        a known place, in the gazetteer's spelling ("bombay" offers Mumbai);
        otherwise the suggestions stand alone and the hint says what Enter
        will do — or that nothing here is a place."""
        include, exclude, unknown = read_place_text(typed)
        rows, seen = [], set(chosen)
        single = len(include) == 1 and not exclude and not unknown
        if single and include[0].casefold() not in seen:
            rows.append((include[0], include[0]))
            seen.add(include[0].casefold())
        for value in offered:
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            rows.append((value, value))
            if len(rows) >= _MAX_ROWS:
                break
        words, out = parse_location_text(typed)
        one_word = len(words) == 1 and not out and not include
        if unknown and not (one_word and rows):
            hint = i18n.t("Not a place Prism knows") + ": " + (
                typed if one_word else ", ".join(unknown))
        elif exclude or len(include) > 1:
            said = SearchSpec.from_dict({"locations": {"include": include,
                                                       "exclude": exclude}})
            hint = i18n.t("Press Enter for") + ": " + said.location_label(limit=3)
        elif not include and not unknown and not rows:
            hint = i18n.t("Anywhere is the default: no filter needed")
        else:
            hint = ""
        return rows, hint
