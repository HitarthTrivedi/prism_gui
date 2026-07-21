"""Panel: the full transformation chain — raw words → task brief → each
agent's engineered prompt. Read-only; this is the "see the difference"
view the CLI shows as a text panel."""
from __future__ import annotations
import html
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit

import core_bridge as CB


class PromptPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        title = QLabel("Your Words → Engineered Prompts")
        title.setObjectName("panelTitle")
        root.addWidget(title)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        root.addWidget(self.view)

    def clear(self):
        self.view.setHtml("")

    def set_content(self, query: str, routing: dict, agents: dict):
        A = CB.agents
        esc = html.escape
        parts = [f"<p><b>1 · You said:</b><br><i>{esc(query.strip())}</i></p>"]
        brief = (routing.get("_brief") or "").strip()
        step = 2
        if brief:
            parts.append(
                f"<p><b>2 · Prism expanded it into this task brief:</b><br>"
                f"<pre style='white-space:pre-wrap'>{esc(brief)}</pre></p>")
            step = 3
        parts.append(f"<p><b>{step} · …and engineered each AI's prompt from it:</b></p>")
        for stage in A.PIPELINE_ORDER:
            data = routing.get(stage)
            if not data or not data.get("needed") or not data.get("questions"):
                continue
            agent = agents.get(stage) or A.summary_agent_name(agents) or "?"
            for q in data["questions"]:
                parts.append(
                    f"<p><b>{stage.upper()}</b> <span style='color:#999'>"
                    f"({esc(agent)}) gets:</span><br>"
                    f"<pre style='white-space:pre-wrap'>{esc(q)}</pre></p>")
        self.view.setHtml("".join(parts))
