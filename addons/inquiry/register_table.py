"""The inquiry register, as a real table.

This replaced a stack of hand-built QFrame rows. That version looked calm and
was the wrong shape for the job: 52px per row meant seven or eight visible on
the 1366x768 laptops these offices actually use, and the people reading it
spend their day in Tally, where a register shows twenty. A register is a grid
of numbers you scan vertically, not a list of cards you read.

Going through QTableView rather than tightening the QFrames buys four things
that would each have been hand-written otherwise, and one that cannot sensibly
be hand-written at all:

    · arrow-key navigation and Enter-to-open, which is the single convention
      a Tally-trained user notices missing
    · click-a-header sorting, numeric where the column is numeric
    · virtualised painting, so a register with four thousand rows costs the
      same as one with forty
    · a selected row, so "which one am I on" survives looking away

The status column keeps its pill. That is deliberate: the pill is how status
reads at a glance in the rest of the app, and dropping to plain text here to
save a delegate would have made the register the one screen that says status
differently.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QStyledItemDelegate, QTableView,
)

import i18n
import theme
from widgets.controls import Pill

# Column order is the reading order of the paper register it replaces: which
# inquiry, whose it is, what they asked for, how many, what we quoted, where it
# stands.
NUM, CUSTOMER, ITEM, QTY, AMOUNT, STATUS = range(6)

# Sort keys live here rather than in DisplayRole so that "₹2,10,000" sorts as
# 210000 and not as the string it is printed as.
SORT_ROLE = Qt.UserRole + 1
TONE_ROLE = Qt.UserRole + 2

ROW_HEIGHT = 32


class RegisterModel(QAbstractTableModel):
    """Rows as dashboard_data.register_view() shapes them."""

    HEADS = ("INQUIRY #", "CUSTOMER", "ITEM", "QTY", "AMOUNT", "STATUS")
    RIGHT = (QTY, AMOUNT)

    def __init__(self, rows: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = list(rows or [])

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def row_at(self, index: QModelIndex) -> dict:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return {}
        return self._rows[index.row()]

    # ── Qt plumbing ───────────────────────────────────────────────────────
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return i18n.t(self.HEADS[section])
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if section in self.RIGHT \
                else int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            return (row.get("num", ""), row.get("customer", ""),
                    row.get("item", ""), row.get("qty", ""),
                    row.get("amount", ""), row.get("status", ""))[col]

        if role == SORT_ROLE:
            # Amount sorts on the figure behind the formatting; everything else
            # sorts on its own text, case-folded so "acme" and "Acme" agree.
            if col == AMOUNT:
                return float(row.get("amount_raw") or 0.0)
            if col == QTY:
                try:
                    return float(str(row.get("qty", "")).split()[0])
                except (ValueError, IndexError):
                    return 0.0
            return str(self.data(index, Qt.DisplayRole) or "").lower()

        if role == TONE_ROLE:
            return row.get("tone", "neutral")

        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if col in self.RIGHT \
                else int(Qt.AlignLeft | Qt.AlignVCenter)

        if role == Qt.ToolTipRole:
            # The two columns that get elided on a 1366-wide screen.
            if col in (CUSTOMER, ITEM):
                return self.data(index, Qt.DisplayRole)
        return None


class StatusPillDelegate(QStyledItemDelegate):
    """The same pill the rest of the app uses, painted into a cell."""

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        text = str(index.data(Qt.DisplayRole) or "")
        if not text:
            return
        tone = index.data(TONE_ROLE) or "neutral"
        bg, ink = Pill.TONES.get(tone, Pill.TONES["neutral"])

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        metrics = option.fontMetrics
        height = 19.0
        width = min(float(option.rect.width() - 10),
                    metrics.horizontalAdvance(text) + 20.0)
        pill = QRectF(option.rect.left() + 5,
                      option.rect.center().y() - height / 2 + 1, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QColor(ink))
        painter.drawText(pill, Qt.AlignCenter,
                         metrics.elidedText(text, Qt.ElideRight,
                                            int(width) - 12))
        painter.restore()


class RegisterTable(QTableView):
    """The register view, wired for keyboard and sorting."""

    opened = Signal(dict)        # a row the user pressed Enter or clicked on

    def __init__(self, rows: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.model_ = RegisterModel(rows)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model_)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)          # search every column
        self.setModel(self.proxy)

        self.setItemDelegateForColumn(STATUS, StatusPillDelegate(self))
        self.setObjectName("registerTable")
        # The Card behind it already draws the border and the rounding; a second
        # frame here would print a box inside a box.
        self.setFrameShape(QFrame.NoFrame)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setTabKeyNavigation(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        vertical = self.verticalHeader()
        vertical.setVisible(False)
        vertical.setDefaultSectionSize(ROW_HEIGHT)
        vertical.setSectionResizeMode(QHeaderView.Fixed)

        head = self.horizontalHeader()
        head.setHighlightSections(False)
        head.setSectionsMovable(False)
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for column, mode, width in (
                (NUM, QHeaderView.Fixed, 118),
                (CUSTOMER, QHeaderView.Stretch, 0),
                (ITEM, QHeaderView.Stretch, 0),
                (QTY, QHeaderView.Fixed, 88),
                (AMOUNT, QHeaderView.Fixed, 104),
                (STATUS, QHeaderView.Fixed, 112)):
            head.setSectionResizeMode(column, mode)
            if width:
                self.setColumnWidth(column, width)

        self.activated.connect(self._opened)     # Enter, and double-click
        if rows:
            self.selectRow(0)

    def set_rows(self, rows: list[dict]) -> None:
        self.model_.set_rows(rows)
        if rows:
            self.selectRow(0)

    def filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text or "")

    def _opened(self, index: QModelIndex) -> None:
        row = self.model_.row_at(self.proxy.mapToSource(index))
        if row:
            self.opened.emit(row)

    def sizeHintForRow(self, row: int) -> int:
        return ROW_HEIGHT
