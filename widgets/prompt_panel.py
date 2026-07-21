"""Panel: the full transformation chain — raw words → task brief → each
agent's engineered prompt. Read-only; this is the "see the difference"
view the CLI shows as a text panel."""
from __future__ import annotations
import html
import re
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit

import core_bridge as CB

_BULLET_RE = re.compile(r"^(\s*)[\*\-•]\s+(.*)$")
_NUM_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_LABEL_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &/,()#\-]{1,44}:?$")


def _inline_md(text: str) -> str:
    """Escape, then apply the inline markdown the briefs actually use."""
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+?)`", r"<span style='color:#67E8F9'>\1</span>", s)
    return s


def render_brief_html(text: str) -> str:
    """Turn a model's markdown-ish task brief into styled rich text: ALL-CAPS
    label bullets (GOAL:, SCOPE:) become violet sub-headings, everything else
    becomes real bullets/paragraphs — so it reads as a brief, not a raw dump
    of asterisks."""
    out: list[str] = []
    list_open = False

    def close_list():
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    def open_list():
        nonlocal list_open
        if not list_open:
            out.append("<ul style='margin:2px 0 8px 4px'>")
            list_open = True

    for raw in text.split("\n"):
        if not raw.strip():
            continue
        bullet = _BULLET_RE.match(raw)
        num = _NUM_RE.match(raw)
        if bullet:
            indent, content = len(bullet.group(1)), bullet.group(2).rstrip()
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", content).strip()
            if indent <= 1 and _LABEL_RE.match(plain):
                close_list()
                out.append(
                    f"<p style='color:#8B7CF6;font-weight:700;font-size:11px;"
                    f"letter-spacing:0.8px;margin:12px 0 4px 0'>"
                    f"{html.escape(plain.rstrip(':'))}</p>")
            else:
                open_list()
                out.append(f"<li style='margin:3px 0;color:#D6D8E0'>"
                           f"{_inline_md(content)}</li>")
        elif num:
            open_list()
            out.append(f"<li style='margin:3px 0;color:#D6D8E0'>"
                       f"{_inline_md(num.group(3).rstrip())}</li>")
        else:
            close_list()
            line = raw.strip()
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", line).strip()
            if _LABEL_RE.match(plain):
                out.append(
                    f"<p style='color:#8B7CF6;font-weight:700;font-size:11px;"
                    f"letter-spacing:0.8px;margin:12px 0 4px 0'>"
                    f"{html.escape(plain.rstrip(':'))}</p>")
            else:
                out.append(f"<p style='margin:5px 0;color:#D6D8E0;"
                           f"line-height:150%'>{_inline_md(line)}</p>")
    close_list()
    return "".join(out)


class PromptPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(6)
        title = QLabel("Your Words → Engineered Prompts")
        title.setObjectName("panelTitle")
        root.addWidget(title)

        self.empty = QLabel("Route a task above to see how Prism engineers each prompt.")
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setVisible(False)
        root.addWidget(self.view)

    def clear(self):
        self.view.setHtml("")
        self.view.setVisible(False)
        self.empty.setVisible(True)

    # ── rich-text builders (Qt has no border-radius, so filled table cells
    #    stand in for the app's glass code blocks) ──────────────────────────
    _MONO = "'JetBrains Mono','DejaVu Sans Mono',Consolas,monospace"

    @staticmethod
    def _marker(num: str, text: str, color: str = "#A78BFA") -> str:
        return (f"<p style='margin:14px 0 5px 0;color:{color};font-weight:700;"
                f"font-size:11px;letter-spacing:1.5px'>{num}&nbsp;&nbsp;{text}</p>")

    @classmethod
    def _block(cls, inner: str, bg: str, mono: bool = True,
               color: str = "#D6D8E0", italic: bool = False) -> str:
        fam = f"font-family:{cls._MONO};" if mono else ""
        ital = "font-style:italic;" if italic else ""
        body = (f"<pre style='white-space:pre-wrap;margin:0;{fam}"
                f"font-size:12px;color:{color};{ital}'>{inner}</pre>")
        return (f"<table width='100%' cellspacing='0' cellpadding='11' "
                f"style='margin:0 0 4px 0'><tr><td bgcolor='{bg}'>{body}"
                f"</td></tr></table>")

    @staticmethod
    def _rich_block(inner_html: str, bg: str) -> str:
        """Filled block for already-formatted rich HTML (not monospace)."""
        return (f"<table width='100%' cellspacing='0' cellpadding='12' "
                f"style='margin:0 0 4px 0'><tr><td bgcolor='{bg}'>{inner_html}"
                f"</td></tr></table>")

    def set_content(self, query: str, routing: dict, agents: dict):
        A = CB.agents
        esc = html.escape
        self.empty.setVisible(False)
        self.view.setVisible(True)

        parts = [self._marker("①", "YOU SAID")]
        parts.append(self._block(esc(query.strip()), "#17131F", mono=False,
                                 color="#CBC5DA", italic=True))

        brief = (routing.get("_brief") or "").strip()
        if brief:
            parts.append(self._marker("②", "PRISM'S TASK BRIEF"))
            parts.append(self._rich_block(render_brief_html(brief), "#0E0E15"))

        step = "③" if brief else "②"
        parts.append(self._marker(step, "ENGINEERED PER-AGENT PROMPTS"))
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
                    f"<span style='color:#67E8F9;font-weight:700;letter-spacing:0.5px'>"
                    f"{esc(stage.upper())}</span>"
                    f"<span style='color:#9CA0B0'> &nbsp;·&nbsp; {esc(agent)}</span></p>")
                parts.append(self._block(esc(q), "#0B0B12"))
        if not any_prompt:
            parts.append(self._block("No per-agent prompts were engineered "
                                     "for this task.", "#0B0B12", mono=False,
                                     color="#9CA0B0"))
        self.view.setHtml("".join(parts))
