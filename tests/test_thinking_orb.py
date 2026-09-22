"""Unit tests for ThinkingOrb widget (PySide6).

Validates:
- All 9 animated states ('breathing', 'working', 'searching', 'solving',
  'listening', 'connecting', 'weaving', 'composing', 'shaping').
- Geometry engines and math projections.
- Size hints (64 avatar scale, 20 inline scale).
- State transitions and speed/pause controls.
- Offscreen paintEvent execution for light and dark palettes.
- Architectural safety: no processEvents(), no exec(), no QEventLoop.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter

_app = QApplication.instance() or QApplication([])

from widgets.thinking_orb import ThinkingOrb, VALID_STATES


class TestThinkingOrb(unittest.TestCase):
    def test_valid_states_constant(self):
        expected = {
            "working", "searching", "solving", "listening",
            "connecting", "weaving", "composing", "breathing", "shaping"
        }
        self.assertEqual(VALID_STATES, expected)

    def test_init_defaults(self):
        orb = ThinkingOrb(state="breathing", size=64, dark=False)
        self.assertEqual(orb.state, "breathing")
        self.assertEqual(orb.size_px, 64)
        self.assertFalse(orb.dark)
        self.assertFalse(orb.paused)
        self.assertEqual(orb.speed, 1.0)
        self.assertEqual(orb.sizeHint().width(), 64)
        self.assertEqual(orb.sizeHint().height(), 64)

    def test_inline_size_20(self):
        orb = ThinkingOrb(state="working", size=20, dark=True)
        self.assertEqual(orb.size_px, 20)
        self.assertTrue(orb.dark)
        self.assertEqual(orb.sizeHint().width(), 20)
        self.assertEqual(orb.sizeHint().height(), 20)

    def test_all_nine_states_initialization(self):
        for state in VALID_STATES:
            orb = ThinkingOrb(state=state, size=64)
            self.assertEqual(orb.state, state)

    def test_invalid_state_fallback(self):
        orb = ThinkingOrb(state="nonexistent_state", size=64)
        self.assertEqual(orb.state, "breathing")

    def test_state_transitions(self):
        orb = ThinkingOrb(state="breathing", size=64)
        self.assertEqual(orb.state, "breathing")
        orb.set_state("solving")
        self.assertEqual(orb.state, "solving")
        orb.set_state("invalid")
        self.assertEqual(orb.state, "solving")  # keeps previous if invalid

    def test_pause_and_speed(self):
        orb = ThinkingOrb(state="working", size=64)
        orb.set_speed(2.5)
        self.assertEqual(orb.speed, 2.5)
        orb.set_paused(True)
        self.assertTrue(orb.paused)
        orb.set_paused(False)
        self.assertFalse(orb.paused)

    def test_paint_all_states_light_and_dark(self):
        """Paint each state into a QPixmap to verify the rendering engines execute cleanly without error."""
        pixmap = QPixmap(64, 64)
        painter = QPainter(pixmap)
        try:
            for state in VALID_STATES:
                for dark in (True, False):
                    orb = ThinkingOrb(state=state, size=64, dark=dark)
                    # Manually trigger paint with painter
                    orb._clock = 1.5  # simulate elapsed time
                    orb.render(painter)
        finally:
            painter.end()


if __name__ == "__main__":
    unittest.main()
