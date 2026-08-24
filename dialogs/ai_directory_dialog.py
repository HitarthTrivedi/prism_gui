"""AI Directory — every tool Prism can drive and what it's picked for.
The GUI equivalent of the CLI's /catalog."""
from __future__ import annotations
import html
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLineEdit

import core_bridge as CB
import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C


class AIDirectoryDialog(PrismDialog):
    def __init__(self, parent=None):
        super().__init__(
            i18n.t("AI directory"),
            i18n.t("Every tool Prism can drive, what it is picked for, and "
                   "what it costs."),
            icon="grid", parent=parent, closable=False)
        self.setWindowTitle("AI Directory")
        self.resize(780, 600)
        self.setMinimumSize(560, 440)
        root = self.body
        # The one search box, so filtering a catalogue looks the same here as
        # it does on the screens that already use it.
        self.search = C.SearchField(i18n.t("Filter by name or specialty…"))
        self.search.textChanged.connect(self._render)
        root.addWidget(self.search)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        root.addWidget(self.view, stretch=1)
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))
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
                # WELL / CARD, the two surfaces this system has for a striped
                # table. NEUTRAL[200] is a border grey and was heavy enough
                # that every other row read as disabled.
                bg = theme.WELL if i % 2 else theme.CARD
                rows.append(
                    f"<tr style='background:{bg}'>"
                    f"<td style='padding:5px 10px'><b style='color:{theme.ACCENT_RAMP[800]}'>{html.escape(name)}</b></td>"
                    f"<td style='padding:5px 10px'>{html.escape(c['specialty'])}</td>"
                    f"<td style='padding:5px 10px;color:{theme.NEUTRAL[600]}'>{html.escape(c['cost'])}</td>"
                    f"<td style='padding:5px 10px;color:{theme.NEUTRAL[600]}'>{html.escape(c['avg'])}</td></tr>")
            if not rows:
                continue
            parts.append(
                f"<h3 style='margin-bottom:2px'>{html.escape(meta['label'])}"
                f" <span style='color:{theme.NEUTRAL[600]};font-weight:normal;font-size:12px'>"
                f"— {html.escape(meta['desc'])}</span></h3>"
                f"<table cellspacing=0 width='100%' style='margin-bottom:14px'>"
                f"<tr style='color:{theme.NEUTRAL[600]};font-size:11px'>"
                f"<th align=left style='padding:4px 10px'>TOOL</th>"
                f"<th align=left style='padding:4px 10px'>WHAT IT'S PICKED FOR</th>"
                f"<th align=left style='padding:4px 10px'>COST</th>"
                f"<th align=left style='padding:4px 10px'>SPEED</th></tr>"
                + "".join(rows) + "</table>")
        self.view.setHtml("".join(parts) or f"<i style='color:{theme.NEUTRAL[600]}'>No matches.</i>")
