"""What a qualified lead's dossier actually FOUND — shown, not just summarised.

The table says "hot", "warm" or "why-now". This is where that is earned: the
verdict and how sure Prism is, the six dimensions it checked (Fit, Need, Timing,
Authority, Budget, Competition) each with the evidence and where it came from,
and the news that makes now a good time — headline, source, date, and a link to
read it yourself.

That is the whole point of qualifying rather than guessing. models.py is strict
that a signal always carries a source and that "we could not find evidence" is
a real answer, never dressed up as "yes"; a drawer that showed only the label
would throw that away and ask the person to trust it. So an unknown dimension
says it is unknown, and every claim that has a source shows it.

Two rules for anything that came off the web (titles, snippets, URLs):
  · it is drawn as plain text, never as markup — a headline containing `<b>` or
    a script tag is just characters;
  · the only thing that can be opened is an http(s) link, and it is escaped
    before it goes into the one rich-text label that carries it.
"""
from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

import theme

_SNIPPET_MAX = 240

# verdict -> (label, ink, tint)
_VERDICT = {
    "pass":    ("Pass",    theme.OK_INK,        theme.OK_BG),
    "warn":    ("Watch",   theme.WARN_INK,      theme.WARN_BG),
    "fail":    ("Fail",    theme.ERR_INK,       theme.ERR_BG),
    "unknown": ("Unknown", theme.NEUTRAL[600],  theme.NEUTRAL[200]),
}
_LEAD_TONE = {
    "hot":  (theme.OK_INK,        theme.OK_BG),
    "warm": (theme.WARN_INK,      theme.WARN_BG),
    "cold": (theme.NEUTRAL[700],  theme.NEUTRAL[200]),
}


