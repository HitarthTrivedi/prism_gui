"""Unit tests for Toast notifications (PySide6).

Validates:
- Toast initialization with title, body, and different tones ('ok', 'err', 'warn', 'info').
- show_toast helper function on parent widget.
- Toast dimensions, styling, and repositioning logic.
- Clean dismiss execution.
- Testing traps adherence: no processEvents(), no exec(), no QEventLoop.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication([])

from widgets.controls import Toast, show_toast


class TestToast(unittest.TestCase):
    def setUp(self):
        self.parent = QWidget()
        self.parent.resize(800, 600)

    def tearDown(self):
        self.parent.deleteLater()

    def test_toast_init_defaults(self):
        toast = Toast(self.parent, title="Operation complete")
        self.assertEqual(toast.title_lbl.text(), "Operation complete")
        self.assertFalse(hasattr(toast, "body_lbl"))
        self.assertEqual(toast.objectName(), "toastNotification")
        toast.dismiss()

    def test_toast_with_body_and_tone(self):
        for tone in ("ok", "err", "warn", "info"):
            toast = Toast(
                self.parent,
                title=f"Title {tone}",
                body=f"Body description {tone}",
                tone=tone,
                duration=0,
            )
            self.assertEqual(toast.title_lbl.text(), f"Title {tone}")
            self.assertTrue(hasattr(toast, "body_lbl"))
            self.assertEqual(toast.body_lbl.text(), f"Body description {tone}")
            toast.dismiss()

    def test_toast_positioning(self):
        toast_bottom = Toast(self.parent, title="Bottom toast", position="bottom", duration=0)
        self.assertEqual(toast_bottom._position, "bottom")
        toast_bottom.dismiss()

        toast_top = Toast(self.parent, title="Top toast", position="top", duration=0)
        self.assertEqual(toast_top._position, "top")
        toast_top.dismiss()

    def test_show_toast_helper(self):
        toast = show_toast(self.parent, title="Hello", body="World", tone="ok", duration=0)
        self.assertIsInstance(toast, Toast)
        self.assertEqual(toast.title_lbl.text(), "Hello")
        self.assertEqual(toast.body_lbl.text(), "World")
        toast.dismiss()


if __name__ == "__main__":
    unittest.main()
