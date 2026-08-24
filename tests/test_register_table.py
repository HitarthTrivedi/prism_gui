"""The register is a grid you drive from the keyboard.

These guard the three things the QFrame version could not do, and the one it
did wrong: money sorted as text, so ₹9,000 filed above ₹10,00,000.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtGui import QKeyEvent                              # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from widgets.register_table import (                             # noqa: E402
    AMOUNT, CUSTOMER, RegisterModel, RegisterTable, ROW_HEIGHT, SORT_ROLE,
)

_app = QApplication.instance() or QApplication([])


def rows():
    return [
        {"num": "INQ-1", "customer": "Zenith Springs", "item": "Coil",
         "qty": "10", "amount": "₹9,000", "amount_raw": 9000.0,
         "status": "Quoted", "tone": "accent"},
        {"num": "INQ-2", "customer": "Anand Works", "item": "Bracket",
         "qty": "20", "amount": "₹10,00,000", "amount_raw": 1000000.0,
         "status": "Won", "tone": "ok"},
        {"num": "INQ-3", "customer": "Meera Industries", "item": "Wire form",
         "qty": "30", "amount": "₹52,000", "amount_raw": 52000.0,
         "status": "New", "tone": "neutral"},
    ]


class Model(unittest.TestCase):

    def test_it_reports_its_shape(self):
        m = RegisterModel(rows())
        self.assertEqual(m.rowCount(), 3)
        self.assertEqual(m.columnCount(), 6)

    def test_money_sorts_as_money_not_as_text(self):
        """The bug this replaced: "₹9,000" sorts above "₹10,00,000" as a
        string, because "9" > "1". The sort role carries the figure."""
        m = RegisterModel(rows())
        keys = [m.data(m.index(r, AMOUNT), SORT_ROLE) for r in range(3)]
        self.assertEqual(keys, [9000.0, 1000000.0, 52000.0])
        self.assertEqual(sorted(keys), [9000.0, 52000.0, 1000000.0])

    def test_a_missing_amount_does_not_raise(self):
        m = RegisterModel([{"num": "x", "customer": "y", "item": "z",
                            "qty": "", "amount": "—", "status": "New",
                            "tone": "neutral"}])
        self.assertEqual(m.data(m.index(0, AMOUNT), SORT_ROLE), 0.0)


class Table(unittest.TestCase):

    def setUp(self):
        self.table = RegisterTable(rows())

    def test_rows_are_dense_enough_to_scan(self):
        """52px was seven or eight rows on the laptops these offices use."""
        self.assertLessEqual(ROW_HEIGHT, 34)
        self.assertEqual(self.table.verticalHeader().defaultSectionSize(),
                         ROW_HEIGHT)

    def test_sorting_by_amount_orders_by_value(self):
        self.table.sortByColumn(AMOUNT, Qt.AscendingOrder)
        shown = [self.table.model().index(r, AMOUNT).data(Qt.DisplayRole)
                 for r in range(3)]
        self.assertEqual(shown, ["₹9,000", "₹52,000", "₹10,00,000"])

    def test_the_arrow_keys_move_the_selection(self):
        self.table.selectRow(0)
        first = self.table.currentIndex().row()
        self.table.keyPressEvent(
            QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
        self.assertEqual(self.table.currentIndex().row(), first + 1)

    def test_enter_opens_the_row_under_the_cursor(self):
        seen = []
        self.table.opened.connect(seen.append)
        self.table.sortByColumn(CUSTOMER, Qt.AscendingOrder)
        self.table.selectRow(0)
        self.table.activated.emit(self.table.currentIndex())
        self.assertEqual(len(seen), 1)
        # Through the proxy: the row emitted is the one on screen, not the one
        # that happened to be first in the CSV.
        self.assertEqual(seen[0]["customer"], "Anand Works")

    def test_filtering_narrows_the_rows(self):
        self.table.filter("meera")
        self.assertEqual(self.table.model().rowCount(), 1)
        self.table.filter("")
        self.assertEqual(self.table.model().rowCount(), 3)


if __name__ == "__main__":
    unittest.main()
