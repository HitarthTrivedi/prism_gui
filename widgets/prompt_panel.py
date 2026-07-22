"""Context rail, bottom half: "Behind the scenes".

The full transformation chain — your raw words → Prism's task brief → the
engineered prompt each tool actually receives. The design files this under a
disclosure with the note "Optional — only if you're curious", so it ships
collapsed: the rail stays about the plan, and this opens only when asked."""
from __future__ import annotations
import html
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
)

import core_bridge as CB
import theme
from widgets import icons
from widgets.controls import kicker
from widgets.markdown import render_markdown


class PromptPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.toggle = QPushButton("  BEHIND THE SCENES")
        self.toggle.setObjectName("ghostBtn")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setCheckable(True)
        self.toggle.setLayoutDirection(Qt.RightToLeft)   # chevron on the right
        self.toggle.setStyleSheet(
            "text-align: right; padding: 2px 0; font-family: 'Barlow Condensed';"
            "font-size: 11.5px; font-weight: 600; color: #416180;")
        icons.button_icon(self.toggle, "chevron-right", 16, theme.NEUTRAL[500])
        self.toggle.toggled.connect(self._on_toggled)
        root.addWidget(self.toggle)

        self.blurb = QLabel(self._BLURB)
        self.blurb.setObjectName("meta")
        self.blurb.setWordWrap(True)
        root.addWidget(self.blurb)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(230)
        self.view.setVisible(False)
        root.addWidget(self.view)

        self._has_content = False

    _BLURB = ("See exactly what Prism will ask each tool, in plain English. "
              "Optional — only if you're curious.")

    def _on_toggled(self, open_: bool):
        icons.button_icon(self.toggle, "chevron-down" if open_ else "chevron-right",
                          16, theme.NEUTRAL[500])
        if open_ and self._has_content:
            self.blurb.setVisible(False)
            self.view.setVisible(True)
            return
        self.view.setVisible(False)
        self.blurb.setText("Nothing to show yet — make a plan first."
                           if open_ else self._BLURB)
        self.blurb.setVisible(True)

    def clear(self):
        self.view.setHtml("")
        self._has_content = False
        self.view.setVisible(False)
        # If the disclosure was left open, put the explainer back — otherwise
        # clearing leaves a bare header over nothing.
        self._on_toggled(self.toggle.isChecked())

    # ── rich-text builders ────────────────────────────────────────────────
    _MONO = "'JetBrains Mono','DejaVu Sans Mono',Consolas,monospace"

    @staticmethod
    def _marker(num: str, text: str) -> str:
        return (f"<p style='margin:14px 0 5px 0;color:{theme.ACCENT_RAMP[700]};"
                f"font-weight:600;font-size:11px'>{num}&nbsp;&nbsp;{text}</p>")

    @classmethod
    def _block(cls, inner: str, bg: str, mono: bool = True,
               color: str = None, italic: bool = False) -> str:
        color = color or theme.NEUTRAL[800]
        fam = f"font-family:{cls._MONO};" if mono else ""
        ital = "font-style:italic;" if italic else ""
        body = (f"<pre style='white-space:pre-wrap;margin:0;{fam}"
                f"font-size:12px;color:{color};{ital}'>{inner}</pre>")
        return (f"<table width='100%' cellspacing='0' cellpadding='10' "
                f"style='margin:0 0 4px 0'><tr><td bgcolor='{bg}'>{body}"
                f"</td></tr></table>")

    @staticmethod
    def _rich_block(inner_html: str, bg: str) -> str:
        """Filled block for already-formatted rich HTML (not monospace)."""
        return (f"<table width='100%' cellspacing='0' cellpadding='11' "
                f"style='margin:0 0 4px 0'><tr><td bgcolor='{bg}'>{inner_html}"
                f"</td></tr></table>")

    def set_content(self, query: str, routing: dict, agents: dict):
        A = CB.agents
        esc = html.escape

        parts = [self._marker("01", "YOU SAID")]
        parts.append(self._block(esc(query.strip()), theme.SURFACE, mono=False,
                                 color=theme.NEUTRAL[800], italic=True))

        brief = (routing.get("_brief") or "").strip()
        if brief:
            parts.append(self._marker("02", "PRISM'S TASK BRIEF"))
            parts.append(self._rich_block(render_markdown(brief), theme.NEUTRAL[100]))

        step = "03" if brief else "02"
        parts.append(self._marker(step, "ENGINEERED PER-TOOL PROMPTS"))
        any_prompt = False
        for stage in A.PIPELINE_ORDER:
            data = routing.get(stage)
            if not data or not data.get("needed") or not data.get("questions"):
                continue
            agent = agents.get(stage) or A.summary_agent_name(agents) or "?"
            for q in data["questions"]:
                any_prompt = True
                parts.append(
                    f"<p style='margin:10px 0 3px 0'>"
                    f"<span style='color:{theme.ACCENT_RAMP[800]};font-weight:600'>"
                    f"{esc(stage.upper())}</span>"
                    f"<span style='color:{theme.NEUTRAL[600]}'> &nbsp;·&nbsp; "
                    f"{esc(agent)}</span></p>")
                parts.append(self._block(esc(q), theme.NEUTRAL[100]))
        if not any_prompt:
            parts.append(self._block("No per-tool prompts were engineered for "
                                     "this task.", theme.NEUTRAL[100], mono=False,
                                     color=theme.NEUTRAL[600]))
        self.view.setHtml("".join(parts))
        self._has_content = True
        if self.toggle.isChecked():
            self.view.setVisible(True)
            self.blurb.setVisible(False)
