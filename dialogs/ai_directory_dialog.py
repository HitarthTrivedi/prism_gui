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
            for i, name in enumerate(meta["agents"]):
                c = A.AGENT_REGISTRY[name]
                if q and q not in name.lower() and q not in c["specialty"].lower():
                    continue
                bg = "#181820" if i % 2 else "#141419"
                rows.append(
                    f"<tr style='background:{bg}'>"
                    f"<td style='padding:5px 10px'><b style='color:#C4B5FD'>{html.escape(name)}</b></td>"
                    f"<td style='padding:5px 10px'>{html.escape(c['specialty'])}</td>"
                    f"<td style='padding:5px 10px;color:#9CA0AA'>{html.escape(c['cost'])}</td>"
                    f"<td style='padding:5px 10px;color:#9CA0AA'>{html.escape(c['avg'])}</td></tr>")
            if not rows:
                continue
            parts.append(
                f"<h3 style='margin-bottom:2px'>{meta['emoji']} {html.escape(meta['label'])}"
                f" <span style='color:#9CA0AA;font-weight:normal;font-size:12px'>"
                f"— {html.escape(meta['desc'])}</span></h3>"
                f"<table cellspacing=0 width='100%' style='margin-bottom:14px'>"
                f"<tr style='color:#9CA0AA;font-size:11px'>"
                f"<th align=left style='padding:4px 10px'>TOOL</th>"
                f"<th align=left style='padding:4px 10px'>WHAT IT'S PICKED FOR</th>"
                f"<th align=left style='padding:4px 10px'>COST</th>"
                f"<th align=left style='padding:4px 10px'>SPEED</th></tr>"
                + "".join(rows) + "</table>")
        self.view.setHtml("".join(parts) or "<i style='color:#9CA0AA'>No matches.</i>")
