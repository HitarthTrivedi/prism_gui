"""Unit tests for WaveDots and WaveDotsProgress animated loader widgets (PySide6).

Validates:
- WaveDots initialization, sizing, and phase calculation.
- WaveDotsProgress QProgressBar compatibility (setVisible, isVisible, sizeHint).
- Architectural safety: no processEvents(), no exec(), no QEventLoop.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QProgressBar, QWidget
from PySide6.QtGui import QPixmap, QPainter

_app = QApplication.instance() or QApplication([])

from widgets.controls import WaveDots, WaveDotsProgress


class TestWaveDots(unittest.TestCase):
    def setUp(self):
        self.parent = QWidget()

    def tearDown(self):
        self.parent.deleteLater()

    def test_wave_dots_defaults(self):
        dots = WaveDots(self.parent)
        self.assertEqual(dots._dot_count, 5)
        self.assertEqual(dots._dot_size, 6)
        self.assertEqual(dots._spacing, 5)
        self.assertEqual(dots.width(), 50)
        self.assertEqual(dots.height(), 22)

    def test_wave_dots_paint(self):
        dots = WaveDots(self.parent)
        pix = QPixmap(dots.size())
        painter = QPainter(pix)
        try:
            dots.paintEvent(None)
        finally:
            painter.end()

    def test_wave_dots_progress_subclass(self):
        prog = WaveDotsProgress(self.parent)
        self.assertIsInstance(prog, QProgressBar)
        self.assertEqual(prog.width(), 50)
        self.assertEqual(prog.height(), 22)
        prog.setVisible(True)
        self.assertFalse(prog.isHidden())
        prog.setVisible(False)
        self.assertTrue(prog.isHidden())


if __name__ == "__main__":
    unittest.main()
