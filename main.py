#!/usr/bin/env python3
"""
Prism GUI — desktop entry point
────────────────────────────────
    python3 main.py

A native desktop app (PySide6/Qt) — no browser, no server, nothing "online"
about it. It is a pure UI layer: every routing decision and every browser
automation call is delegated straight into prism_terminal/core/*.py via
core_bridge.py, so the CLI and GUI share one engine and one ~/.prism config.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

import theme
from main_window import MainWindow
from widgets import icons


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Prism")
    # Register Barlow before any widget is constructed — a QFont resolved
    # against a missing family stays resolved, so loading late leaves the
    # first-built widgets on the fallback sans.
    theme.load_fonts()
    # Titlebar, taskbar, alt-tab and every dialog inherit this.
    app.setWindowIcon(icons.logo_icon())

    here = os.path.dirname(os.path.abspath(__file__))
    style_path = os.path.join(here, "style.qss")
    if os.path.exists(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            qss = f.read()
        app.setStyleSheet(qss.replace("%ASSETS%", os.path.join(here, "assets")))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
