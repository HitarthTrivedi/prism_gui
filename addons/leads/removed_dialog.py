"""
Leads & Outreach — the Removed list, where a removed person comes back
───────────────────────────────────────────────────────────────────────
Remove takes people off the list (removed.py). This window is where the
owner sees who, and puts any of them back: tick them, Restore. They return
to People as they stood — nothing about them was deleted, so their stage,
notes and Activities come back with them.

    dlg = RemovedDialog(records)
    if dlg.exec() == QDialog.Accepted:
        ids = dlg.chosen_ids()
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

import i18n
import theme
from dialogs.base import PrismDialog


def _when(iso: str) -> str:
    """"23 Sep 2026" — the day someone was removed."""
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return ""


class _Row(QFrame):
    """One removed person: a tick, who they are, when they were removed. A
    click anywhere on the row ticks it — the name is the target people aim
    for, not the 16-pixel box."""

    def __init__(self, record, on_change, parent=None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("removedRow")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_3)
        self.check = QCheckBox()
        self.check.toggled.connect(lambda _on: on_change())
        lay.addWidget(self.check, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        name = QLabel(record.name or record.email or i18n.t("(no name)"))
        name.setObjectName("removedName")
        text.addWidget(name)
        detail = " · ".join(p for p in (record.title, record.company, record.location) if p)
        if detail:
            sub = QLabel(detail)
            sub.setObjectName("removedDetail")
            sub.setWordWrap(True)
            text.addWidget(sub)
        lay.addLayout(text, 1)
        when = _when(record.removed_at)
        if when:
            stamp = QLabel(when)
            stamp.setObjectName("removedDetail")
            lay.addWidget(stamp, 0, Qt.AlignTop)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()                  # the release comes back to this row
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.check.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class RemovedDialog(PrismDialog):
    """Everyone taken off the list, newest first; Restore puts the ticked
    ones back."""

    def __init__(self, records, parent=None):
        super().__init__(i18n.t("Removed people"),
                         i18n.t("People you took off the list. They stay out of People "
                                "and out of new searches until you restore them."),
                         parent=parent)
        self.setMinimumSize(620, 520)
        style = (
            f"QFrame#removedRow{{background:transparent;border:none;"
            f"border-bottom:1px solid {theme.HAIRLINE};}}"
            f"QFrame#removedRow:hover{{background:{theme.WELL};}}"
            f"QLabel#removedName{{color:{theme.TEXT};font-size:13px;font-weight:600;"
            f"background:transparent;}}"
            f"QLabel#removedDetail{{color:{theme.NEUTRAL[600]};font-size:12px;"
            f"background:transparent;}}")
        self.rows: list = []
        records = list(records or ())
        self.select_all = QCheckBox(i18n.t("Select all ({n})").format(n=len(records)))
        self.select_all.setTristate(False)
        self.select_all.clicked.connect(self._tick_all)
        self.select_all.setVisible(bool(records))
        self.body.addWidget(self.select_all)

        host = QWidget()
        host.setStyleSheet(style)           # the rows' look, kept off the header
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        for record in records:
            row = _Row(record, self._changed)
            self.rows.append(row)
            col.addWidget(row)
        if not records:
            empty = QLabel(i18n.t("Nobody has been removed."))
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{theme.NEUTRAL[500]};font-size:13px;padding:40px;")
            col.addWidget(empty)
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("removedScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea#removedScroll{background:transparent;border:none;}")
        scroll.setWidget(host)
        self.body.addWidget(scroll, 1)

        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        self.restore_btn = self.button(i18n.t("Restore"), "primary", on_click=self.accept)
        self.footer.set_primary(self.restore_btn)
        self._changed()

    def _tick_all(self, on: bool) -> None:
        for row in self.rows:
            row.check.blockSignals(True)
            row.check.setChecked(on)
            row.check.blockSignals(False)
        self._changed()

    def _changed(self) -> None:
        n = len(self.chosen_ids())
        self.restore_btn.setEnabled(n > 0)
        self.restore_btn.setText(i18n.t("Restore {n}").format(n=n) if n
                                 else i18n.t("Restore"))
        self.select_all.blockSignals(True)
        self.select_all.setChecked(bool(self.rows) and n == len(self.rows))
        self.select_all.blockSignals(False)

    def chosen_ids(self) -> list:
        """The ids of the people ticked to come back."""
        return [row.record.id for row in self.rows if row.check.isChecked()]
