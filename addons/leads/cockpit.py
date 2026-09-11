"""
Leads & Outreach — the workspace (the "A" direction)
────────────────────────────────────────────────────
`LeadsWorkspace` is the whole surface: a tab strip over six screens —

    Leads · Sessions · Lists · Saved searches · Sequences · Analytics

• Leads is the dense cockpit (`LeadsCockpit`): a multi-select lead TABLE with a
  left rail (the workbench mounts its lead filters there, above the refine
  controls), a Net-new / avg-fit counter strip, a bulk-actions bar that rises
  once a row is ticked, and an on-demand right DRAWER carrying the dossier plus
  a stop-on-reply sequence preview. Rail, results and a docked drawer share a
  splitter the user drags; columns resize. Scan-dense list; depth one click away.
• Sessions is real — every finished run (addons/leads/sessions.py), reopenable.
• Lists is real — the CSV/xlsx sheets Prism has already written to
  ~/Documents/Prism Leads, as open-able cards.
• Saved searches is real — the filters the owner kept to run again
  (addons/leads/saved_searches.py), each a card with its last run, "Use
  search" and "Delete".
• Analytics is real — this run's funnel, deliverability and verdict mix drawn
  from the dossiers in hand, plus the count of addresses already reached (the
  suppression ledger) and the outreach guardrails.
• Sequences is an honest, designed shell: it shows the exact model it will
  hold, and says plainly that the scheduler lands next.

The cockpit is pure presentation + selection: it takes the qualified dossiers
the pipeline produced and emits a signal when the user asks to verify, export,
save or sequence the checked rows, open a session, or use or delete a saved
search. The workbench wires those to the real workers and stores, so the whole
surface is testable with no pipeline and no network — Analytics off the
dossiers passed in, Lists, Sessions and Saved searches off folders the test
controls.
"""
from __future__ import annotations

import datetime
import os

import paths
import theme
from widgets import controls as C
from widgets import icons
from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter,
    QPainterPath, QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QSplitterHandle, QStackedWidget, QStyle, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

_COLS = ("", "Lead", "Focus", "Fit", "Status", "Signal")
# The deliverability statuses a lead can carry, each with its (ink, tint) tone.
_TONE = {
    "Verified":  (theme.OK_INK,   theme.OK_BG),
    "Guessed":   (theme.WARN_INK, theme.WARN_BG),
    "Catch-all": (theme.WARN_INK, theme.WARN_BG),
    "Unknown":   (theme.WARN_INK, theme.WARN_BG),
    "Invalid":   (theme.ERR_INK,  theme.ERR_BG),
    "No email":  (theme.WARN_INK, theme.WARN_BG),
    "Mailed":    (theme.NEUTRAL[700], theme.NEUTRAL[200]),
    "Not qualified": (theme.NEUTRAL[700], theme.NEUTRAL[200]),
}
# Dossier.status of a display-only row: someone a search sourced whom the
# qualify pass never reached (a leads-sheet-only run, or past the Qualify count).
UNQUALIFIED = "not_qualified"
# Rows "Qualify & draft" can (re)run: never qualified, or a qualify pass that
# failed — no Groq key, a Groq error, a reply that wasn't JSON (models.py).
RETRYABLE = frozenset({UNQUALIFIED, "no_model", "qualify_error", "non_json"})
_MONO = theme.FONT_MONO_STACK.split(",")[0].strip().strip('"')


def status_of(dos, draft=None) -> str:
    """The deliverability label for a dossier — the one thing a bulk sender
    must see per row. A lead already sent to reads 'Mailed'; otherwise the free
    verify verdict (or 'Guessed' for an un-checked pattern address)."""
    if draft is not None and getattr(draft, "status", "") == "sent":
        return "Mailed"
    lead = dos.lead
    if not (lead.email or "").strip():
        return "No email"
    ec = (lead.extra or {}).get("email_check") or ""
    return {"valid": "Verified", "invalid": "Invalid",
            "catch-all": "Catch-all", "unknown": "Unknown"}.get(ec, "Guessed")


def unqualified_rows(dossiers, all_leads) -> list:
    """Everyone a run sourced whom the qualify pass didn't reach, as display-only
    rows. The table used to list qualified dossiers alone, so a leads-sheet-only
    run — 100 people sourced, none qualified — opened to an empty screen, and a
    full run hid everyone past the Qualify count. Apollo lists every person a
    search found, and so does this.

    The rows live only here: never saved into a session, exported as dossiers
    or counted by Analytics. A qualified lead keeps its real dossier — matched
    by object, since a run's dossiers and its all_leads share Lead objects (a
    restored session rebuilds them that way too)."""
    from prospector.models import Dossier
    have = {id(d.lead) for d in dossiers or []}
    return [Dossier(lead=lead, verdict="", generated_at="", status=UNQUALIFIED,
                    score=int(getattr(lead, "fit_score", 0) or 0))
            for lead in all_leads or [] if id(lead) not in have]


class _FitItem(QTableWidgetItem):
    """Sorts by the numeric fit score, not the string — so 100 beats 88. The
    score is painted as a chip by _FitDelegate, which reads _FIT_ROLE."""
    def __init__(self, value: float):
        super().__init__(f"{value:g}")
        self._v = float(value)
        self.setData(_FIT_ROLE, self._v)

    def __lt__(self, other):
        return self._v < getattr(other, "_v", 0.0)


class _LeadCard(QFrame):
    """One lead as a card in the gallery view — clickable (opens the drawer),
    with an accent-lit hover. Carries its dossier index so a click and a tick
    both name the same lead."""

    clicked = Signal(int)

    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self._idx = idx
        self.setObjectName("leadcard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#leadcard{{background:{theme.CARD};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CARD}px;}}"
            f"QFrame#leadcard:hover{{border-color:{theme.ACCENT};}}")

    def mousePressEvent(self, event):
        self.clicked.emit(self._idx)
        super().mousePressEvent(event)


# ── faces and painted cells ─────────────────────────────────────────────────
_AVATAR_INKS = (theme.ACCENT_RAMP[600], theme.OK, theme.WARN,
                theme.ACCENT_RAMP[800], theme.NEUTRAL[600], theme.ACCENT_RAMP[500])
_RAIL_W = 320          # the rail's default width; 300 cut every job title
_RAIL_MIN = 260        # a drag on the rail's edge stays between these
_RAIL_MAX = 520
_DRAWER_W = 360        # the dossier drawer: its default width, and its width floating
_DRAWER_MIN = 320
_DRAWER_MAX = 600
_DOCK_MIN = 1180       # floor for docking; _dock_room also measures the centre
_TABLE_MIN = 560       # a docked drawer never leaves the results less than this
_HANDLE_W = 6          # a splitter handle's grab area — it draws a 1px rule
_SHADOW = 12           # the soft edge a floating drawer paints over the table
_ROW_H = 52
_HEAD_H = 36
_PAD = 12              # a cell's edge to its text; the header labels share it
_BOX = 16              # the painted checkbox
_STEP = 20             # one scroll step, in px — the table scrolls per pixel
_SLIDE_MS = 160        # the bulk bar's slide
_DRAWER_MS = 180       # the drawer's
_QMAX = 16777215       # QWIDGETSIZE_MAX: "no maximum"
_COMPANY_ROLE = Qt.UserRole + 1     # Lead cell: the company under the name
_WHERE_ROLE = Qt.UserRole + 1       # Focus cell: the location under the title
_FIT_ROLE = Qt.UserRole + 2         # Fit cell: the score as a number
_C_TICK, _C_LEAD, _C_FOCUS, _C_FIT, _C_STATUS, _C_SIGNAL = range(len(_COLS))
# Default widths, and the least a drag may leave. Focus has neither: it takes
# whatever the others leave, and _fit_columns keeps that at _FOCUS_MIN or more.
_COL_WIDTH = {_C_TICK: 44, _C_LEAD: 300, _C_FIT: 76, _C_STATUS: 124, _C_SIGNAL: 136}
_COL_MIN = {_C_LEAD: 180, _C_FIT: 60, _C_STATUS: 100, _C_SIGNAL: 112}
_FOCUS_MIN = 150
# Pills that name a state rather than a finding, drawn as a quiet outline.
_OUTLINE = frozenset({"Not qualified"})
_EMPTY_TITLE = "No leads yet"
_EMPTY_BODY = ("Set lead filters in the panel on the left, or import a sheet, then "
               "press Prepare outreach. Lists you saved live under Lists.")


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace(".", " ").split() if p[:1].isalpha()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def _avatar_ink(name: str) -> str:
    return _AVATAR_INKS[sum(map(ord, name or "?")) % len(_AVATAR_INKS)]


def _avatar(name: str, size: int = 32) -> QLabel:
    lab = QLabel(_initials(name))
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(
        f"QLabel{{color:#ffffff;background:{_avatar_ink(name)};"
        f"border-radius:{size // 2}px;font-weight:700;font-size:{max(11, size // 3)}px;}}")
    return lab


def _motion_ok(widget: QWidget) -> bool:
    """Whether a slide may play: only where someone can watch it — on screen,
    on a real display. These slides animate a height or a width, never a
    QGraphicsEffect, so they carry none of the blank-paint risk that
    controls.effects_enabled() guards against, and they run by default (the
    owner asked for a smoother screen; PRISM_NO_MOTION=1 turns them off).
    Anywhere else — a test, the offscreen renderer, a tab that isn't showing —
    the change lands at its end state at once. Every slide below sets that
    same end state when it finishes, so skipping one never changes where
    things end up."""
    if os.environ.get("PRISM_NO_MOTION") or not widget.isVisible():
        return False
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return app is not None and app.platformName() != "offscreen"


def _asset(name: str) -> str:
    """A shipped asset as a stylesheet url() path (forward slashes on Windows)."""
    return paths.resource("assets", name).replace(os.sep, "/")


def _font(px: int, weight=QFont.Normal, family: str = "") -> QFont:
    f = QFont(family or theme.FONT_BODY)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _ticked(value) -> bool:
    """A CheckStateRole value read as ticked. PySide hands back an int or a
    Qt.CheckState depending on who set it, and the two don't compare equal."""
    try:
        return int(getattr(value, "value", value)) == Qt.Checked.value
    except (TypeError, ValueError):
        return False


def _mix(base: str, ink: str, amount: float) -> QColor:
    """`base` moved `amount` of the way towards `ink` — an opaque tint, so a
    row ground never lets the hairline beneath it show through."""
    a, b = QColor(base), QColor(ink)
    return QColor(round(a.red() + (b.red() - a.red()) * amount),
                  round(a.green() + (b.green() - a.green()) * amount),
                  round(a.blue() + (b.blue() - a.blue()) * amount))


def _paint_check(painter: QPainter, rect, state, hot: bool = False) -> None:
    """The table's own checkbox, for the rows and the header alike: a rounded
    16px box, white with a grey edge unticked, accent-filled with a white mark
    when ticked (a bar when only some are). Painted rather than left to the
    platform: under the native Windows style an unticked item-view indicator
    drew nothing at all, so nobody could see the rows were selectable."""
    area = QRectF(rect)
    box = QRectF(area.center().x() - _BOX / 2, area.center().y() - _BOX / 2, _BOX, _BOX)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    if state in (Qt.Checked, Qt.PartiallyChecked):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT_RAMP[600] if hot else theme.ACCENT))
        painter.drawRoundedRect(box, 4, 4)
        pen = QPen(QColor("#ffffff"), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if state == Qt.PartiallyChecked:
            y = box.center().y()
            painter.drawLine(QPointF(box.left() + 4.5, y), QPointF(box.right() - 4.5, y))
        else:
            mark = QPainterPath()
            mark.moveTo(box.left() + 4.2, box.top() + 8.3)
            mark.lineTo(box.left() + 6.9, box.top() + 11.0)
            mark.lineTo(box.left() + 11.9, box.top() + 5.4)
            painter.drawPath(mark)
    else:
        painter.setPen(QPen(QColor(theme.ACCENT if hot else theme.NEUTRAL[400]), 1.2))
        painter.setBrush(QColor(theme.CARD))
        painter.drawRoundedRect(box.adjusted(0.6, 0.6, -0.6, -0.6), 4, 4)
    painter.restore()


def _paint_row(painter: QPainter, option, index) -> None:
    """A row's ground, painted by every cell so the row reads as one: white; a
    faint accent once ticked; a stronger one with an accent edge on the row
    open in the drawer; a shade darker under the mouse. The hairline under it
    is the only rule — the grid is off."""
    view = option.widget
    rect = option.rect
    row = index.row()
    is_open = bool(option.state & QStyle.State_Selected)
    ticked = _ticked(index.sibling(row, _C_TICK).data(Qt.CheckStateRole))
    hover = getattr(view, "hover_row", -1) == row
    if is_open or ticked:
        ground = _mix(theme.CARD, theme.ACCENT,
                      (0.10 if is_open else 0.06) + (0.03 if hover else 0.0))
    else:
        ground = QColor(theme.NEUTRAL[100] if hover else theme.CARD)
    painter.fillRect(rect, ground)
    painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1),
                     QColor(theme.HAIRLINE))
    if is_open and index.column() == _C_TICK:
        painter.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()),
                         QColor(theme.ACCENT))


def _two_lines(painter: QPainter, x: int, rect: QRect, first: str, second: str,
               font1: QFont, ink1: str, font2: QFont, ink2: str) -> None:
    """One or two lines centred as a block in the row. The line boxes are the
    Lead cell's (a 14px name over a 12px company) whatever the fonts, so the
    Lead and Focus cells' second lines sit on the same baseline."""
    width = max(0, rect.right() - _PAD - x)
    h1 = QFontMetrics(_font(14, QFont.DemiBold)).height()
    h2 = QFontMetrics(_font(12)).height()
    top = rect.top() + (rect.height() - h1 - (h2 + 1 if second else 0)) // 2
    painter.setFont(font1)
    painter.setPen(QColor(ink1))
    painter.drawText(QRect(x, top, width, h1), Qt.AlignLeft | Qt.AlignVCenter,
                     QFontMetrics(font1).elidedText(first, Qt.ElideRight, width))
    if second:
        painter.setFont(font2)
        painter.setPen(QColor(ink2))
        painter.drawText(QRect(x, top + h1 + 1, width, h2), Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(font2).elidedText(second, Qt.ElideRight, width))


class _CellDelegate(QStyledItemDelegate):
    """Base for every column: the row's ground first, then `cell`. The view's
    own item painting is skipped on purpose — under the native Windows style
    it added a dotted focus rectangle, and the tick column's indicator was
    invisible until ticked."""

    def paint(self, painter, option, index):
        painter.save()
        _paint_row(painter, option, index)
        self.cell(painter, QRect(option.rect), index, option)
        painter.restore()

    def cell(self, painter, rect, index, option):
        """Draw the cell's content inside `rect`."""


