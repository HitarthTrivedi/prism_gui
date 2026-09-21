"""Dashboard launchers remain usable without a mouse or a signed-in session."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from widgets.home_panel import HomePanel


class ShelfHost(QWidget):
    open_addon = Signal(str)


def test_tool_tile_keyboard_routes_and_names_its_state():
    app = QApplication.instance() or QApplication([])
    host = ShelfHost()
    routes = []
    host.open_addon.connect(routes.append)
    for name, glyph, builtin, route in (
        ("Email", "mail", True, "email"),
        ("Slack", "slack", False, "catalog"),
        ("Notion", "notion", False, "catalog"),
    ):
        tile = HomePanel._make_tool_tile(host, name, glyph, builtin, route)
        try:
            assert tile.focusPolicy() == Qt.StrongFocus
            assert name in tile.accessibleName()
            assert ("Built-in" if builtin else "Not connected") in tile.accessibleName()
            QTest.keyClick(tile, Qt.Key_Space)
            assert routes[-1] == route
        finally:
            tile.close()
    assert routes == ["email", "catalog", "catalog"]
    host.close()
