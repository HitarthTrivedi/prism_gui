"""AI Directory — every tool Prism can drive and what it's picked for.
The GUI equivalent of the CLI's /catalog."""
from __future__ import annotations
import html
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLineEdit

import core_bridge as CB


class AIDirectoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Directory")
        self.resize(720, 560)
        root = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or specialty…")
        self.search.textChanged.connect(self._render)
        root.addWidget(self.search)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        root.addWidget(self.view)
        self._render("")

    def _render(self, query: str):
        A = CB.agents
        q = query.lower().strip()
        parts = []
        for cat, meta in A.CATEGORIES.items():
            rows = []
            for name in meta["agents"]:
                c = A.AGENT_REGISTRY[name]
                if q and q not in name.lower() and q not in c["specialty"].lower():
                    continue
                rows.append(
                    f"<tr><td><b>{html.escape(name)}</b></td>"
                    f"<td>{html.escape(c['specialty'])}</td>"
                    f"<td>{html.escape(c['cost'])}</td>"
                    f"<td>{html.escape(c['avg'])}</td></tr>")
            if not rows:
                continue
            parts.append(
                f"<h3>{meta['emoji']} {html.escape(meta['label'])}"
                f" <span style='color:#999;font-weight:normal'>"
                f"— {html.escape(meta['desc'])}</span></h3>"
                f"<table cellspacing=6><tr><th align=left>Tool</th>"
                f"<th align=left>What it's picked for</th>"
                f"<th align=left>Cost</th><th align=left>Speed</th></tr>"
                + "".join(rows) + "</table>")
        self.view.setHtml("".join(parts) or "<i>No matches.</i>")
