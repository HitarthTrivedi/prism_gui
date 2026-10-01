"""Qt silently drops a stylesheet it cannot parse and prints one warning per
widget: "Could not parse stylesheet of object QPushButton(0x...)". The widget
just renders unstyled, so nothing fails and nothing is seen until someone reads
a terminal. A stray `}}` in the Appearance wallpaper tiles did exactly that, a
warning for every tile, found by walking Settings in the real window
(1 Oct 2026). This opens every Settings section with Qt's own message handler
listening and fails on any stylesheet Qt rejects."""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])


class EverySettingsSectionParses(unittest.TestCase):

    def test_no_stylesheet_in_settings_is_rejected_by_qt(self):
        from widgets import settings_panel as SP

        seen: list[str] = []

        def handler(_mode, _ctx, message):
            if "Could not parse" in message:
                seen.append(message)

        previous = qInstallMessageHandler(handler)
        try:
            panel = SP.SettingsPanel({})
            for key, *_rest in SP.SECTIONS:
                panel.show_section(key)
                # Styles apply when a widget is polished; re-applying each one
                # makes Qt parse it now, on the same widget, so a bad one is
                # reported here rather than whenever it is first painted.
                for w in panel.findChildren(QWidget):
                    ss = w.styleSheet()
                    if ss:
                        w.setStyleSheet("")
                        w.setStyleSheet(ss)
        finally:
            qInstallMessageHandler(previous)
        self.assertEqual(seen, [], "Qt rejected %d stylesheet(s); first: %s"
                         % (len(seen), seen[0] if seen else ""))


if __name__ == "__main__":
    unittest.main()
