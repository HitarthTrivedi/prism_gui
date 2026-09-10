"""The measured quantities, as a table a person can read.

Until 10 Sep 2026 the BOQ window showed the measurement as the same plain
text the AI prompt carries -- "LENGTHS BY LAYER:" and a wall of
"  layer: 498.44 unspecified" lines in a 120 px box -- which is a prompt,
not a report. The owner asked for the numbers the way the CSV has them:
one row per measured item, columns, readable at a glance.

Pure widget over the `q` dict core.boq.measure() returns; the prompt text
(core.boq.summary_text) is untouched and still what the AI is given.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import i18n
import theme
from widgets import controls as C

KIND_LENGTH = "Length"
KIND_AREA = "Area"
KIND_COUNT = "Count"


def rows_for(q: dict) -> list[tuple[str, str, str, float, str]]:
    """(item, kind, layer, value, unit) for every measured figure, lengths
    first, then areas, then block counts -- the CSV's own order."""
    unit = q.get("unit") or "unspecified"
    out = []
    for layer, length in (q.get("lengths_by_layer") or {}).items():
        out.append((layer, KIND_LENGTH, layer, float(length), unit))
    for layer, area in (q.get("areas_by_layer") or {}).items():
        out.append((layer, KIND_AREA, layer, float(area), f"sq {unit}"))
    layers_of = q.get("block_layers") or {}
    for name, count in (q.get("block_counts") or {}).items():
        out.append((name, KIND_COUNT, ", ".join(layers_of.get(name) or []),
                    float(count), "nos"))
    return out


def _fmt(kind: str, value: float) -> str:
    if kind == KIND_COUNT:
        return f"{int(value):,}"
    return f"{value:,.2f}"


class MeasuredTable(QWidget):
    """Header line, warnings, the table, and the layer list on demand."""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)

        self.header = C.label("", level="BODY", wrap=True)
        col.addWidget(self.header)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(
            f"color: {theme.WARN_INK}; background: {theme.WARN_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        self.warn.setVisible(False)
        col.addWidget(self.warn)

        # Five columns a person reads, and a sixth, hidden, that holds the
        # CSV's own order: a sortable table re-sorts itself on whatever
        # column was last clicked when it is refilled, and the default
        # view must be the file's order, lengths then areas then counts.
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            i18n.t("Item"), i18n.t("Measured as"), i18n.t("Layer"),
            i18n.t("Value"), i18n.t("Unit"), "#"])
        self.table.setColumnHidden(5, True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        row_h = self.table.verticalHeader().defaultSectionSize()
        head_h = head.sizeHint().height()
        # Ten rows on screen, the rest scroll: a 64-layer survey is a long
        # list, and a table that shows only its header is a table nobody reads.
        self.table.setMinimumHeight(head_h + 6 * row_h + 4)
        self.table.setMaximumHeight(head_h + 10 * row_h + 4)
        col.addWidget(self.table)

        self.layers_btn = C.button(i18n.t("Show every layer name"), "tertiary",
                                   small=True, on_click=self._toggle_layers)
        col.addWidget(self.layers_btn, alignment=Qt.AlignLeft)
        self.layers = C.label("", level="SUPPORT", wrap=True)
        self.layers.setVisible(False)
        col.addWidget(self.layers)
        self._layer_names: list[str] = []

    # ── data ─────────────────────────────────────────────────────────────
    def set_quantities(self, q: dict):
        unit = q.get("unit") or "unspecified"
        self.header.setText(i18n.t(
            "Drawing units: {unit} · {entities:,} entities · {layers} layers").format(
            unit=unit, entities=int(q.get("entity_count") or 0),
            layers=len(q.get("layers") or [])))
        warnings = []
        if not q.get("unit_confirmed", q.get("unit_code", 0) != 0):
            warnings.append(i18n.t(
                "Unit not confirmed — the drawing's unit was not recorded. "
                "Every value is in the drawing's raw unit (mm, m or ft); "
                "confirm it against the source before this goes near a rate."))
        if "scope_keywords" in q:
            warnings.append(i18n.t(
                "Scope filter on ({words}) — {shown} of the drawing's {total} "
                "layers are shown.").format(
                words=", ".join(q["scope_keywords"]),
                shown=len(q.get("layers") or []),
                total=q.get("scope_total_layers", len(q.get("layers") or []))))
        warnings += [str(n) for n in (q.get("notes") or [])]
        self.warn.setText("\n".join(f"⚠ {w}" for w in warnings))
        self.warn.setVisible(bool(warnings))

        rows = rows_for(q)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, (item, kind, layer, value, unit_name) in enumerate(rows):
            cells = [item, i18n.t(kind), layer, _fmt(kind, value), unit_name]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c == 3:
                    cell.setData(Qt.UserRole, value)
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                self.table.setItem(r, c, cell)
            self.table.setItem(r, 5, QTableWidgetItem(f"{r:06d}"))
        self.table.setSortingEnabled(True)
        self.table.sortItems(5, Qt.AscendingOrder)
        if not rows:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem(i18n.t(
                "No measurable lines, polylines, hatches or blocks were found.")))
        self._layer_names = list(q.get("layers") or [])
        self.layers_btn.setVisible(bool(self._layer_names))
        self.layers.setText(i18n.t("All {n} layers: {names}").format(
            n=len(self._layer_names), names=", ".join(self._layer_names)))

    def rows(self) -> list:
        """What is on screen, row by row -- for tests and for eyes."""
        out = []
        for r in range(self.table.rowCount()):
            out.append(tuple((self.table.item(r, c).text() if self.table.item(r, c) else "")
                             for c in range(5)))
        return out

    def _toggle_layers(self):
        show = not self.layers.isVisible()
        self.layers.setVisible(show)
        self.layers_btn.setText(i18n.t("Hide the layer names") if show
                                else i18n.t("Show every layer name"))
