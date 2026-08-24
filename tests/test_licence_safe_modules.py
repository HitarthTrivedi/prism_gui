"""No GPL-only Qt module may reach a shipped build.

Qt Charts, Qt Graphs, Qt Quick Timeline, Qt Quick 3D, Qt Data Visualization and
Qt Virtual Keyboard are GPLv3-or-commercial, NOT LGPL like the rest of Qt. They
are importable from the installed PySide6 and they feel exactly as native as
QtWidgets does, so the only thing standing between a dashboard chart and a
licence violation is somebody remembering. This test is that somebody.

If you need charts, PyQtGraph is MIT and does the job — see docs/ui-review.md.
"""
from __future__ import annotations

import os
import re
import unittest

GPL_ONLY = (
    "QtCharts",
    "QtGraphs",
    "QtDataVisualization",
    "QtVirtualKeyboard",
    "QtQuick3D",
    "QtQuickTimeline",
    "QtQuick.Timeline",
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "build", "dist", "release", "prism_terminal",
             ".venv", "node_modules"}


def _sources():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith((".py", ".qss", ".qml")):
                path = os.path.join(folder, name)
                if os.path.abspath(path) == os.path.abspath(__file__):
                    continue        # this file names them on purpose
                yield path


class NoGplOnlyQtModules(unittest.TestCase):

    def test_no_source_file_imports_a_gpl_only_qt_module(self):
        offenders = []
        for path in _sources():
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            for module in GPL_ONLY:
                # Word-boundary match so a comment mentioning the name in prose
                # ("Qt Charts is GPL") does not fail the build; an import or a
                # QML `import QtQuick.Timeline` does.
                if re.search(rf"(import|from)\s+[\w.]*{re.escape(module)}\b", text):
                    offenders.append(f"{os.path.relpath(path, ROOT)} → {module}")
        self.assertEqual(
            offenders, [],
            "GPL-only Qt module(s) referenced. These are GPLv3-or-commercial "
            "and cannot ship in a closed-source product:\n  "
            + "\n  ".join(offenders)
            + "\n\nUse PyQtGraph (MIT) for charts instead.")


if __name__ == "__main__":
    unittest.main()
