"""widgets/controls.py::FlowLayout — the layout that stops a row of buttons
being cut off at the right edge of a narrow window.

The owner photographed exactly that failure: seven buttons in a QHBoxLayout
on the Inquiries tab, the last two simply gone. A flow layout has no such
width — whatever does not fit steps down a line — and this pins that.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from widgets import controls as C  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _host(width: int, labels) -> tuple[QWidget, list[QPushButton]]:
    host = QWidget()
    flow = C.FlowLayout(host)
    buttons = [QPushButton(text) for text in labels]
    for b in buttons:
        flow.addWidget(b)
    host.resize(width, 400)
    host.show()
    flow.setGeometry(host.rect())
    return host, buttons


class ButtonsWrapInsteadOfBeingCutOff(unittest.TestCase):

    LABELS = ["Prepare a quotation", "Mark as already quoted", "Edit this row",
              "Open this inquiry's folder", "Make a BOQ from the drawing",
              "Win this back", "Mark as not converted"]

    def test_wide_enough_is_one_line(self):
        host, buttons = _host(2000, self.LABELS)
        tops = {b.geometry().top() for b in buttons}
        self.assertEqual(len(tops), 1)
        host.close()

    def test_too_narrow_wraps_and_nothing_leaves_the_host(self):
        host, buttons = _host(420, self.LABELS)
        tops = {b.geometry().top() for b in buttons}
        self.assertGreater(len(tops), 1, "nothing wrapped")
        for b in buttons:
            self.assertLessEqual(b.geometry().right(), host.width(),
                                 f"{b.text()!r} sticks out past the right edge")
        host.close()

    def test_height_grows_with_the_number_of_lines(self):
        host, _ = _host(420, self.LABELS)
        layout = host.layout()
        self.assertGreater(layout.heightForWidth(420), layout.heightForWidth(2000))
        host.close()

    def test_a_hidden_button_takes_no_room(self):
        host, buttons = _host(2000, self.LABELS)
        layout = host.layout()
        before = layout.heightForWidth(300)
        for b in buttons[1:]:
            b.hide()
        after = layout.heightForWidth(300)
        self.assertLess(after, before)
        host.close()


if __name__ == "__main__":
    unittest.main()