class _TickDelegate(_CellDelegate):
    """The tick column: the painted checkbox, edged in the accent under the
    mouse. The item's CheckStateRole stays the one source of truth."""

    def cell(self, painter, rect, index, option):
        view = option.widget
        hot = (getattr(view, "hover_row", -1) == index.row()
               and getattr(view, "hover_col", -1) == _C_TICK)
        state = Qt.Checked if _ticked(index.data(Qt.CheckStateRole)) else Qt.Unchecked
        _paint_check(painter, rect, state, hot)


class _LeadDelegate(_CellDelegate):
    """The 'Lead' column: an initials avatar, the name, and the company beneath."""

    def cell(self, painter, rect, index, option):
        name = index.data(Qt.DisplayRole) or ""
        company = index.data(_COMPANY_ROLE) or ""
        d = 32
        x = rect.left() + theme.SPACE_2
        ay = rect.top() + (rect.height() - d) // 2
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(_avatar_ink(name)))
        painter.drawEllipse(QRectF(x, ay, d, d))
        painter.setFont(_font(11, QFont.Bold))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRect(x, ay, d, d), Qt.AlignCenter, _initials(name))
        _two_lines(painter, x + d + theme.SPACE_3, rect, name, company,
                   _font(14, QFont.DemiBold), theme.TEXT, _font(12), theme.NEUTRAL[600])


class _FocusDelegate(_CellDelegate):
    """The 'Focus' column: the title, and beneath it where they are — the owner
    filters by location, so a row says it without opening the drawer."""

    def cell(self, painter, rect, index, option):
        _two_lines(painter, rect.left() + _PAD, rect, index.data(Qt.DisplayRole) or "",
                   index.data(_WHERE_ROLE) or "", _font(13), theme.NEUTRAL[800],
                   _font(12), theme.NEUTRAL[600])


def _fit_tone(fit: float) -> tuple:
    """(ink, tint) for a fit score — the bands the gallery badge uses."""
    if fit >= 75:
        return theme.OK_INK, theme.OK_BG
    if fit >= 50:
        return theme.WARN_INK, theme.WARN_BG
    return theme.NEUTRAL[700], theme.NEUTRAL[100]


class _FitDelegate(_CellDelegate):
    """The 'Fit' column: the score as a compact tinted chip, right-aligned. The
    band's tone says good or weak; a big bold number shouted it on every row."""

    def cell(self, painter, rect, index, option):
        fit, text = index.data(_FIT_ROLE), index.data(Qt.DisplayRole) or ""
        if fit is None or not text:
            return
        ink, bg = _fit_tone(float(fit))
        f = _font(12, QFont.DemiBold, _MONO)
        w, h = max(36, QFontMetrics(f).horizontalAdvance(text) + 16), 22
        x = rect.right() + 1 - _PAD - w
        y = rect.top() + (rect.height() - h) // 2
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(x, y, w, h), theme.R_CHIP, theme.R_CHIP)
        painter.setFont(f)
        painter.setPen(QColor(ink))
        painter.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)


class _PillDelegate(_CellDelegate):
    """Status / Signal columns: the value as a tinted pill — the card tones.
    "Not qualified" is a state rather than a finding, so it takes a quiet
    outline instead of a fill. Every pill is 22px, centred on the row."""

    def cell(self, painter, rect, index, option):
        text = index.data(Qt.DisplayRole) or ""
        if not text:
            return
        f = _font(11, QFont.DemiBold)
        fm = QFontMetrics(f)
        h = 22
        w = min(fm.horizontalAdvance(text) + 20, max(0, rect.width() - 2 * _PAD))
        x = rect.left() + _PAD
        y = rect.top() + (rect.height() - h) // 2
        box = QRectF(x, y, w, h)
        painter.setRenderHint(QPainter.Antialiasing)
        if text in _OUTLINE:
            ink = theme.NEUTRAL[600]
            painter.setPen(QPen(QColor(theme.NEUTRAL[300]), 1))
            painter.setBrush(Qt.NoBrush)
            box = box.adjusted(0.5, 0.5, -0.5, -0.5)
        else:
            ink, bg = _TONE.get(text, (theme.INFO_INK, theme.INFO_BG))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(bg))
        painter.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        painter.setFont(f)
        painter.setPen(QColor(ink))
        painter.drawText(QRect(x, y, w, h), Qt.AlignCenter,
                         fm.elidedText(text, Qt.ElideRight, max(0, w - 12)))


class _LeadHeader(QHeaderView):
    """The table's header, painted whole: 11px uppercase labels lined up with
    the cell content, a hairline beneath, a quiet rule on each edge you can
    drag (accent while hovered), and a select-all checkbox over the tick
    column. Painted rather than styled so no platform style can float a sort
    arrow or a grid line into it."""

    toggleAll = Signal()

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._state = Qt.Unchecked
        self._hot_edge = -1                 # the column whose right edge is under the mouse
        self._hot_box = False               # the mouse is on the select-all box
        self.setSectionsClickable(False)    # the Sort combo is the one sort control
        self.setHighlightSections(False)
        self.setSortIndicatorShown(False)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFixedHeight(_HEAD_H)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def check_state(self):
        return self._state

    def set_check_state(self, state) -> None:
        if state != self._state:
            self._state = state
            self.viewport().update()

    def _edge_at(self, x: int) -> int:
        """The resizable column whose right edge — its drag grip — is under x."""
        for col in range(self.count()):
            if (self.isSectionHidden(col)
                    or self.sectionResizeMode(col) != QHeaderView.Interactive):
                continue
            if abs(x - self.sectionViewportPosition(col) - self.sectionSize(col)) <= 4:
                return col
        return -1

    def paintSection(self, painter, rect, logical):
        painter.save()
        painter.fillRect(rect, QColor(theme.CARD))
        painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1),
                         QColor(theme.HAIRLINE))
        if logical == _C_TICK:
            _paint_check(painter, rect, self._state, self._hot_box)
        else:
            label = str(self.model().headerData(logical, Qt.Horizontal, Qt.DisplayRole) or "")
            f = _font(11, QFont.DemiBold, theme.FONT_HEADING)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
            painter.setFont(f)
            painter.setPen(QColor(theme.NEUTRAL[600]))
            inset = theme.SPACE_2 if logical == _C_LEAD else _PAD     # over the avatar
            align = Qt.AlignRight if logical == _C_FIT else Qt.AlignLeft
            painter.drawText(rect.adjusted(inset, 0, -_PAD, 0), align | Qt.AlignVCenter,
                             label.upper())
        # A faint rule between the labelled columns keeps their rhythm even; the
        # one under the mouse lights up only where a drag would resize (the
        # cursor tells the same truth).
        if logical not in (_C_TICK, self.logicalIndex(self.count() - 1)):
            hot = logical == self._hot_edge
            painter.fillRect(QRect(rect.right() - (1 if hot else 0), rect.top() + 10,
                                   2 if hot else 1, rect.height() - 20),
                             QColor(theme.ACCENT if hot else theme.NEUTRAL[200]))
        painter.restore()

    def _hover(self, edge: int, box: bool) -> None:
        if (edge, box) != (self._hot_edge, self._hot_box):
            self._hot_edge, self._hot_box = edge, box
            self.viewport().update()

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if event.buttons():
            self._hover(self._hot_edge, False)          # mid-drag: keep the grip lit
        else:
            edge = self._edge_at(x)
            self._hover(edge, edge < 0 and self.logicalIndexAt(x) == _C_TICK)
        super().mouseMoveEvent(event)

    def _on_box(self, event) -> bool:
        x = event.position().toPoint().x()
        return (event.button() == Qt.LeftButton and self._edge_at(x) < 0
                and self.logicalIndexAt(x) == _C_TICK)

    def mousePressEvent(self, event):
        if self._on_box(event):
            self.toggleAll.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # The second press of a double click is a click too, as on any checkbox.
        if self._on_box(event):
            self.toggleAll.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._hover(-1, False)
        return super().viewportEvent(event)