def _pill(text: str, ink: str, bg: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel{{color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
        f"padding:2px 9px;font-size:11px;font-weight:600;}}")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lab


def _text(text: str, size: int = 12, colour: str = "", weight: int = 400,
          mono: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.PlainText)            # untrusted: never interpreted as markup
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    family = f"font-family:'{theme.FONT_MONO}';" if mono else ""
    lab.setStyleSheet(f"color:{colour or theme.TEXT};font-size:{size}px;"
                      f"font-weight:{weight};{family}background:transparent;")
    return lab


def _head(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:10px;letter-spacing:1px;font-weight:600;background:transparent;")
    return lab


def _card(name: str) -> tuple:
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(
        f"QFrame#{name}{{background:transparent;border:1px solid {theme.HAIRLINE};"
        f"border-radius:{theme.R_CONTROL}px;}}")
    col = QVBoxLayout(f)
    col.setContentsMargins(theme.SPACE_3, theme.SPACE_2 + 2, theme.SPACE_3, theme.SPACE_3)
    col.setSpacing(theme.SPACE_2)
    return f, col


def safe_url(url: str) -> str:
    """The URL if it is a plain http(s) link, else ''. A search result is not a
    trusted party: javascript:, file: and data: links never become clickable."""
    u = (url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) and " " not in u else ""


def when(stamp: str) -> str:
    """'2 Sep 2026' from an ISO date; the raw text if it is not one."""
    s = (stamp or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    return f"{dt.day} {dt.strftime('%b %Y')}"


def clip(text: str, limit: int = _SNIPPET_MAX) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


# ── the pieces ───────────────────────────────────────────────────────────────

def _verdict_row(dos) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(theme.SPACE_2)
    verdict = (getattr(dos, "verdict", "") or "").lower()
    ink, bg = _LEAD_TONE.get(verdict, (theme.NEUTRAL[700], theme.NEUTRAL[200]))
    lay.addWidget(_pill((verdict or "unrated").upper(), ink, bg))
    score = int(getattr(dos, "score", 0) or 0)
    lay.addWidget(_text(f"{score} / 100", 12, theme.NEUTRAL[700], 600, mono=True))
    lay.addStretch(1)
    conf = getattr(dos, "confidence", 0.0) or 0.0
    if conf > 0:
        tip = _text(f"{round(conf * 100)}% of the why-now story is sourced", 11,
                    theme.NEUTRAL[600])
        tip.setWordWrap(False)
        lay.addWidget(tip)
    return row


def _dimension_row(dim) -> QWidget:
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    label, ink, bg = _VERDICT.get(getattr(dim, "verdict", "") or "unknown", _VERDICT["unknown"])
    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.addWidget(_text(getattr(dim, "name", ""), 12, theme.TEXT, 600), stretch=1)
    top.addWidget(_pill(label, ink, bg))
    col.addLayout(top)
    evidence = (getattr(dim, "evidence", "") or "").strip()
    if evidence:
        col.addWidget(_text(evidence, 12, theme.NEUTRAL[700]))
    elif (getattr(dim, "verdict", "") or "unknown") == "unknown":
        col.addWidget(_text("No evidence found — left unknown, not assumed.", 11,
                            theme.NEUTRAL[500]))
    source = (getattr(dim, "source", "") or "").strip()
    if source:
        col.addWidget(_text(f"Source: {source}", 11, theme.NEUTRAL[500]))
    return box


def _signal_row(sig) -> QWidget:
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    title = (getattr(sig, "title", "") or "").strip()
    if title:
        col.addWidget(_text(title, 13, theme.TEXT, 600))
    snippet = clip(getattr(sig, "snippet", ""))
    if snippet:
        col.addWidget(_text(snippet, 12, theme.NEUTRAL[700]))
    cite = " · ".join(p for p in (
        (getattr(sig, "source", "") or "").strip(), when(getattr(sig, "published", ""))) if p)
    if cite:
        col.addWidget(_text(cite, 11, theme.NEUTRAL[500]))
    url = safe_url(getattr(sig, "url", ""))
    if url:
        link = QLabel(f'<a href="{html.escape(url, quote=True)}" '
                      f'style="color:{theme.INFO_INK};">Read the source</a>')
        link.setTextFormat(Qt.RichText)
        link.setOpenExternalLinks(True)
        link.setToolTip(url)
        link.setStyleSheet("font-size:11px;background:transparent;")
        col.addWidget(link)
    return box


def _has_evidence(dos) -> bool:
    return bool(getattr(dos, "dimensions", None) or getattr(dos, "signals", None)
                or (getattr(dos, "summary", "") or "").strip())


def headline(dos) -> list:
    """The verdict, how sure Prism is, and the one-line summary — what belongs
    at the very top of the drawer. Empty when there is nothing to say."""
    if not _has_evidence(dos):
        return []
    out = [_verdict_row(dos)]
    summary = (getattr(dos, "summary", "") or "").strip()
    if summary:
        out.append(_text(summary, 12, theme.NEUTRAL[700]))
    return out


def detail(dos) -> list:
    """The six dimensions with their evidence, then the why-now news with its
    source. Empty when the dossier has nothing to show (an unqualified row, a
    failed pass)."""
    out: list = []
    if not _has_evidence(dos):
        return out
    dims = list(getattr(dos, "dimensions", None) or [])
    sigs = list(getattr(dos, "signals", None) or [])

    if dims:
        card, col = _card("evQual")
        col.addWidget(_head("Qualification"))
        for i, d in enumerate(dims):
            if i:
                rule = QFrame()
                rule.setFixedHeight(1)
                rule.setStyleSheet(f"background:{theme.HAIRLINE};")
                col.addWidget(rule)
            col.addWidget(_dimension_row(d))
        out.append(card)

    status = getattr(dos, "signal_status", "") or ""
    if sigs or status in ("none", "source_error"):
        card, col = _card("evNow")
        col.addWidget(_head("Why now"))
        if sigs:
            for i, s in enumerate(sigs):
                if i:
                    rule = QFrame()
                    rule.setFixedHeight(1)
                    rule.setStyleSheet(f"background:{theme.HAIRLINE};")
                    col.addWidget(rule)
                col.addWidget(_signal_row(s))
        elif status == "source_error":
            col.addWidget(_text("The news search failed, so nothing is claimed here. "
                                "Run it again to look.", 12, theme.WARN_INK))
        else:
            col.addWidget(_text("No recent news found — Prism doesn't invent a reason.",
                                12, theme.NEUTRAL[600]))
        out.append(card)
    return out


def build(dos) -> list:
    """Headline then detail, in reading order."""
    return headline(dos) + detail(dos)