class _LeadTable(QTableWidget):
    """The lead table, with what a list you work through needs: a click
    anywhere in the tick column ticks that row without opening the drawer,
    Space ticks the current row, Esc asks for the drawer to close, and the
    cell under the mouse is tracked so the delegates can light its row."""

    tickRequested = Signal(int)             # a row
    escapePressed = Signal()

    def __init__(self, rows: int, columns: int, parent=None):
        super().__init__(rows, columns, parent)
        self.hover_row = -1
        self.hover_col = -1
        self._ticking = False               # a press in the tick column owns this click
        self.viewport().setMouseTracking(True)
        # Rows slide under a still mouse while scrolling: re-read what's under it.
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._hover_at_cursor())

    def _hover(self, row: int, col: int) -> None:
        if (row, col) == (self.hover_row, self.hover_col):
            return
        rows = {self.hover_row, row}
        self.hover_row, self.hover_col = row, col
        vp = self.viewport()
        for r in rows:
            if r >= 0:
                vp.update(QRect(0, self.rowViewportPosition(r), vp.width(), self.rowHeight(r)))

    def _hover_at_cursor(self) -> None:
        if not self.viewport().underMouse():
            self._hover(-1, -1)
            return
        p = self.viewport().mapFromGlobal(QCursor.pos())
        row = self.rowAt(p.y())
        self._hover(row, self.columnAt(p.x()) if row >= 0 else -1)

    def _cell_at(self, event) -> tuple:
        p = event.position().toPoint()
        return self.rowAt(p.y()), self.columnAt(p.x())

    def mouseMoveEvent(self, event):
        row, col = self._cell_at(event)
        self._hover(row, col if row >= 0 else -1)
        if self._ticking:
            return                          # no drag-select out of a tick
        super().mouseMoveEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._hover(-1, -1)
        return super().viewportEvent(event)

    def _tick_press(self, event) -> bool:
        row, col = self._cell_at(event)
        if event.button() != Qt.LeftButton or row < 0 or col != _C_TICK:
            return False
        self._ticking = True
        self.setFocus(Qt.MouseFocusReason)
        self.tickRequested.emit(row)
        event.accept()
        return True

    def mousePressEvent(self, event):
        if not self._tick_press(event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # The second press of a double click ticks again, as on any checkbox.
        if not self._tick_press(event):
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self._ticking:
            self._ticking = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentRow() >= 0:
            self.tickRequested.emit(self.currentRow())
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _SplitHandle(QSplitterHandle):
    """A handle you can find without seeing a fat bar: a 6px grab area that
    draws one 1px rule, lit in the accent while hovered or dragged."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hot = False
        self._held = False
        self.setCursor(Qt.SplitHCursor if orientation == Qt.Horizontal else Qt.SplitVCursor)

    def _light(self, on: bool) -> None:
        if on != self._hot:
            self._hot = on
            self.update()

    def enterEvent(self, event):
        self._light(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._light(self._held)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._held = True
        self._light(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._held = False
        self._light(self.underMouse())
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.CARD))
        mid = self.width() // 2
        if self._hot:
            p.fillRect(QRect(mid - 1, 0, 2, self.height()), QColor(theme.ACCENT))
        else:
            p.fillRect(QRect(mid, 0, 1, self.height()), QColor(theme.HAIRLINE))


class _Splitter(QSplitter):
    def createHandle(self):
        return _SplitHandle(self.orientation(), self)


class _Reveal(QWidget):
    """A box that shows as much of one widget as its own size allows, keeping
    the widget at full size inside it. Animating the box's height (the bulk
    bar) or width (the drawer) then slides the content in whole, instead of
    squashing its layout for a few frames. At rest `extent` is 0 and the
    content simply fills the box. A horizontal box can also paint a soft
    shadow down its left edge, for a drawer floating over the table."""

    def __init__(self, child: QWidget, orientation=Qt.Vertical, parent=None):
        super().__init__(parent)
        self._child = child
        self._vertical = orientation == Qt.Vertical
        self._shadow = 0
        self.extent = 0                     # the content's length while a slide runs
        child.setParent(self)
        if self._vertical:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def shadow(self) -> int:
        return self._shadow

    def set_shadow(self, px: int) -> None:
        """A painted gradient, not a QGraphicsEffect — see controls.shadows_enabled
        for why this app never trusts those to render."""
        self._shadow = max(0, int(px))
        self._fit()
        self.update()

    def paintEvent(self, event):
        if self._shadow and not self._vertical:
            p = QPainter(self)
            fade = QLinearGradient(0, 0, self._shadow, 0)
            fade.setColorAt(0.0, theme.c(theme.SHADOW_INK, 0.0))
            fade.setColorAt(1.0, theme.c(theme.SHADOW_INK, 0.10))
            p.fillRect(QRect(0, 0, self._shadow, self.height()), fade)
        super().paintEvent(event)

    def sizeHint(self) -> QSize:
        return self._child.sizeHint()

    def minimumSizeHint(self) -> QSize:
        # Claims no width: what it holds sheds its own extras when narrow
        # (_fit_bulk), and a claimed minimum pushed the bar past the results.
        m = self._child.minimumSizeHint()
        return QSize(0, 0) if self._vertical else QSize(0, m.height())

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self.updateGeometry()           # the content's hint moved: tell our parent
            self._fit()
        return super().event(event)

    def resizeEvent(self, event):
        self._fit()
        super().resizeEvent(event)

    def _fit(self) -> None:
        if self._vertical:
            self._child.setGeometry(0, 0, self.width(), max(self.height(), self.extent))
        else:
            s = self._shadow
            self._child.setGeometry(s, 0, max(self.width() - s, self.extent), self.height())


class LeadsCockpit(QWidget):
    """The dense results surface. `set_dossiers` fills it; the five *Requested
    signals carry the checked dossiers out to the dialog's workers."""

    verifyRequested = Signal(list)
    exportRequested = Signal(list)
    saveListRequested = Signal(list)
    sequenceRequested = Signal(list)
    qualifyRequested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dossiers: list = []
        self._draft_by: dict = {}
        self._checked: set = set()          # dossier indices ticked (shared view)
        self._hidden: set = set()           # dossier indices hidden by the filters
        self._card_cbs: dict = {}           # idx → the gallery card's checkbox
        self._view = "table"                # "table" (dense) or "cards" (gallery)
        self._rail_pref = _RAIL_W           # the rail's width, to come back to after a fold
        self._drawer_pref = _DRAWER_W       # the docked drawer's width, as last dragged
        self._col_pref = dict(_COL_WIDTH)   # column widths as the user last left them
        self._fitting = False               # _fit_columns is resizing, not the user
        self._drawer_docked = False         # the drawer is in the splitter (else floats)
        self._drawer_t = 0.0                # 0 shut … 1 open: what its geometry shows now
        self._drawer_opening = False        # where the drawer's slide is headed
        self._bulk_open = False             # where the bulk bar is headed
        self._drawer_anim = QVariantAnimation(self)
        self._drawer_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._drawer_anim.valueChanged.connect(self._drawer_step)
        self._drawer_anim.finished.connect(self._drawer_landed)
        self._placing = False               # _move_drawer is mid-move: don't re-enter
        # Resizes place the drawer on the next turn of the event loop, never
        # inside the resize: docking resizes the results, and placing again
        # from within that left their layout finishing with a stale width.
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.setInterval(0)
        self._place_timer.timeout.connect(self._place_drawer)
        self._build()

    # ── construction ──────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # rail | results | drawer, in a splitter the user can drag. The drawer is
        # in the splitter only while there's room to dock it; on a narrow window
        # it floats over the results instead — see _place_drawer.
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._split = _Splitter(Qt.Horizontal)
        self._split.setHandleWidth(_HANDLE_W)
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._filter_rail())
        self._center_w = self._center()
        self._split.addWidget(self._center_w)
        # A wider window widens the results; the rail and drawer keep their width.
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([_RAIL_W, 4 * _RAIL_W])
        self._split.splitterMoved.connect(self._on_split_moved)
        body.addWidget(self._split)
        self._drawer()
        self._body.installEventFilter(self)
        root.addWidget(self._body, 1)
        self._update_counters()
        self._show_empty(True)
        self._refresh_bulk()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Resize and obj in (getattr(self, "_body", None),
                                             getattr(self, "_view_stack", None)):
            # The body resizing moves the dock threshold; the results column
            # resizing (the bulk bar sliding) moves a floating drawer's foot.
            self._place_timer.start()
        elif kind in (QEvent.Resize, QEvent.Show) and obj is getattr(self, "_table_vp", None):
            self._fit_columns()
        # Show as well as Resize: off screen the toolbar and the bulk bar keep
        # everything (a tab away, or the bar hidden between ticks), and coming
        # back at the same width sends no Resize — so without Show they stayed
        # unfolded and Qt crushed their labels to stubs.
        elif kind in (QEvent.Resize, QEvent.Show) and obj is getattr(self, "_toolbar", None):
            self._fit_toolbar()
        elif kind in (QEvent.Resize, QEvent.Show) and obj is getattr(self, "_bulk_bar_w", None):
            self._fit_bulk()
        return super().eventFilter(obj, event)

    def _filter_rail(self) -> QWidget:
        """The left rail, Sales-Nav style: a slot for the search that BUILDS the
        list (the workbench mounts it), then the filters that REFINE it. The rail
        scrolls on its own, so a short window never crushes a control; its edge
        drags between _RAIL_MIN and _RAIL_MAX."""
        self._rail = QScrollArea()
        self._rail.setObjectName("leadsRail")
        self._rail.setMinimumWidth(_RAIL_MIN)
        self._rail.setMaximumWidth(_RAIL_MAX)
        self._rail.setWidgetResizable(True)
        self._rail.setFrameShape(QFrame.NoFrame)
        self._rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rail.verticalScrollBar().setSingleStep(_STEP)
        # No border-right: the splitter handle beside it draws the rule.
        self._rail.setStyleSheet(
            f"QScrollArea#leadsRail{{background:{theme.CARD};border:none;}}")
        inner = QWidget()
        inner.setObjectName("leadsRailInner")
        inner.setAttribute(Qt.WA_StyledBackground, True)
        inner.setStyleSheet(f"QWidget#leadsRailInner{{background:{theme.CARD};}}")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        lay.setSpacing(theme.SPACE_3)

        self._search_slot = QVBoxLayout()
        self._search_slot.setContentsMargins(0, 0, 0, 0)
        self._search_slot.setSpacing(0)
        lay.addLayout(self._search_slot)

        lay.addWidget(self._rail_head("Refine results"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name, company, title")
        self._search.setClearButtonEnabled(True)
        self._search.addAction(icons.icon("search", 15, theme.NEUTRAL[500]),
                               QLineEdit.LeadingPosition)
        # Debounced: in Cards view every filter pass rebuilds the gallery, so
        # typing a name would otherwise rebuild it once per keystroke.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_filters)
        self._search.textChanged.connect(lambda _t: self._search_timer.start())
        lay.addWidget(self._search)

        fit_row = QHBoxLayout()
        fit_row.setContentsMargins(0, 0, 0, 0)
        fit_row.setSpacing(theme.SPACE_2)
        fit_label = _muted("Minimum fit", 13)
        fit_label.setWordWrap(False)        # at the rail's narrowest it broke in two
        fit_row.addWidget(fit_label, 1)
        self._fit_min = QSpinBox()
        self._fit_min.setRange(0, 100)
        self._fit_min.setSuffix(" / 100")
        self._fit_min.setMinimumWidth(112)
        self._fit_min.valueChanged.connect(self._apply_filters)
        fit_row.addWidget(self._fit_min)
        lay.addLayout(fit_row)

        # A run lists everyone it sourced; this narrows it to the leads Prism
        # has researched and drafted for.
        self._only_qualified = QCheckBox("Qualified leads only")
        self._only_qualified.setStyleSheet("QCheckBox{border:none;background:transparent;}")
        self._only_qualified.stateChanged.connect(self._apply_filters)
        lay.addWidget(self._only_qualified)

        lay.addWidget(_muted("Deliverability", 13))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        self._status_boxes: dict = {}
        for i, name in enumerate(("Verified", "Guessed", "Catch-all", "Unknown",
                                  "Invalid", "No email", "Mailed")):
            cb = QCheckBox(name)
            cb.setChecked(True)
            # Under the app stylesheet a QCheckBox is drawn inside a 2px accent
            # box; the indicator already says checked, so the box is noise.
            cb.setStyleSheet("QCheckBox{border:none;background:transparent;}")
            cb.stateChanged.connect(self._apply_filters)
            self._status_boxes[name] = cb
            grid.addWidget(cb, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        lay.addWidget(_muted("Manual, 1:1 — Prism drafts and paces the touches; you "
                             "send from your own inbox. No auto-DMs.", 11))
        self._rail.setWidget(inner)
        return self._rail

    def _rail_head(self, text: str) -> QLabel:
        lab = QLabel(text.upper())
        lab.setStyleSheet(
            f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
            f"font-size:11px;letter-spacing:1px;font-weight:600;")
        return lab

    def set_search_panel(self, widget: QWidget) -> None:
        """Mount the list-building search (owned by the workbench) at the top of
        the rail, above the refine filters, with a rule between the two."""
        _clear(self._search_slot)
        self._search_slot.addWidget(widget)
        self._search_slot.addSpacing(theme.SPACE_4)
        rule = QFrame()
        rule.setObjectName("railRule")
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame#railRule{{background:{theme.HAIRLINE};border:none;}}")
        self._search_slot.addWidget(rule)
        self._search_slot.addSpacing(theme.SPACE_2)

    def _stat(self, label: str, accent: bool = False) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(5)
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:12px;")
        num = QLabel("0")
        num.setStyleSheet(f"color:{theme.ACCENT if accent else theme.TEXT};"
                          f"font-family:'{_MONO}';font-size:13px;font-weight:600;")
        h.addWidget(lab)
        h.addWidget(num)
        w._num = num
        return w

    def _center(self) -> QWidget:
        wrap = QWidget()
        # On a narrow window the rail gives way (down to its minimum) before
        # the results do.
        wrap.setMinimumWidth(_TABLE_MIN)
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._toolbar = QFrame()
        self._toolbar.setObjectName("resultsBar")
        self._toolbar.setAttribute(Qt.WA_StyledBackground, True)
        self._toolbar.setStyleSheet(
            f"QFrame#resultsBar{{background:{theme.CARD};border:none;"
            f"border-bottom:1px solid {theme.HAIRLINE};}}")
        tlay = QHBoxLayout(self._toolbar)
        tlay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        tlay.setSpacing(theme.SPACE_4)
        # Beside the rail it folds, the way Apollo places it.
        tlay.addWidget(self._filters_toggle())
        self._count_lbl = QLabel("Showing 0 of 0")
        self._count_lbl.setStyleSheet(f"color:{theme.TEXT};font-size:13px;font-weight:600;")
        tlay.addWidget(self._count_lbl)
        self._c_new = self._stat("Net-new", accent=True)
        self._c_fit = self._stat("Avg fit")
        tlay.addWidget(self._c_new)
        tlay.addWidget(self._c_fit)
        tlay.addStretch(1)
        self._seg = self._view_toggle()
        tlay.addWidget(self._seg)
        sort = QHBoxLayout()
        sort.setContentsMargins(0, 0, 0, 0)
        sort.setSpacing(theme.SPACE_2)
        self._sort_lbl = QLabel("Sort")
        self._sort_lbl.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:12px;")
        sort.addWidget(self._sort_lbl)
        self._sort = QComboBox()
        self._sort.setObjectName("leadsSort")
        self._sort.addItems(["Best fit", "Name A–Z"])
        self._sort.setMinimumWidth(124)
        self._sort.setCursor(Qt.PointingHandCursor)
        # One height with the toggle and the view switch (32px), and a caret:
        # the app sheet's combo is 36px with no arrow, so it read as a text box.
        self._sort.setStyleSheet(
            f"QComboBox#leadsSort{{background:{theme.CARD};color:{theme.TEXT};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 10px;min-height:20px;font-size:13px;}}"
            f"QComboBox#leadsSort:hover{{border-color:{theme.NEUTRAL[300]};}}"
            f"QComboBox#leadsSort::drop-down{{border:none;width:22px;}}"
            f"QComboBox#leadsSort::down-arrow{{image:url({_asset('caret-down.svg')});"
            f"width:12px;height:12px;}}")
        self._sort.currentIndexChanged.connect(self._on_sort_changed)
        sort.addWidget(self._sort)
        tlay.addLayout(sort)
        self._toolbar.installEventFilter(self)          # narrow → _fit_toolbar
        col.addWidget(self._toolbar)

        self._table = self._build_table()

        # Nothing loaded yet → a centred empty state, not an empty grid.
        self._empty = C.EmptyState("user", _EMPTY_TITLE, _EMPTY_BODY)

        # Two ways to read the same filtered leads: the dense table (scan power)
        # and a card gallery (the visual, Pinterest-style view). One selection
        # model feeds both, so ticking a card and ticking a row are the same act.
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._table)             # 0 — table
        self._view_stack.addWidget(self._build_gallery())   # 1 — cards
        self._view_stack.addWidget(self._empty)             # 2 — nothing loaded
        self._view_stack.installEventFilter(self)
        col.addWidget(self._view_stack, 1)

        self._bulk = self._bulk_bar()
        col.addWidget(self._bulk)
        return wrap

    def _build_table(self) -> QTableWidget:
        t = _LeadTable(0, len(_COLS))
        t.setObjectName("leadsTable")
        self._head = _LeadHeader(t)
        t.setHorizontalHeader(self._head)
        t.setHorizontalHeaderLabels(list(_COLS))
        t.horizontalHeaderItem(_C_TICK).setToolTip("Select all")
        rows = t.verticalHeader()
        rows.setVisible(False)
        rows.setSectionResizeMode(QHeaderView.Fixed)
        rows.setDefaultSectionSize(_ROW_H)
        t.setShowGrid(False)
        t.setAlternatingRowColors(False)
        t.setWordWrap(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Per pixel, in 20px steps: per item, one wheel notch jumped three rows.
        t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.verticalScrollBar().setSingleStep(_STEP)
        t.horizontalScrollBar().setSingleStep(_STEP)
        t.setItemDelegateForColumn(_C_TICK, _TickDelegate(t))
        t.setItemDelegateForColumn(_C_LEAD, _LeadDelegate(t))
        t.setItemDelegateForColumn(_C_FOCUS, _FocusDelegate(t))
        t.setItemDelegateForColumn(_C_FIT, _FitDelegate(t))
        pills = _PillDelegate(t)
        t.setItemDelegateForColumn(_C_STATUS, pills)
        t.setItemDelegateForColumn(_C_SIGNAL, pills)
        head = self._head
        head.setStretchLastSection(False)
        head.setMinimumSectionSize(40)
        # Focus is Fixed rather than Stretch, and _fit_columns hands it the
        # rest of the width: a Stretch column can't be held to a minimum, so a
        # wide Lead squeezed it to a 40px sliver instead of scrolling.
        for c in range(len(_COLS)):
            head.setSectionResizeMode(c, QHeaderView.Interactive if c in _COL_MIN else
                                      QHeaderView.Fixed)
            if c in _COL_WIDTH:
                head.resizeSection(c, _COL_WIDTH[c])
        head.sectionResized.connect(self._on_section_resized)
        head.toggleAll.connect(self._toggle_all_visible)
        t.tickRequested.connect(self._tick_row)
        t.escapePressed.connect(self._dismiss_drawer)
        t.itemChanged.connect(self._on_item_changed)
        t.currentCellChanged.connect(lambda *_: self._show_selected())
        self._table_vp = t.viewport()
        self._table_vp.installEventFilter(self)
        # The app sheet hides every horizontal scrollbar (height 0); this table
        # can overflow sideways once columns are dragged wide, so it gets a thin one.
        t.setStyleSheet(
            f"QTableWidget#leadsTable{{background:{theme.CARD};border:none;"
            f"border-radius:0px;outline:0;}}"
            f"QTableWidget#leadsTable QHeaderView{{background:{theme.CARD};border:none;}}"
            f"QTableWidget#leadsTable QScrollBar:horizontal{{height:9px;"
            f"background:transparent;margin:0px;}}"
            f"QTableWidget#leadsTable QScrollBar::handle:horizontal{{"
            f"background:{theme.NEUTRAL[300]};border-radius:4px;min-width:30px;}}"
            f"QTableWidget#leadsTable QScrollBar::handle:horizontal:hover{{"
            f"background:{theme.NEUTRAL[400]};}}"
            f"QTableWidget#leadsTable QScrollBar::add-line:horizontal,"
            f"QTableWidget#leadsTable QScrollBar::sub-line:horizontal{{width:0px;}}")
        return t

    def _filters_toggle(self) -> QPushButton:
        """Hide filters / Show filters — Apollo's switch: fold the rail away for
        a wider table, and bring it back at the width it had."""
        self._filters_label = "Hide filters"
        b = QPushButton(self._filters_label)
        b.setObjectName("filtersToggle")
        b.setToolTip(self._filters_label)
        b.setCursor(Qt.PointingHandCursor)
        icons.button_icon(b, "sliders", 15, theme.NEUTRAL[700])
        b.setStyleSheet(
            f"QPushButton#filtersToggle{{background:{theme.CARD};color:{theme.NEUTRAL[800]};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 12px 5px 10px;min-height:20px;font-size:12px;font-weight:600;}}"
            f"QPushButton#filtersToggle:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}")
        b.clicked.connect(lambda: self.set_filters_shown(self._rail.isHidden()))
        self._filters_btn = b
        return b

    def set_filters_shown(self, show: bool) -> None:
        """Fold the rail away, or bring it back at the width it had when folded."""
        rail = self._rail
        if show != rail.isHidden():
            return                          # already that way
        if show:
            rail.show()
            self._split_sizes(rail=self._rail_pref)
        else:
            if rail.isVisible() and rail.width() >= _RAIL_MIN:
                self._rail_pref = min(_RAIL_MAX, rail.width())
            rail.hide()
        self._filters_label = "Hide filters" if show else "Show filters"
        self._filters_btn.setToolTip(self._filters_label)
        self._fit_toolbar()                 # puts the new label on, unless icon-only
        self._split.refresh()
        self._place_drawer()

    def _view_toggle(self) -> QWidget:
        seg = QFrame()
        seg.setObjectName("viewSeg")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(
            f"QFrame#viewSeg{{background:{theme.WELL};border:1px solid {theme.HAIRLINE};"
            f"border-radius:{theme.R_CONTROL}px;}}"
            f"QFrame#viewSeg QPushButton{{background:transparent;border:none;"
            f"color:{theme.NEUTRAL[600]};padding:3px 14px;min-height:20px;"
            f"font-size:12px;font-weight:600;border-radius:{theme.R_CHIP}px;}}"
            f"QFrame#viewSeg QPushButton:hover{{color:{theme.TEXT};}}"
            f"QFrame#viewSeg QPushButton:checked{{background:{theme.CARD};"
            f"color:{theme.TEXT};}}")
        lay = QHBoxLayout(seg)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._view_table_btn = QPushButton("Table")
        self._view_cards_btn = QPushButton("Cards")
        for b, v in ((self._view_table_btn, "table"), (self._view_cards_btn, "cards")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, view=v: self._set_view(view))
            lay.addWidget(b)
        self._view_table_btn.setChecked(True)
        return seg

    def _set_view(self, view: str) -> None:
        self._view = view
        self._view_table_btn.setChecked(view == "table")
        self._view_cards_btn.setChecked(view == "cards")
        if not self._dossiers:
            self._show_empty(True)
            return
        self._view_stack.setCurrentIndex(0 if view == "table" else 1)
        if view == "cards":
            self._fill_gallery()

    def _show_empty(self, empty: bool) -> None:
        """Nothing loaded: a centred empty state instead of an empty grid, and no
        toolbar or bulk bar offering to act on nothing."""
        self._toolbar.setVisible(not empty)
        if empty:
            self._land_bulk(False)
            self._view_stack.setCurrentIndex(2)
            self._close_drawer()
        else:
            self._view_stack.setCurrentIndex(0 if self._view == "table" else 1)

    def set_empty_text(self, title: str = "", body: str = "") -> None:
        """What the empty state says. After a leads-only run there ARE leads —
        just none qualified to show here — so the default "No leads yet" would
        tell the user to redo what they just did. Blank restores the default."""
        self._empty.set_text(title or _EMPTY_TITLE, body or _EMPTY_BODY)

    def _build_gallery(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        scroll.verticalScrollBar().setSingleStep(_STEP)
        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        hl.setSpacing(0)
        self._grid = C.CardGrid(min_col_width=228)
        hl.addWidget(self._grid)
        hl.addStretch(1)
        scroll.setWidget(host)
        self._gallery = scroll
        return scroll

    def _link(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("bulkLink")
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _bulk_bar(self) -> QWidget:
        """The bulk actions. Hidden until a row is ticked, then it rises from
        the foot of the results with the count, "Select all N" while only some
        are ticked, "Clear", and the actions."""
        bar = QFrame()
        bar.setObjectName("bulkBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#bulkBar{{background:{theme.CARD};border:none;"
            f"border-top:1px solid {theme.DIVIDER};}}"
            f"QFrame#bulkBar QLabel{{color:{theme.TEXT};font-size:13px;font-weight:600;"
            f"background:transparent;border:none;}}"
            f"QFrame#bulkBar QPushButton{{color:{theme.NEUTRAL[800]};background:{theme.CARD};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 14px;min-height:20px;font-family:'{theme.FONT_BODY}';"
            f"font-size:12px;font-weight:600;}}"
            f"QFrame#bulkBar QPushButton:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}"
            f"QFrame#bulkBar QPushButton:disabled{{color:{theme.NEUTRAL[400]};"
            f"border-color:{theme.HAIRLINE};background:{theme.CARD};}}"
            f"QFrame#bulkBar QPushButton#primary{{background:{theme.ACCENT};"
            f"border-color:{theme.ACCENT};color:#fff;}}"
            f"QFrame#bulkBar QPushButton#primary:hover{{background:{theme.ACCENT_RAMP[600]};"
            f"border-color:{theme.ACCENT_RAMP[600]};}}"
            f"QFrame#bulkBar QPushButton#primary:disabled{{background:{theme.NEUTRAL[200]};"
            f"border-color:{theme.NEUTRAL[200]};color:{theme.NEUTRAL[500]};}}"
            f"QFrame#bulkBar QPushButton#bulkLink{{background:transparent;border:none;"
            f"color:{theme.ACCENT};padding:5px 6px;font-size:13px;font-weight:600;}}"
            f"QFrame#bulkBar QPushButton#bulkLink:hover{{color:{theme.ACCENT_RAMP[700]};"
            f"text-decoration:underline;}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 10, theme.SPACE_4, 10)
        lay.setSpacing(theme.SPACE_2)
        self._sel_lbl = QLabel("0 selected")
        lay.addWidget(self._sel_lbl)
        lay.addSpacing(theme.SPACE_2)
        self._sel_all = self._link("Select all")
        self._sel_all.clicked.connect(lambda: self._set_many(self._visible(), True))
        lay.addWidget(self._sel_all)
        self._bulk_clear = self._link("Clear")
        self._bulk_clear.clicked.connect(self._clear_ticks)
        lay.addWidget(self._bulk_clear)
        lay.addStretch(1)
        self._b_verify = QPushButton("Verify free")
        self._b_save = QPushButton("Save to list")
        self._b_export = QPushButton("Export")
        # Runs the qualify pass on the ticked people a run sourced but never
        # qualified. "&&": a lone & in a button label is eaten as a mnemonic.
        self._b_qualify = QPushButton("Qualify && draft")
        self._b_qualify.setToolTip("Research, qualify and draft an email for the "
                                   "selected leads that aren't qualified yet.")
        self._b_seq = QPushButton("Add to sequence")   # Barlow has no →
        self._b_seq.setObjectName("primary")
        self._b_verify.clicked.connect(lambda: self.verifyRequested.emit(self.selected()))
        self._b_save.clicked.connect(lambda: self.saveListRequested.emit(self.selected()))
        self._b_export.clicked.connect(lambda: self.exportRequested.emit(self.selected()))
        self._b_qualify.clicked.connect(lambda: self.qualifyRequested.emit(self.selected()))
        self._b_seq.clicked.connect(lambda: self.sequenceRequested.emit(self.selected()))
        # On a narrow window the less-used actions fold into More (_fit_bulk).
        self._b_more = QPushButton("More")
        self._b_more.setToolTip("More actions for the selected leads")
        self._b_more.clicked.connect(self._show_more)
        self._b_more.hide()
        self._qualify_wanted = False        # the run holds someone Qualify can reach
        self._sel_all_wanted = False        # only some of the visible rows are ticked
        self._bulk_folded: list = []
        for b in (self._b_verify, self._b_save, self._b_export, self._b_qualify,
                  self._b_more, self._b_seq):
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        self._bulk_bar_w = bar
        bar.installEventFilter(self)
        slot = _Reveal(bar, Qt.Vertical)
        slot.setObjectName("bulkSlot")
        self._bulk_anim = QPropertyAnimation(slot, b"maximumHeight", self)
        self._bulk_anim.setDuration(_SLIDE_MS)
        self._bulk_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bulk_anim.finished.connect(lambda: self._land_bulk(self._bulk_open))
        return slot

    def _slide_bulk(self, show: bool) -> None:
        """Bring the bulk bar up when the first row is ticked and take it away
        when the last is cleared: a slide on screen, the end state elsewhere."""
        slot, anim = self._bulk, self._bulk_anim
        running = anim.state() == QAbstractAnimation.Running
        if show == self._bulk_open and (running or slot.isHidden() != show):
            return                          # already there, or on its way
        if not _motion_ok(self):
            self._land_bulk(show)
            return
        self._bulk_open = show
        anim.stop()
        start = 0 if slot.isHidden() else slot.height()
        slot.extent = slot.sizeHint().height()
        slot.setMaximumHeight(start)
        slot.show()
        anim.setStartValue(start)
        anim.setEndValue(slot.extent if show else 0)
        anim.start()

    def _land_bulk(self, show: bool) -> None:
        """The bulk bar's end state, with no slide."""
        self._bulk_anim.stop()
        self._bulk_open = show
        self._bulk.extent = 0
        self._bulk.setMaximumHeight(_QMAX)
        self._bulk.setVisible(show)

    # ── narrow windows: the toolbar and the bulk bar shed extras, not letters ──
    def _toolbar_need(self, level: int) -> int:
        """The width the results toolbar needs at one step of compaction: 0 is
        all of it; 1 drops Avg fit, 2 Net-new, 3 the "Sort" label, and 4 shows
        Hide filters as its icon alone."""
        lay = self._toolbar.layout()
        m = lay.contentsMargins()
        btn = self._filters_btn
        words = btn.fontMetrics().horizontalAdvance(self._filters_label) + theme.SPACE_1
        with_words = btn.sizeHint().width() + (0 if btn.text() else words)
        items = [with_words - (words if level >= 4 else 0), self._count_lbl.sizeHint().width()]
        if level < 2:
            items.append(self._c_new.sizeHint().width())
        if level < 1:
            items.append(self._c_fit.sizeHint().width())
        items.append(self._seg.sizeHint().width())
        sort = max(self._sort.minimumWidth(), self._sort.sizeHint().width())
        if level < 3:
            sort += self._sort_lbl.sizeHint().width() + theme.SPACE_2
        items.append(sort)
        return m.left() + m.right() + sum(items) + lay.spacing() * len(items)

    def _fit_toolbar(self) -> None:
        """Take the toolbar's extras away, least needed first, until what's left
        fits — instead of Qt crushing every label to a stub. Off screen (a
        test) it keeps everything."""
        bar = self._toolbar
        level = 0
        if bar.isVisible():
            while level < 4 and self._toolbar_need(level) > bar.width():
                level += 1
        self._c_fit.setVisible(level < 1)
        self._c_new.setVisible(level < 2)
        self._sort_lbl.setVisible(level < 3)
        text = "" if level >= 4 else self._filters_label
        if self._filters_btn.text() != text:
            self._filters_btn.setText(text)

    def _bulk_actions(self) -> tuple:
        return (self._b_verify, self._b_save, self._b_export, self._b_qualify, self._b_seq)

    def _wanted(self, button: QPushButton) -> bool:
        return button is not self._b_qualify or self._qualify_wanted

    @staticmethod
    def _fold_set(level: int, actions: tuple) -> tuple:
        """Which actions sit in More at a compaction level: from 2 the two
        least used, from 3 all but the primary."""
        verify, save, export, qualify, _seq = actions
        return {2: (verify, save), 3: (verify, save, export, qualify)}.get(level, ())

    def _bulk_need(self, level: int) -> int:
        """The width the bulk bar needs at a compaction level: 0 is all of it;
        1 drops "Select all N"; 2 and 3 fold actions into More."""
        lay = self._bulk_bar_w.layout()
        m = lay.contentsMargins()
        items = [self._sel_lbl.sizeHint().width() + theme.SPACE_2,
                 self._bulk_clear.sizeHint().width()]
        if level < 1 and self._sel_all_wanted:
            items.append(self._sel_all.sizeHint().width())
        folded = self._fold_set(level, self._bulk_actions())
        items += [b.sizeHint().width() for b in self._bulk_actions()
                  if self._wanted(b) and b not in folded]
        if any(self._wanted(b) for b in folded):
            items.append(self._b_more.sizeHint().width())
        return m.left() + m.right() + sum(items) + lay.spacing() * len(items)

    def _fit_bulk(self) -> None:
        """Show the bulk actions that fit; fold the rest into More. Off screen
        every wanted action shows, as on a wide window."""
        level = 0
        if self._bulk.isVisible():
            width = self._bulk_bar_w.width()
            while level < 3 and self._bulk_need(level) > width:
                level += 1
        folded = self._fold_set(level, self._bulk_actions())
        for b in self._bulk_actions():
            b.setVisible(self._wanted(b) and b not in folded)
        self._sel_all.setVisible(self._sel_all_wanted and level < 1)
        self._bulk_folded = [b for b in folded if self._wanted(b)]
        self._b_more.setVisible(bool(self._bulk_folded))

    def _show_more(self) -> None:
        """More's menu: the folded actions, armed exactly as their buttons are.
        It opens upwards — the bar sits at the foot of the window."""
        menu = QMenu(self)
        for b in self._bulk_folded:
            act = menu.addAction(b.text())
            act.setEnabled(b.isEnabled())
            act.triggered.connect(b.click)
        if menu.isEmpty():
            return
        at = self._b_more.mapToGlobal(QPoint(0, -menu.sizeHint().height() - theme.SPACE_1))
        menu.popup(at)
        self._more_menu = menu              # alive while it shows

    def _drawer(self) -> QWidget:
        """The dossier drawer. Hidden until a lead is picked; docks beside the
        results on a wide window and floats over their right edge on a narrow
        one — so opening it never squeezes the table into a sliver."""
        panel = QFrame()
        panel.setObjectName("leadDrawer")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        head.setSpacing(theme.SPACE_3)
        self._drawer_head = QHBoxLayout()
        self._drawer_head.setContentsMargins(0, 0, 0, 0)
        self._drawer_head.setSpacing(theme.SPACE_3)
        head.addLayout(self._drawer_head, 1)
        head.addWidget(C.icon_button("x", "Close", on_click=self._dismiss_drawer),
                       alignment=Qt.AlignTop)
        col.addLayout(head)
        rule = QFrame()
        rule.setObjectName("drawerRule")
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame#drawerRule{{background:{theme.HAIRLINE};border:none;}}")
        col.addWidget(rule)
        scroll = QScrollArea()
        scroll.setObjectName("drawerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().setSingleStep(_STEP)
        scroll.setStyleSheet("QScrollArea#drawerScroll{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("drawerInner")
        inner.setAttribute(Qt.WA_StyledBackground, True)
        inner.setStyleSheet(f"QWidget#drawerInner{{background:{theme.CARD};}}")
        self._drawer_lay = QVBoxLayout(inner)
        self._drawer_lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4,
                                            theme.SPACE_4, theme.SPACE_4)
        self._drawer_lay.setSpacing(theme.SPACE_3)
        self._drawer_lay.addStretch(1)
        scroll.setWidget(inner)
        col.addWidget(scroll, 1)
        self._drawer_panel = panel
        self._drawer_w = _Reveal(panel, Qt.Horizontal, self._body)
        self._drawer_w.setObjectName("leadDrawerSlot")
        self._style_drawer(floating=True)
        close = QShortcut(QKeySequence(Qt.Key_Escape), self._drawer_w)
        close.setContext(Qt.WidgetWithChildrenShortcut)
        close.activated.connect(self._dismiss_drawer)
        self._drawer_w.hide()
        return self._drawer_w

    def _style_drawer(self, floating: bool) -> None:
        # Docked, the splitter handle is its edge; floating over the table it
        # needs one of its own, and a soft shadow to lift it off the rows.
        edge = f"border-left:1px solid {theme.DIVIDER};" if floating else ""
        self._drawer_panel.setStyleSheet(
            f"QFrame#leadDrawer{{background:{theme.CARD};border:none;{edge}}}")
        self._drawer_w.set_shadow(_SHADOW if floating else 0)

    # ── the splitter, and where the drawer lives ──────────────────────────────
    def _split_sizes(self, rail: int | None = None, drawer: int | None = None) -> None:
        """Set the rail's and/or the drawer's width and give the results the
        rest. A hidden pane gets 0; a width left as None stays as it is."""
        sp = self._split
        sizes = sp.sizes()
        out = [0 if self._rail.isHidden() else (sizes[0] if rail is None else rail), 0]
        if sp.count() > 2:
            out.append(0 if self._drawer_w.isHidden()
                       else (sizes[2] if drawer is None else drawer))
        out[1] = max(1, sum(sizes) - out[0] - sum(out[2:]))
        sp.setSizes(out)

    def _on_split_moved(self, _pos: int, _index: int) -> None:
        """A handle was dragged: keep the widths it left, so a folded rail or a
        reopened drawer comes back as the user set it."""
        sizes = self._split.sizes()
        if not self._rail.isHidden() and sizes and sizes[0] >= _RAIL_MIN:
            self._rail_pref = min(_RAIL_MAX, sizes[0])
        if (self._drawer_docked and len(sizes) > 2 and not self._drawer_w.isHidden()
                and not self._drawer_sliding()):
            self._drawer_pref = max(_DRAWER_MIN, min(_DRAWER_MAX, sizes[2]))

    def _dock_room(self) -> bool:
        """Whether the drawer can dock: the results keep room for the whole
        toolbar — and never less than _TABLE_MIN — beside the rail and the
        drawer. That's measured at the toolbar's full dress, which docking
        doesn't change, so this can't flip-flop."""
        rail = 0 if self._rail.isHidden() else self._rail_pref + _HANDLE_W
        center = max(_TABLE_MIN, self._toolbar_need(0))
        need = max(_DOCK_MIN, rail + center + _HANDLE_W + self._drawer_pref)
        return self._body.width() >= need

    def _float_rect(self) -> QRect:
        """Floating, the drawer covers the results' right edge between the
        toolbar and the bulk bar, so view/sort and the bulk actions stay
        reachable while it's open."""
        body = self._body
        top = 0
        if not self._toolbar.isHidden():
            top = self._toolbar.mapTo(body, QPoint(0, self._toolbar.height())).y()
        bottom = self._view_stack.mapTo(body, QPoint(0, self._view_stack.height())).y()
        width = min(_DRAWER_W + _SHADOW, body.width())
        return QRect(body.width() - width, top, width, max(0, bottom - top))

    def _move_drawer(self, dock: bool, sized: bool = True) -> None:
        """Put the drawer in the splitter (dock) or back over the body (float)."""
        w = self._drawer_w
        shown = not w.isHidden()
        self._placing = True
        self._drawer_docked = dock          # first: the moves below re-enter via resizes
        try:
            if dock:
                self._split.addWidget(w)
                self._split.setCollapsible(self._split.indexOf(w), False)
                w.setMinimumWidth(_DRAWER_MIN)
                w.setMaximumWidth(_DRAWER_MAX)
            else:
                w.setParent(self._body)
                w.setMinimumWidth(0)
                w.setMaximumWidth(_QMAX)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            self._style_drawer(floating=not dock)
            w.setVisible(shown)             # a reparent hides a widget
            if dock and shown and sized:
                self._split_sizes(drawer=self._drawer_pref)
                self._split.refresh()
        finally:
            self._placing = False

    def _place_drawer(self) -> None:
        w = getattr(self, "_drawer_w", None)
        if w is None or w.isHidden() or self._placing or self._drawer_sliding():
            return                          # a move or a slide owns the geometry for now
        dock = self._dock_room()
        if dock != self._drawer_docked:
            self._move_drawer(dock)
        if not self._drawer_docked:
            w.setGeometry(self._float_rect())
            w.raise_()

    # ── the drawer's open and close ───────────────────────────────────────────
    def _drawer_sliding(self) -> bool:
        return self._drawer_anim.state() == QAbstractAnimation.Running

    def _open_drawer(self, dos) -> None:
        self._render_drawer(dos)
        w = self._drawer_w
        if not w.isHidden() and not (self._drawer_sliding() and not self._drawer_opening):
            self._place_drawer()            # already open: it just shows the new lead
            return
        if w.isHidden():
            self._drawer_t = 0.0
            w.show()
        if _motion_ok(self):
            self._slide_drawer(True)
        else:
            self._drawer_anim.stop()
            self._drawer_opening, self._drawer_t = True, 1.0
            self._settle_drawer()

    def _close_drawer(self) -> None:
        w = self._drawer_w
        if w.isHidden() or (self._drawer_sliding() and not self._drawer_opening):
            return                          # shut, or already on its way
        if _motion_ok(self):
            self._slide_drawer(False)
        else:
            self._drawer_anim.stop()
            self._drawer_opening, self._drawer_t = False, 0.0
            w.hide()
            self._settle_drawer()

    def _slide_drawer(self, opening: bool) -> None:
        """Slide the drawer in from the right edge, or back out. Docked, it
        grows its splitter pane while its content keeps full width and moves
        with the pane's edge; floating, it moves over the table."""
        anim = self._drawer_anim
        anim.stop()
        self._drawer_opening = opening
        if opening and self._dock_room() != self._drawer_docked:
            self._move_drawer(not self._drawer_docked, sized=False)
        w = self._drawer_w
        w.extent = (self._drawer_pref if self._drawer_docked
                    else self._float_rect().width() - w.shadow())
        if self._drawer_docked:
            # Let the pane go under its real minimum for the length of the slide.
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        start, end = self._drawer_t, (1.0 if opening else 0.0)
        self._drawer_step(start)
        anim.setDuration(max(1, round(_DRAWER_MS * abs(end - start))))
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def _drawer_step(self, t) -> None:
        self._drawer_t = float(t)
        w = self._drawer_w
        if self._drawer_docked:
            self._split_sizes(drawer=round(self._drawer_pref * self._drawer_t))
        else:
            r = self._float_rect()
            w.setGeometry(self._body.width() - round(r.width() * self._drawer_t),
                          r.top(), r.width(), r.height())
            w.raise_()

    def _drawer_landed(self) -> None:
        if not self._drawer_opening:
            self._drawer_w.hide()
        self._settle_drawer()

    def _settle_drawer(self) -> None:
        """The end of an open or a close: a docked drawer gets its real minimum
        and maximum and its width back; a floating one is placed."""
        w = self._drawer_w
        w.extent = 0
        if self._drawer_docked:
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            w.setMinimumWidth(_DRAWER_MIN)
            w.setMaximumWidth(_DRAWER_MAX)
            if not w.isHidden():
                self._split_sizes(drawer=self._drawer_pref)
            self._split.refresh()
        self._place_drawer()

    def _dismiss_drawer(self) -> None:
        """The ✕ or Esc: close it and drop the row highlight, so it doesn't reopen."""
        self._table.blockSignals(True)
        self._table.setCurrentCell(-1, -1)
        self._table.clearSelection()
        self._table.blockSignals(False)
        self._close_drawer()

    # ── data ──────────────────────────────────────────────────────────────────
    def set_dossiers(self, dossiers: list, drafts=None, all_leads=None) -> None:
        # Qualified dossiers first, then everyone else the run sourced.
        self._dossiers = list(dossiers or []) + unqualified_rows(dossiers, all_leads)
        self._draft_by = {id(d.dossier): d for d in (drafts or [])}
        self._checked = set()               # a fresh run starts with nothing ticked
        self._hidden = set()
        self._card_cbs = {}
        self._show_empty(not self._dossiers)
        self._fill_table()                  # _apply_filters() fills the gallery too
        self._update_counters()
        self._show_selected()               # nothing picked → the drawer stays shut

    def _fill_table(self):
        t = self._table
        # Never live-sorted: the Sort combo sorts once (_resort). Live sorting
        # also re-showed the header's sort arrow on every fill.
        t.setSortingEnabled(False)
        t.setRowCount(0)
        t.blockSignals(True)
        for idx, dos in enumerate(self._dossiers):
            lead = dos.lead
            row = t.rowCount()
            t.insertRow(row)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, idx)          # sort-safe dossier pointer
            t.setItem(row, _C_TICK, chk)

            # Name is the item text (sorts A–Z); the company rides along for the
            # painted two-line cell (_LeadDelegate).
            name_it = QTableWidgetItem(lead.name or "(no name)")
            name_it.setData(_COMPANY_ROLE, lead.company or "")
            name_it.setToolTip(" — ".join(p for p in (lead.name, lead.company) if p))
            t.setItem(row, _C_LEAD, name_it)
            focus_it = QTableWidgetItem(lead.title or lead.industry or "")
            where = str((lead.extra or {}).get("location") or "")
            focus_it.setData(_WHERE_ROLE, where)
            focus_it.setToolTip(" — ".join(p for p in (focus_it.text(), where) if p))
            t.setItem(row, _C_FOCUS, focus_it)

            t.setItem(row, _C_FIT, _FitItem(getattr(lead, "fit_score", 0) or 0))

            # Status and signal are painted as pills by _PillDelegate.
            t.setItem(row, _C_STATUS, QTableWidgetItem(
                status_of(dos, self._draft_by.get(id(dos)))))
            if getattr(dos, "status", "") == UNQUALIFIED:
                signal = "Not qualified"
            else:
                signal = "why-now" if getattr(dos, "signal_status", "") == "found" else ""
            t.setItem(row, _C_SIGNAL, QTableWidgetItem(signal))
        t.blockSignals(False)
        self._resort()
        self._apply_filters()
        self._refresh_bulk()

    def _dossier_at(self, row: int):
        it = self._table.item(row, _C_TICK)
        return self._dossiers[it.data(Qt.UserRole)] if it is not None else None

    # ── columns ───────────────────────────────────────────────────────────────
    def _resize_col(self, col: int, width: int) -> None:
        self._fitting = True
        try:
            self._head.resizeSection(col, width)
        finally:
            self._fitting = False

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        """A column dragged: hold it to its minimum and remember the width, so
        a narrow spell that squeezed it hands it back later."""
        if self._fitting or col not in _COL_MIN:
            return
        if new < _COL_MIN[col]:
            new = _COL_MIN[col]
            self._resize_col(col, new)
        self._col_pref[col] = new
        self._fit_columns(grown=col)

    def _fit_columns(self, grown: int = -1) -> None:
        """Lay the columns into the table's width. Focus takes what the others
        leave, never less than _FOCUS_MIN. When the table narrows the others
        give way — Lead first, then Signal, Status and Fit, each down to its
        minimum — and grow back to the widths the user left once there's room;
        past that the table scrolls sideways. A column being dragged (`grown`)
        takes nothing from the others: it stops when Focus is at its minimum."""
        t = self._table
        if not t.isVisible():
            return                          # nothing laid out yet; showing resizes it
        head = self._head
        room = t.viewport().width() - head.sectionSize(_C_TICK) - _FOCUS_MIN
        if grown in _COL_MIN:
            others = sum(head.sectionSize(c) for c in _COL_MIN if c != grown)
            cap = max(_COL_MIN[grown], room - others)
            if head.sectionSize(grown) > cap:
                self._resize_col(grown, cap)
                self._col_pref[grown] = cap
        else:
            width = {c: self._col_pref[c] for c in _COL_MIN}
            over = sum(width.values()) - room
            for c in (_C_LEAD, _C_SIGNAL, _C_STATUS, _C_FIT):
                give = max(0, min(over, width[c] - _COL_MIN[c]))
                width[c] -= give
                over -= give
            for c, w in width.items():
                if head.sectionSize(c) != w:
                    self._resize_col(c, w)
        rest = t.viewport().width() - sum(head.sectionSize(c) for c in range(head.count())
                                          if c != _C_FOCUS)
        if head.sectionSize(_C_FOCUS) != max(_FOCUS_MIN, rest):
            self._resize_col(_C_FOCUS, max(_FOCUS_MIN, rest))

    # ── interaction ───────────────────────────────────────────────────────────
    def _resort(self):
        col, order = (_C_FIT, Qt.DescendingOrder) if self._sort.currentIndex() == 0 \
            else (_C_LEAD, Qt.AscendingOrder)
        self._table.sortItems(col, order)

    def _on_sort_changed(self):
        # Not inside _resort: _fill_table calls _resort right before
        # _apply_filters, which already refills the gallery.
        self._resort()
        if self._view == "cards":
            self._fill_gallery()

    def _passes(self, dos, fmin: int, q: str, allowed: set) -> bool:
        lead = dos.lead
        if (getattr(lead, "fit_score", 0) or 0) < fmin:
            return False
        if self._only_qualified.isChecked() and getattr(dos, "status", "") == UNQUALIFIED:
            return False
        if status_of(dos, self._draft_by.get(id(dos))) not in allowed:
            return False
        if q:
            # The row shows the location now, so the search finds it too.
            where = (lead.extra or {}).get("location") or ""
            blob = f"{lead.name} {lead.company} {lead.title} {lead.email} {where}".lower()
            if q not in blob:
                return False
        return True

    def _apply_filters(self):
        fmin = self._fit_min.value()
        q = self._search.text().strip().lower()
        allowed = {n for n, cb in self._status_boxes.items() if cb.isChecked()}
        self._hidden = {i for i, dos in enumerate(self._dossiers)
                        if not self._passes(dos, fmin, q, allowed)}
        for row in range(self._table.rowCount()):
            it = self._table.item(row, _C_TICK)
            if it is not None:
                self._table.setRowHidden(row, it.data(Qt.UserRole) in self._hidden)
        shown = len(self._dossiers) - len(self._hidden)
        self._count_lbl.setText(f"Showing {shown} of {len(self._dossiers)}")
        self._fit_toolbar()
        if self._view == "cards":
            self._fill_gallery()
        self._refresh_bulk()                # selection may have lost visible rows
        self._place_drawer()                # the count text moves the dock threshold

    def _visible(self) -> list:
        """Dossier indices the filters show."""
        return [i for i in range(len(self._dossiers)) if i not in self._hidden]

    def _tick_row(self, row: int) -> None:
        """A click in the tick column, or Space: flip that row's tick through its
        item, so itemChanged → _set_checked does the rest as for any tick."""
        it = self._table.item(row, _C_TICK)
        if it is not None and not self._table.isRowHidden(row):
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _toggle_all_visible(self) -> None:
        """The header checkbox: tick every row the filters show — or, when all
        of those are ticked already, clear them. Rows the filters hide keep
        whatever tick they had (selected() leaves them out regardless)."""
        shown = self._visible()
        self._set_many(shown, not all(i in self._checked for i in shown))

    def _clear_ticks(self) -> None:
        self._set_many(list(self._checked), False)

    def _on_item_changed(self, item):
        if item.column() == _C_TICK:
            self._set_checked(item.data(Qt.UserRole),
                              item.checkState() == Qt.Checked)

    def _set_checked(self, idx: int, on: bool) -> None:
        """The one place a lead's ticked state changes — from a table row or a
        gallery card. Mirrors it into the other view and re-arms the bulk bar."""
        if idx is None:
            return
        if on:
            self._checked.add(idx)
        else:
            self._checked.discard(idx)
        self._sync_check(idx)
        self._refresh_bulk()

    def _set_many(self, idxs, on: bool) -> None:
        """Tick or clear many leads at once — select all, clear — in one pass
        over the rows and one bulk-bar refresh, not one per lead."""
        idxs = set(idxs)
        if on:
            self._checked |= idxs
        else:
            self._checked -= idxs
        state = Qt.Checked if on else Qt.Unchecked
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            it = self._table.item(row, _C_TICK)
            if it is not None and it.data(Qt.UserRole) in idxs and it.checkState() != state:
                it.setCheckState(state)
        self._table.blockSignals(False)
        for idx in idxs:
            cb = self._card_cbs.get(idx)
            if cb is not None and cb.isChecked() != on:
                cb.blockSignals(True)
                cb.setChecked(on)
                cb.blockSignals(False)
        self._refresh_bulk()

    def _sync_check(self, idx: int) -> None:
        on = idx in self._checked
        for row in range(self._table.rowCount()):
            it = self._table.item(row, _C_TICK)
            if it is not None and it.data(Qt.UserRole) == idx:
                if (it.checkState() == Qt.Checked) != on:
                    self._table.blockSignals(True)
                    it.setCheckState(Qt.Checked if on else Qt.Unchecked)
                    self._table.blockSignals(False)
                break
        cb = self._card_cbs.get(idx)
        if cb is not None and cb.isChecked() != on:
            cb.blockSignals(True)
            cb.setChecked(on)
            cb.blockSignals(False)

    def _refresh_bulk(self):
        picked = self.selected()
        n = len(picked)
        shown = len(self._dossiers) - len(self._hidden)
        self._sel_lbl.setText(f"{n} selected")
        self._sel_all.setText(f"Select all {shown}")
        self._sel_all_wanted = 0 < n < shown
        for b in (self._b_verify, self._b_save, self._b_export, self._b_seq):
            b.setEnabled(n > 0)
        # Qualify only means something while the run holds people to qualify
        # (never qualified, or a failed pass), and arms when one of them is ticked.
        self._qualify_wanted = any(getattr(d, "status", "") in RETRYABLE
                                   for d in self._dossiers)
        self._b_qualify.setEnabled(any(getattr(d, "status", "") in RETRYABLE
                                       for d in picked))
        self._head.set_check_state(Qt.Unchecked if n == 0 else
                                   Qt.Checked if n >= shown else Qt.PartiallyChecked)
        self._table.viewport().update()     # a tick tints its whole row, not one cell
        self._slide_bulk(n > 0)
        # Fold after the slide has put the bar up: measured while it was still
        # hidden, the fold came out as "everything", and a bar returning at
        # the same width gets no Resize to correct it.
        self._fit_bulk()

    def selected(self) -> list:
        return [self._dossiers[i] for i in sorted(self._checked)
                if i not in self._hidden and 0 <= i < len(self._dossiers)]

    # ── gallery (the card view) ────────────────────────────────────────────────
    def _fill_gallery(self):
        self._grid.clear()
        self._card_cbs = {}
        # Cards follow the table's row order, so Sort means the same thing in
        # both views.
        order = [self._table.item(r, _C_TICK).data(Qt.UserRole)
                 for r in range(self._table.rowCount())
                 if self._table.item(r, _C_TICK) is not None]
        self._grid.add_all([self._card_for(i, self._dossiers[i])
                            for i in order if i not in self._hidden])

    def _card_for(self, idx: int, dos) -> QWidget:
        lead = dos.lead
        draft = self._draft_by.get(id(dos))
        card = _LeadCard(idx)
        card.clicked.connect(self._card_clicked)
        v = QVBoxLayout(card)
        v.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        v.setSpacing(theme.SPACE_2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        cb = QCheckBox()
        cb.setChecked(idx in self._checked)
        cb.setStyleSheet("QCheckBox{border:none;background:transparent;}")  # see rail
        cb.toggled.connect(lambda on, i=idx: self._set_checked(i, on))
        self._card_cbs[idx] = cb
        top.addWidget(cb, alignment=Qt.AlignTop)
        top.addWidget(_avatar(lead.name, 38))
        top.addStretch(1)
        top.addWidget(self._fit_badge(getattr(lead, "fit_score", 0) or 0),
                      alignment=Qt.AlignTop)
        v.addLayout(top)

        name = QLabel(lead.name or "(no name)")
        name.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        name.setWordWrap(True)
        v.addWidget(name)
        if lead.company:
            v.addWidget(_muted(lead.company, 12))
        focus = lead.title or lead.industry or ""
        if focus:
            v.addWidget(_muted(focus, 11))

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(theme.SPACE_1)
        status = status_of(dos, draft)
        ink, bg = _TONE.get(status, (theme.NEUTRAL[700], theme.WELL))
        chips.addWidget(_pill(status, ink, bg))
        if getattr(dos, "status", "") == UNQUALIFIED:
            # The table's quiet outline, so the two views say it the same way.
            chips.addWidget(_outline_pill("Not qualified"))
        elif getattr(dos, "signal_status", "") == "found":
            chips.addWidget(_pill("why-now", theme.INFO_INK, theme.INFO_BG))
        chips.addStretch(1)
        v.addLayout(chips)
        return card

    def _fit_badge(self, fit) -> QLabel:
        ink = theme.OK if fit >= 75 else (theme.WARN if fit >= 50 else theme.NEUTRAL[500])
        lab = QLabel(f"{fit:g}")
        lab.setFixedSize(30, 30)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet(
            f"QLabel{{color:#fff;background:{ink};border-radius:15px;"
            f"font-family:'{_MONO}';font-weight:700;font-size:12px;}}")
        return lab

    def _card_clicked(self, idx: int) -> None:
        if 0 <= idx < len(self._dossiers):
            self._open_drawer(self._dossiers[idx])

    def _update_counters(self):
        n = len(self._dossiers)
        mailed = sum(1 for d in self._dossiers
                     if status_of(d, self._draft_by.get(id(d))) == "Mailed")
        fits = [getattr(d.lead, "fit_score", 0) or 0 for d in self._dossiers]
        avg = round(sum(fits) / len(fits)) if fits else 0
        self._c_new._num.setText(str(n - mailed))
        self._c_fit._num.setText(str(avg))

    # ── drawer ────────────────────────────────────────────────────────────────
    def _show_selected(self):
        row = self._table.currentRow()
        dos = self._dossier_at(row) if row >= 0 else None
        if dos is None:
            self._close_drawer()
        else:
            self._open_drawer(dos)

    def _render_drawer(self, dos):
        lay = self._drawer_lay
        _clear(lay)
        _clear(self._drawer_head)
        if dos is None:
            lay.addStretch(1)
            return
        lead = dos.lead
        draft = self._draft_by.get(id(dos))

        self._drawer_head.addWidget(_avatar(lead.name, 42), alignment=Qt.AlignTop)
        who = QVBoxLayout()
        who.setContentsMargins(0, 0, 0, 0)
        who.setSpacing(1)
        name = QLabel(lead.name or "(no name)")
        name.setWordWrap(True)
        name.setStyleSheet(f"color:{theme.TEXT};font-size:16px;font-weight:600;")
        who.addWidget(name)
        role = " · ".join(p for p in (lead.title, lead.company) if p)
        if role:
            who.addWidget(_muted(role, 12))
        self._drawer_head.addLayout(who, 1)

        lay.addWidget(self._d_card("Fit", f"{getattr(lead,'fit_score',0) or 0:g} / 100 · "
                                          f"{lead.fit_reason or ''}"))
        status = status_of(dos, draft)
        lay.addWidget(self._d_card("Deliverability", status))
        if lead.email:
            em = QLabel(lead.email)
            em.setStyleSheet(f"color:{theme.INFO_INK};font-family:'{_MONO}';font-size:11px;")
            lay.addWidget(em)
        where = (lead.extra or {}).get("location") or ""
        if where:
            lay.addWidget(self._d_card("Location", str(where)))
        if getattr(dos, "status", "") in RETRYABLE - {UNQUALIFIED}:
            # A pass that failed says why, and how to run it again.
            why = (getattr(dos, "note", "") or "The qualify pass failed.").strip()
            lay.addWidget(self._d_card(
                "Qualification", f"Couldn't be qualified: {why} Tick this lead and "
                                 "press Qualify & draft to try again."))
        if getattr(dos, "status", "") == UNQUALIFIED:
            # Nothing researched or drafted yet: no opener, no sequence to preview.
            lay.addWidget(self._d_card(
                "Qualification", "Not qualified yet. Prism sourced this person but "
                                 "hasn't researched them or drafted an email."))
            lay.addStretch(1)
            return
        opener = (draft.body if draft is not None else "") or dos.opener or ""
        if opener:
            lay.addWidget(self._d_card("Drafted opener", opener, mono=False, well=True))

        seq = QLabel("STOP-ON-REPLY SEQUENCE · 3 touches")
        seq.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
                          f"font-size:11px;letter-spacing:1px;font-weight:600;margin-top:6px;")
        lay.addWidget(seq)
        for i, (t, when) in enumerate((("First touch", "today"),
                                       ("Follow-up", "+3 days"),
                                       ("Last touch", "+7 days")), 1):
            step = QLabel(f"<b>{i}</b>&nbsp;&nbsp;{t} · "
                          f"<span style='color:{theme.NEUTRAL[600]}'>{when}</span>")
            step.setTextFormat(Qt.RichText)     # the app never auto-detects markup
            step.setWordWrap(True)
            lay.addWidget(step)
        stop = QLabel("Stops automatically the moment they reply")
        stop.setStyleSheet(f"color:{theme.OK_INK};background:{theme.OK_BG};"
                           f"border-radius:{theme.R_CONTROL}px;padding:7px 10px;font-size:11px;")
        stop.setWordWrap(True)
        lay.addWidget(stop)
        guard = QLabel("Target reply 2–4% · auto-stop if bounce > 2% · re-verify 60d")
        guard.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:11px;")
        guard.setWordWrap(True)
        lay.addWidget(guard)
        lay.addStretch(1)

    def _d_card(self, label: str, body: str, mono=False, well=False) -> QWidget:
        w = QFrame()
        w.setObjectName("dcard")           # scope: QLabel is-a QFrame (see _card)
        bg = theme.WELL if well else "transparent"
        w.setStyleSheet(
            f"QFrame#dcard{{background:{bg};border:1px solid {theme.HAIRLINE};"
            f"border-radius:{theme.R_CONTROL}px;}}")
        v = QVBoxLayout(w)
        v.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        v.setSpacing(3)
        lab = QLabel(label.upper())
        lab.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
                          f"font-size:10px;letter-spacing:1px;font-weight:600;")
        v.addWidget(lab)
        val = QLabel(body)
        val.setWordWrap(True)
        val.setStyleSheet(f"color:{theme.TEXT};font-size:12px;"
                          + (f"font-family:'{_MONO}';" if mono else ""))
        v.addWidget(val)
        return w


# ════════════════════════════════════════════════════════════════════════════
#  Shared building blocks for the non-Leads tabs
# ════════════════════════════════════════════════════════════════════════════
def _page_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{theme.TEXT};font-family:'{theme.FONT_HEADING}';"
        f"font-size:20px;font-weight:600;")
    return lab


def _section_head(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:11px;letter-spacing:1px;font-weight:600;")
    return lab


def _muted(text: str, size: int = 12) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:{size}px;")
    return lab


def _card(title: str = ""):
    """A bordered card surface → (frame, body-layout). Title optional.

    The selector is scoped to the frame by object name on purpose: QLabel is a
    QFrame subclass, so a bare `QFrame{border}` would cascade a box onto every
    label inside the card. `#leadcard` keeps the border on the card alone."""
    f = QFrame()
    f.setObjectName("leadcard")
    f.setAttribute(Qt.WA_StyledBackground, True)   # paint the fill in any container
    f.setStyleSheet(
        f"QFrame#leadcard{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};"
        f"border-radius:{theme.R_CARD}px;}}")
    v = QVBoxLayout(f)
    v.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
    v.setSpacing(theme.SPACE_3)
    if title:
        v.addWidget(_section_head(title))
    return f, v


def _pill(text: str, ink: str, bg: str) -> QLabel:
    # R_CHIP, not R_PILL: Qt drops a border-radius larger than half the height
    # and draws square corners, so 999px rendered every pill as a box.
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel{{color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
        f"padding:3px 10px;font-size:11px;font-weight:600;}}")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lab


def _outline_pill(text: str) -> QLabel:
    """A pill for a state rather than a finding ("Not qualified"): an outline,
    no fill, the same size as _pill."""
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel{{color:{theme.NEUTRAL[600]};background:transparent;"
        f"border:1px solid {theme.NEUTRAL[300]};border-radius:{theme.R_CHIP}px;"
        f"padding:2px 9px;font-size:11px;font-weight:600;}}")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lab


def _clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)      # leave the paint tree now, not on the next tick
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


def _bar_row(label: str, value: int, total: int, ink: str) -> QWidget:
    """One labelled proportion bar — label · filled track · count. The fill is a
    stretch ratio so the bar stays right when the panel is resized."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.SPACE_3)
    lab = QLabel(label)
    lab.setFixedWidth(104)
    lab.setStyleSheet(f"color:{theme.TEXT};font-size:12px;")
    h.addWidget(lab)
    track = QFrame()
    track.setFixedHeight(16)
    track.setStyleSheet(
        f"QFrame{{background:{theme.WELL};border-radius:{theme.R_CHIP}px;}}")
    th = QHBoxLayout(track)
    th.setContentsMargins(0, 0, 0, 0)
    th.setSpacing(0)
    fill = QFrame()
    fill.setStyleSheet(
        f"QFrame{{background:{ink};border-radius:{theme.R_CHIP}px;}}")
    th.addWidget(fill, max(int(value), 0))
    th.addWidget(QWidget(), max(int(total) - int(value), 0) if total else 1)
    h.addWidget(track, 1)
    num = QLabel(f"{value:g}")
    num.setFixedWidth(34)
    num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    num.setStyleSheet(
        f"color:{theme.NEUTRAL[700]};font-family:'{_MONO}';font-size:12px;")
    h.addWidget(num)
    return row


def _stat_card(label: str, value: str, sub: str = "", accent: bool = False) -> QWidget:
    f, v = _card()
    v.setSpacing(2)
    lab = QLabel(label.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:10px;letter-spacing:1px;font-weight:600;")
    v.addWidget(lab)
    num = QLabel(value)
    ink = theme.ACCENT if accent else theme.TEXT
    num.setStyleSheet(f"color:{ink};font-family:'{_MONO}';font-size:26px;font-weight:600;")
    v.addWidget(num)
    if sub:
        v.addWidget(_muted(sub, 11))
    f._num = num
    return f


# ════════════════════════════════════════════════════════════════════════════
#  Lists — the real sheets Prism has written to ~/Documents/Prism Leads
# ════════════════════════════════════════════════════════════════════════════
def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _csv_rows(path: str):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            n = sum(1 for _ in f)
        return max(n - 1, 0)
    except Exception:                                       # noqa: BLE001
        return None


class _ListsTab(QWidget):
    """The real files Prism has already written — every run's sheets and every
    saved list, in ~/Documents/Prism Leads. Each is a card you can open; the
    folder is one click away. Rescans on `refresh()`, and when the tab is shown."""

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self._folder = folder
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)

        head = QHBoxLayout()
        head.addWidget(_page_title("Saved lists"))
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        open_dir = QPushButton("Open folder")
        for b in (refresh, open_dir):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{color:{theme.TEXT};background:{theme.CARD};"
                f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
                f"padding:7px 13px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:{theme.WELL};}}")
        refresh.clicked.connect(self.refresh)
        open_dir.clicked.connect(self._open_folder)
        head.addWidget(refresh)
        head.addWidget(open_dir)
        root.addLayout(head)
        root.addWidget(_muted(
            "Every run's sheets and every list you save land here automatically — "
            "the leads sheet, the hot list and any shortlist. Open one to work it "
            "in Excel, or bring it back through “Import a sheet”."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SPACE_4)
        self._grid.setVerticalSpacing(theme.SPACE_4)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)
        self.refresh()

    def _scan(self) -> list:
        try:
            names = os.listdir(self._folder)
        except Exception:                                   # noqa: BLE001
            return []
        out = []
        for nm in names:
            if os.path.splitext(nm)[1].lower() not in (".csv", ".xlsx", ".xlsm"):
                continue
            p = os.path.join(self._folder, nm)
            try:
                st = os.stat(p)
            except Exception:                               # noqa: BLE001
                continue
            out.append((p, nm, st.st_size, st.st_mtime))
        out.sort(key=lambda r: r[3], reverse=True)
        return out

    def refresh(self) -> None:
        _clear(self._grid)
        files = self._scan()
        if not files:
            empty = QLabel(
                "No lists yet.\n\nRun “Prepare outreach” or “Leads sheet only”, "
                "or save a shortlist from the Leads tab — the files will appear "
                "here.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color:{theme.NEUTRAL[500]};font-size:13px;padding:40px;")
            self._grid.addWidget(empty, 0, 0, 1, 2)
            return
        for i, (path, name, size, mtime) in enumerate(files):
            self._grid.addWidget(self._file_card(path, name, size, mtime),
                                 i // 2, i % 2)

    def _file_card(self, path: str, name: str, size: int, mtime: float) -> QWidget:
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        f, v = _card()
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_2)
        tag = _pill(ext.upper(), theme.INFO_INK, theme.INFO_BG)
        top.addWidget(tag)
        top.addStretch(1)
        when = datetime.datetime.fromtimestamp(mtime).strftime("%d %b %Y")
        top.addWidget(_muted(when, 11))
        v.addLayout(top)

        title = QLabel(os.path.splitext(name)[0])
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        v.addWidget(title)

        rows = _csv_rows(path) if ext == "csv" else None
        meta = _human_size(size) if rows is None else f"{rows} rows · {_human_size(size)}"
        v.addWidget(_muted(meta, 11))

        btn = QPushButton("Open")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{color:#fff;background:{theme.ACCENT};border:none;"
            f"border-radius:{theme.R_CONTROL}px;padding:7px 16px;font-size:12px;"
            f"font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_RAMP[600]};}}")
        btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        btn.clicked.connect(lambda _=False, p=path: self._open(p))
        v.addWidget(btn)
        return f

    def _open(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_folder(self) -> None:
        try:
            os.makedirs(self._folder, exist_ok=True)
        except Exception:                                   # noqa: BLE001
            pass
        self._open(self._folder)


# ════════════════════════════════════════════════════════════════════════════
#  Sessions — every run Prism has kept, reopenable exactly as it was
# ════════════════════════════════════════════════════════════════════════════
_SESSION_MODES = {"sheet": "Sheet", "icp": "Find people", "icp_leads_only": "Leads sheet"}


class _SessionsTab(QWidget):
    """Every finished run is kept as a session (addons/leads/sessions.py) —
    newest first. Open one to put its leads, drafts and send status back on the
    Leads tab. People a session pulled are what the next search skips."""

    openRequested = Signal(str)

    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self._folder = folder or ""
        self._current = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)

        head = QHBoxLayout()
        head.addWidget(_page_title("Sessions"))
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setStyleSheet(
            f"QPushButton{{color:{theme.TEXT};background:{theme.CARD};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:7px 13px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.WELL};}}")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        root.addLayout(head)
        root.addWidget(_muted(
            "Every run is kept here with its leads, drafts and who was mailed. "
            "A new search skips everyone these sessions already pulled — turn "
            "that off in the search panel to go through them again."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SPACE_4)
        self._grid.setVerticalSpacing(theme.SPACE_4)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)
        self.refresh()

    def set_folder(self, folder: str) -> None:
        self._folder = folder or ""
        self.refresh()

    def set_current(self, session_id: str) -> None:
        self._current = session_id or ""
        self.refresh()

    def _headers(self) -> list:
        if not self._folder:
            return []
        try:
            from addons.leads import sessions
            return sessions.list_sessions(self._folder)
        except Exception:                                   # noqa: BLE001
            return []

    def refresh(self) -> None:
        _clear(self._grid)
        heads = self._headers()
        if not heads:
            empty = QLabel(
                "No sessions yet.\n\nEvery run you prepare is kept here — its "
                "leads, drafts and send status — so you can come back to it.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{theme.NEUTRAL[500]};font-size:13px;padding:40px;")
            self._grid.addWidget(empty, 0, 0, 1, 2)
            return
        for i, head in enumerate(heads):
            self._grid.addWidget(self._session_card(head), i // 2, i % 2)
        self._grid.setRowStretch((len(heads) + 1) // 2, 1)

    def _session_card(self, head: dict) -> QWidget:
        f, v = _card()
        sid = head.get("id", "")
        on_screen = bool(sid) and sid == self._current
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_2)
        top.addWidget(_pill(_SESSION_MODES.get(head.get("mode"), "Session"),
                            theme.INFO_INK, theme.INFO_BG))
        if on_screen:
            top.addWidget(_pill("On screen", theme.OK_INK, theme.OK_BG))
        top.addStretch(1)
        try:
            when = datetime.datetime.fromisoformat(
                head.get("created_at", "")).strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            when = head.get("created_at", "")
        top.addWidget(_muted(when, 11))
        v.addLayout(top)

        title = QLabel(head.get("label") or "Session")
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        v.addWidget(title)
        c = head.get("counts") or {}
        v.addWidget(_muted(
            f"{c.get('leads', 0)} leads · {c.get('qualified', 0)} qualified · "
            f"{c.get('hot', 0)} hot · {c.get('drafted', 0)} drafted · "
            f"{c.get('sent', 0)} mailed", 12))
        if head.get("skipped_seen"):
            v.addWidget(_muted(f"{head['skipped_seen']} already pulled, skipped", 11))

        btn = QPushButton("On screen" if on_screen else "Open")
        btn.setEnabled(not on_screen)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{color:#fff;background:{theme.ACCENT};border:none;"
            f"border-radius:{theme.R_CONTROL}px;padding:7px 16px;font-size:12px;"
            f"font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_RAMP[600]};}}"
            f"QPushButton:disabled{{background:{theme.NEUTRAL[200]};"
            f"color:{theme.NEUTRAL[600]};}}")
        btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        btn.clicked.connect(lambda _=False, s=sid: self.openRequested.emit(s))
        v.addWidget(btn)
        return f


# ════════════════════════════════════════════════════════════════════════════
#  Analytics — this run's funnel + mix, the reached-to-date ledger, guardrails
# ════════════════════════════════════════════════════════════════════════════
class _AnalyticsTab(QWidget):
    """Real numbers, honestly sourced. The funnel, deliverability mix and verdict
    mix are computed from the dossiers in hand; “reached to date” is the real
    suppression ledger (who Prism won't re-contact); the guardrails are the
    operating targets. Live reply/open/bounce tracking needs the inbox watcher
    that lands with the sequence engine — it is named as such, not faked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dossiers: list = []
        self._draft_by: dict = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        col.setSpacing(theme.SPACE_4)
        col.addWidget(_page_title("Analytics"))
        col.addWidget(_muted(
            "This run, measured. Sending metrics (opens, replies, bounces) become "
            "live meters when the inbox watcher lands with the sequence engine."))

        self._stats = QHBoxLayout()
        self._stats.setSpacing(theme.SPACE_4)
        col.addLayout(self._stats)

        self._funnel_card, self._funnel = _card("Funnel — this run")
        col.addWidget(self._funnel_card)
        self._mix_card, self._mix = _card("Deliverability")
        col.addWidget(self._mix_card)
        self._verdict_card, self._verdict = _card("Fit & verdict")
        col.addWidget(self._verdict_card)

        guard_card, guard = _card("Outreach guardrails")
        guard.addWidget(_bar_row("Reply target", 4, 100, theme.OK))
        guard.addWidget(_muted(
            "Aim for a 2–4% reply rate on cold 1:1 mail. Below ~1% says the list "
            "or the opener is off — re-qualify before sending more.", 11))
        guard.addWidget(_bar_row("Bounce ceiling", 2, 100, theme.WARN))
        guard.addWidget(_muted(
            "Keep hard bounces under 2%. Prism verifies before it sends and "
            "suppresses every bounce so a re-run never retries it; the sequence "
            "engine auto-pauses a send if bounces cross the line.", 11))
        guard.addWidget(_muted(
            "Re-verify addresses older than 60 days. One send per person, from "
            "your own inbox — never a blast.", 11))
        col.addWidget(guard_card)
        col.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.refresh()

    def set_data(self, dossiers: list, draft_by: dict) -> None:
        self._dossiers = list(dossiers or [])
        self._draft_by = dict(draft_by or {})
        self.refresh()

    def _reached_to_date(self):
        try:
            from prospector import reach
            return len(reach.load_suppression())
        except Exception:                                   # noqa: BLE001
            return None

    def refresh(self) -> None:
        dos = self._dossiers
        n = len(dos)
        drafted = sum(1 for d in dos if id(d) in self._draft_by)
        mailed = sum(1 for d in dos
                     if status_of(d, self._draft_by.get(id(d))) == "Mailed")
        reached = self._reached_to_date()

        _clear(self._stats)
        self._stats.addWidget(_stat_card("Qualified", str(n)))
        self._stats.addWidget(_stat_card("Drafted", str(drafted)))
        self._stats.addWidget(_stat_card("Mailed", str(mailed), accent=True))
        self._stats.addWidget(_stat_card(
            "Reached to date", "—" if reached is None else str(reached),
            "won't be re-contacted"))

        # Funnel — Sourced→Qualified→Drafted→Mailed off this run.
        _clear(self._funnel)
        self._funnel.addWidget(_section_head("Funnel — this run"))
        if n:
            for label, val in (("Qualified", n), ("Drafted", drafted),
                               ("Mailed", mailed)):
                self._funnel.addWidget(_bar_row(label, val, n, theme.ACCENT))
        else:
            self._funnel.addWidget(_muted(
                "Run a list to see its funnel — qualified, drafted, mailed."))

        # Deliverability mix.
        _clear(self._mix)
        self._mix.addWidget(_section_head("Deliverability"))
        if n:
            counts: dict = {}
            for d in dos:
                s = status_of(d, self._draft_by.get(id(d)))
                counts[s] = counts.get(s, 0) + 1
            order = ("Verified", "Guessed", "Catch-all", "Unknown", "Invalid",
                     "No email", "Mailed")
            for s in order:
                if counts.get(s):
                    ink = _TONE.get(s, (theme.NEUTRAL[700], theme.WELL))[0]
                    self._mix.addWidget(_bar_row(s, counts[s], n, ink))
        else:
            self._mix.addWidget(_muted(
                "Verify statuses appear here once a list is prepared."))

        # Fit & verdict.
        _clear(self._verdict)
        self._verdict.addWidget(_section_head("Fit & verdict"))
        if n:
            fits = [getattr(d.lead, "fit_score", 0) or 0 for d in dos]
            avg = round(sum(fits) / len(fits)) if fits else 0
            self._verdict.addWidget(_muted(f"Average fit  ·  {avg} / 100", 12))
            vcount = {"hot": 0, "warm": 0, "cold": 0}
            for d in dos:
                v = getattr(d, "verdict", "")
                if v in vcount:
                    vcount[v] += 1
            for label, key, ink in (("Hot", "hot", theme.OK),
                                    ("Warm", "warm", theme.WARN),
                                    ("Cold", "cold", theme.NEUTRAL[500])):
                self._verdict.addWidget(_bar_row(label, vcount[key], n, ink))
        else:
            self._verdict.addWidget(_muted(
                "Fit scores and hot/warm/cold split appear here after a run."))


# ════════════════════════════════════════════════════════════════════════════
#  Saved searches — filters kept to run again (addons/leads/saved_searches.py)
# ════════════════════════════════════════════════════════════════════════════
def _saved_when(iso: str) -> str:
    """"11 Sep, 14:02" — how a card says when a search last ran."""
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return ""


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _small_button(text: str, primary: bool) -> QPushButton:
    """The card buttons, sized like the Sessions card's Open: the app sheet
    makes a bare QPushButton 34-36px with its own border, so both carry their
    whole look. Primary is the accent fill; the other is a quiet text button
    that must not compete with it."""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if primary:
        btn.setStyleSheet(
            f"QPushButton{{color:#fff;background:{theme.ACCENT};border:none;"
            f"border-radius:{theme.R_CONTROL}px;padding:7px 16px;font-size:12px;"
            f"font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_RAMP[600]};}}"
            f"QPushButton:disabled{{background:{theme.NEUTRAL[200]};"
            f"color:{theme.NEUTRAL[600]};}}")
    else:
        btn.setStyleSheet(
            f"QPushButton{{color:{theme.NEUTRAL[700]};background:transparent;"
            f"border:1px solid transparent;border-radius:{theme.R_CONTROL}px;"
            f"padding:6px 12px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ERR_BG};color:{theme.ERR_INK};}}")
    btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return btn


class _SavedSearchesTab(QWidget):
    """The searches the owner saved from the lead filters — most recently used
    first. "Use search" puts one back in the Leads rail, ready to run; a run
    of it is recorded on its card. Pure presentation: the workbench loads,
    runs and deletes (useRequested / deleteRequested)."""

    useRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self._folder = folder or ""
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)
        root.addWidget(_page_title("Saved searches"))
        root.addWidget(_muted(
            "Filters you kept to run again. A re-run skips everyone an earlier "
            "session already pulled, so each one brings new people."))

        # The empty state sits in the page, not the grid: EmptyState centres
        # itself in the height it is given, and the grid's cells give it none.
        self._empty = C.EmptyState(
            "search", "No saved searches yet",
            "Set your filters on the Leads tab and press Save search.")
        root.addWidget(self._empty, 1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SPACE_4)
        self._grid.setVerticalSpacing(theme.SPACE_4)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)
        self.refresh()

    def set_folder(self, folder: str) -> None:
        self._folder = folder or ""
        self.refresh()

    def _records(self) -> list:
        if not self._folder:
            return []
        try:
            from addons.leads import saved_searches
            return saved_searches.list_searches(self._folder)
        except Exception:                                   # noqa: BLE001
            return []

    def cards(self) -> int:
        """How many search cards are showing — what a test counts."""
        return sum(1 for i in range(self._grid.count())
                   if self._grid.itemAt(i).widget() is not None)

    def refresh(self) -> None:
        _clear(self._grid)
        records = self._records()
        self._empty.setVisible(not records)
        self._scroll.setVisible(bool(records))
        for i, record in enumerate(records):
            self._grid.addWidget(self._search_card(record), i // 2, i % 2)
        # Rows keep their natural height; the leftover goes below the last row.
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)
        self._grid.setRowStretch((len(records) + 1) // 2, 1)

    def _chips(self, spec) -> list:
        """Up to four small chips: where, how many titles, how many industries,
        then what is excluded — in the error tone, so an exclusion reads as a
        rule at a glance."""
        where = (", ".join(spec.locations.include[:2])
                 + (f" +{len(spec.locations.include) - 2}"
                    if len(spec.locations.include) > 2 else "")
                 ) if spec.locations.include else "Anywhere"
        chips = [_pill(where, theme.INFO_INK, theme.INFO_BG)]
        n_titles, n_ind = len(spec.job_titles.include), len(spec.industries.include)
        if n_titles:
            chips.append(_pill(_plural(n_titles, "title", "titles"),
                               theme.NEUTRAL[700], theme.WELL))
        if n_ind:
            chips.append(_pill(_plural(n_ind, "industry", "industries"),
                               theme.NEUTRAL[700], theme.WELL))
        from prospector.filters import CHIP_FACETS, CLOSED_FACETS, label_of
        excluded = []
        for name in CHIP_FACETS:
            options = CLOSED_FACETS.get(name)
            excluded += [label_of(options, v) if options else v
                         for v in spec.facet(name).exclude]
        room = 4 - len(chips)
        for value in excluded[:room]:
            chip = _pill(f"\u2212 {value}", theme.ERR_INK, theme.ERR_BG)
            chip.setToolTip(f"Excluded: {value}")
            chips.append(chip)
        return chips

    def _search_card(self, record: dict) -> QWidget:
        from prospector.filters import SearchSpec
        from addons.leads import saved_searches
        f, v = _card()
        sid = record.get("id", "")
        name = record.get("name") or "Saved search"
        spec = SearchSpec.from_dict(record.get("filters"))

        title = QLabel(name)
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        v.addWidget(title)
        v.addWidget(_muted(saved_searches.summary(record), 12))

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(theme.SPACE_1 + 2)
        for chip in self._chips(spec):
            chips.addWidget(chip)
        chips.addStretch(1)
        v.addLayout(chips)

        runs = int(record.get("runs") or 0)
        when = _saved_when(record.get("last_run_at") or "")
        if runs and when:
            meta = (f"Last run {when} · {_plural(runs, 'run', 'runs')} · "
                    f"{int(record.get('last_new') or 0)} new last time")
        else:
            meta = "Never run"
        v.addWidget(_muted(meta, 11))

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(theme.SPACE_2)
        use = _small_button("Use search", primary=True)
        use.clicked.connect(lambda _=False, i=sid: self.useRequested.emit(i))
        delete = _small_button("Delete", primary=False)
        delete.clicked.connect(lambda _=False, i=sid: self.deleteRequested.emit(i))
        actions.addWidget(use)
        actions.addWidget(delete)
        actions.addStretch(1)
        v.addLayout(actions)
        f._use, f._delete = use, delete         # what a test presses
        return f


# ════════════════════════════════════════════════════════════════════════════
#  Sequences — honest shell: the real 3-touch stop-on-reply model
# ════════════════════════════════════════════════════════════════════════════
class _SequencesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)
        root.addWidget(_page_title("Sequences"))
        root.addWidget(_muted(
            "A stop-on-reply sequence: a short run of touches that halts the "
            "moment someone replies. Every message goes one-to-one from your own "
            "inbox — Prism drafts and paces; it never blasts and never auto-DMs."))

        card, v = _card("Your sequence")
        for i, (t, when, what) in enumerate((
                ("First touch", "today",
                 "the reviewed opener, grounded in the company's own why-now"),
                ("Follow-up", "+3 days", "a short nudge if there's no reply"),
                ("Last touch", "+7 days", "a final, easy-to-decline close")), 1):
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_3)
            mark = QLabel(str(i))
            mark.setFixedSize(24, 24)
            mark.setAlignment(Qt.AlignCenter)
            mark.setStyleSheet(
                f"color:#fff;background:{theme.ACCENT};border-radius:12px;"
                f"font-weight:700;font-size:12px;")
            row.addWidget(mark)
            txt = QLabel(f"<b>{t}</b> · <span style='color:{theme.NEUTRAL[600]}'>"
                         f"{when}</span><br><span style='color:{theme.NEUTRAL[600]};"
                         f"font-size:11px'>{what}</span>")
            txt.setTextFormat(Qt.RichText)
            txt.setWordWrap(True)
            row.addWidget(txt, 1)
            v.addLayout(row)
        stop = QLabel("Stops automatically the moment they reply · "
                      "pauses if bounces cross 2%")
        stop.setWordWrap(True)
        stop.setStyleSheet(
            f"color:{theme.OK_INK};background:{theme.OK_BG};"
            f"border-radius:{theme.R_CONTROL}px;padding:8px 12px;font-size:11px;")
        v.addWidget(stop)
        root.addWidget(card)

        status = QHBoxLayout()
        status.setSpacing(theme.SPACE_2)
        status.addWidget(_pill("Touch 1 live", theme.OK_INK, theme.OK_BG))
        status.addWidget(_muted(
            "Today: select leads and “Add to sequence” sends the first touch now, "
            "from your inbox. The scheduler that fires the follow-ups and watches "
            "for replies is the next build.", 12), 1)
        root.addLayout(status)
        root.addStretch(1)


# ════════════════════════════════════════════════════════════════════════════
#  The workspace — the tab strip over the five screens
# ════════════════════════════════════════════════════════════════════════════
_TABS = ("Leads", "Sessions", "Lists", "Saved searches", "Sequences", "Analytics")


class LeadsWorkspace(QWidget):
    """The whole Leads & Outreach surface. Re-exposes the cockpit's four bulk
    signals and its `set_dossiers`, so the dialog wires to it exactly as it did
    to the bare cockpit — plus it keeps Analytics, Lists, Sessions and Saved
    searches in step."""

    verifyRequested = Signal(list)
    exportRequested = Signal(list)
    saveListRequested = Signal(list)
    sequenceRequested = Signal(list)
    qualifyRequested = Signal(list)
    openSessionRequested = Signal(str)
    useSavedSearchRequested = Signal(str)
    deleteSavedSearchRequested = Signal(str)

    def __init__(self, leads_folder: str | None = None, sessions_folder: str = "",
                 searches_folder: str = "", parent=None):
        super().__init__(parent)
        self._folder = leads_folder or os.path.join(
            os.path.expanduser("~"), "Documents", "Prism Leads")
        self.leads = LeadsCockpit()
        self.leads.verifyRequested.connect(self.verifyRequested)
        self.leads.exportRequested.connect(self.exportRequested)
        self.leads.saveListRequested.connect(self.saveListRequested)
        self.leads.sequenceRequested.connect(self.sequenceRequested)
        self.leads.qualifyRequested.connect(self.qualifyRequested)
        # No folder → the tab shows its empty state and never touches disk.
        self._sessions = _SessionsTab(sessions_folder)
        self._sessions.openRequested.connect(self.openSessionRequested)
        self._lists = _ListsTab(self._folder)
        self._saved = _SavedSearchesTab(searches_folder)
        self._saved.useRequested.connect(self.useSavedSearchRequested)
        self._saved.deleteRequested.connect(self.deleteSavedSearchRequested)
        self._sequences = _SequencesTab()
        self._analytics = _AnalyticsTab()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._tabstrip())
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"QStackedWidget{{background:{theme.CANVAS};}}")
        for w in (self.leads, self._sessions, self._lists, self._saved,
                  self._sequences, self._analytics):
            self._stack.addWidget(w)
        root.addWidget(self._stack, 1)
        self._select(0)

    def _tabstrip(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("wsTabs")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#wsTabs{{background:{theme.CARD};border:none;"
            f"border-bottom:1px solid {theme.HAIRLINE};}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, 0)
        lay.setSpacing(theme.SPACE_5)
        self._tabs = []
        for i, name in enumerate(_TABS):
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, k=i: self._select(k))
            self._tabs.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        badge = _pill("Local · BYO-key · your inbox", theme.INFO_INK, theme.INFO_BG)
        badge.setToolTip("Runs on this computer with your own API keys; every "
                         "message leaves from your own mailbox.")
        lay.addWidget(badge)
        return bar

    def _style_tab(self, b: QPushButton, active: bool) -> None:
        # border-radius:0 on purpose: the app-wide QPushButton radius would curl
        # the ends of the 2px underline up into a bracket.
        if active:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid {theme.ACCENT};color:{theme.TEXT};"
                f"padding:12px 4px;margin-bottom:-1px;font-size:13px;font-weight:600;}}")
        else:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid transparent;color:{theme.NEUTRAL[600]};"
                f"padding:12px 4px;font-size:13px;font-weight:500;}}"
                f"QPushButton:hover{{color:{theme.TEXT};}}")

    def _select(self, i: int) -> None:
        self._stack.setCurrentIndex(i)
        for k, b in enumerate(self._tabs):
            self._style_tab(b, k == i)
        w = self._stack.widget(i)
        if w is self._lists:
            self._lists.refresh()
        elif w is self._sessions:
            self._sessions.refresh()
        elif w is self._saved:
            self._saved.refresh()
        elif w is self._analytics:
            self._analytics.refresh()

    # ── forwarded from the dialog ──────────────────────────────────────────────
    def set_dossiers(self, dossiers: list, drafts=None, all_leads=None) -> None:
        # The table lists everyone sourced; Analytics counts only the qualified.
        self.leads.set_dossiers(dossiers, drafts, all_leads)
        draft_by = {id(d.dossier): d for d in (drafts or [])}
        self._analytics.set_data(list(dossiers or []), draft_by)

    def refresh_lists(self) -> None:
        self._lists.refresh()

    def set_search_panel(self, widget: QWidget) -> None:
        """Mount the workbench's list-building search in the Leads rail."""
        self.leads.set_search_panel(widget)

    def set_empty_text(self, title: str = "", body: str = "") -> None:
        self.leads.set_empty_text(title, body)

    def set_sessions_folder(self, folder: str) -> None:
        self._sessions.set_folder(folder)

    def refresh_sessions(self, current_id: str = "") -> None:
        """Re-read the Sessions tab and mark which session is on screen."""
        self._sessions.set_current(current_id)

    def set_searches_folder(self, folder: str) -> None:
        self._saved.set_folder(folder)

    def refresh_searches(self) -> None:
        """Re-read the Saved searches tab — after a save, a delete or a run."""
        self._saved.refresh()
