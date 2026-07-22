"""Run history — every past run, as something you can actually read.

Runs are stored as raw JSON dumps (`~/.prism/runs/run_<epoch>.json`, written
by prism_terminal's config.save_run). Showing that file verbatim makes the
user parse a machine format to answer human questions: what did I ask, which
tool did what, what came back. So the file is read as data and re-rendered —
one section per step, with the step's plain-English name, the tool that ran
it, what Prism asked it, and what it said back as formatted prose."""
from __future__ import annotations
import json
import os
import time
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QTextBrowser, QWidget, QPushButton, QSplitter, QSizePolicy,
)

import core_bridge as CB
import theme
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import heading, kicker
from widgets.markdown import render_markdown

_PATH_ROLE = 1000


def _when(filename: str) -> tuple[str, str]:
    """('22 Jul 2026', '14:21') from run_<epoch>.json, falling back to the
    file's own mtime if the name isn't in that shape."""
    stamp = filename.removeprefix("run_").removesuffix(".json")
    try:
        moment = time.localtime(int(stamp))
    except ValueError:
        moment = time.localtime(os.path.getmtime(filename))
    return time.strftime("%d %b %Y", moment), time.strftime("%H:%M", moment)


def _one_line(text: str, limit: int = 90) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def _attachment_name(entry) -> str:
    """Records written by the CLI store attachments as bare names; the GUI
    matches that, but a dict could turn up from an older or hand-edited file,
    so read both rather than throwing on the whole run."""
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("path") or "?")
    return str(entry)


class _Elided(QLabel):
    """A label that shortens to fit rather than being cut off mid-word. The
    run list lives in a splitter, so the available width isn't known up front
    and a fixed character budget would clip at some sizes and waste space at
    others."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def paintEvent(self, event):
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self._full, Qt.ElideRight, self.width()))
        super().paintEvent(event)


class _RunItem(QWidget):
    """Two-line list row: when it ran, and what was asked."""

    def __init__(self, day: str, clock: str, query: str, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(2)
        when = QLabel(f"{day} · {clock}")
        when.setObjectName("meta")
        box.addWidget(when)
        what = _Elided(_one_line(query, 160) or "(no task recorded)")
        what.setStyleSheet("font-size: 13px; font-weight: 500;")
        box.addWidget(what)


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run history")
        self.resize(940, 640)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(9)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("clock", 20, theme.ACCENT))
        head.addWidget(glyph)
        head.addWidget(heading("Run history"), stretch=1)
        root.addLayout(head)

        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(7)
        left_box.addWidget(kicker("Past runs", muted=True))
        self.runs = QListWidget()
        self.runs.setFrameShape(QListWidget.NoFrame)
        self.runs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.runs.currentItemChanged.connect(self._show)
        left_box.addWidget(self.runs, stretch=1)
        split.addWidget(left)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.setSpacing(7)
        right_box.addWidget(kicker("What happened", muted=True))
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        right_box.addWidget(self.view, stretch=1)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([280, 620])
        root.addWidget(split, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("Close")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

        self._load()

    # ── data ──────────────────────────────────────────────────────────────
    def _load(self):
        runs_dir = CB.config.RUNS_DIR
        names = []
        if os.path.isdir(runs_dir):
            names = sorted((n for n in os.listdir(runs_dir) if n.endswith(".json")),
                           reverse=True)
        if not names:
            self.runs.setEnabled(False)
            self.view.setHtml(self._page(
                "<p style='color:%s'>No runs saved yet. Once Prism finishes a "
                "task, it turns up here.</p>" % theme.NEUTRAL[600]))
            return
        for name in names:
            path = os.path.join(runs_dir, name)
            day, clock = _when(name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    query = (json.load(f) or {}).get("query", "")
            except Exception:
                query = "(unreadable run file)"
            item = QListWidgetItem()
            item.setData(_PATH_ROLE, path)
            item.setToolTip(name)
            widget = _RunItem(day, clock, query)
            # +4 so descenders on the query line aren't shaved off — the row
            # widget's own hint is exact, and the item view gives no slack.
            item.setSizeHint(QSize(0, widget.sizeHint().height() + 4))
            self.runs.addItem(item)
            self.runs.setItemWidget(item, widget)
        self.runs.setCurrentRow(0)

    def _show(self, item: QListWidgetItem, _previous=None):
        if item is None:
            return
        path = item.data(_PATH_ROLE)
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception as e:
            self.view.setHtml(self._page(
                f"<p style='color:#8a2f2f'>Couldn't read {os.path.basename(path)}: "
                f"{e}</p>"))
            return
        self.view.setHtml(self._page(self._render(record, os.path.basename(path))))

    # ── rendering ─────────────────────────────────────────────────────────
    @staticmethod
    def _page(body: str) -> str:
        return (f"<body style='font-family:{theme.FONT_BODY}; font-size:14px; "
                f"color:{theme.TEXT}'>{body}</body>")

    def _render(self, record: dict, filename: str) -> str:
        A = CB.agents
        routing = record.get("routing") or {}
        responses = record.get("responses") or {}
        links = record.get("links") or {}
        attachments = record.get("attachments") or []
        day, clock = _when(filename)

        ran = [s for s in A.PIPELINE_ORDER
               if (routing.get(s) or {}).get("needed")
               and (routing.get(s) or {}).get("questions")]

        parts = [
            f"<p style='font-family:{theme.FONT_HEADING};font-size:22px;"
            f"margin:0 0 4px 0'>{_esc(_one_line(record.get('query', ''), 400))}</p>",
            f"<p style='color:{theme.NEUTRAL[600]};font-size:12px;margin:0 0 4px 0'>"
            f"{day} at {clock} &nbsp;·&nbsp; {len(ran)} step{'' if len(ran) == 1 else 's'}"
            + (f" &nbsp;·&nbsp; {len(attachments)} file"
               f"{'' if len(attachments) == 1 else 's'}" if attachments else "")
            + "</p>",
        ]

        if attachments:
            names = ", ".join(_esc(_attachment_name(a)) for a in attachments)
            parts.append(f"<p style='color:{theme.NEUTRAL[600]};font-size:12px;"
                         f"margin:0 0 14px 0'>Files: {names}</p>")
        if record.get("error"):
            parts.append(
                f"<table width='100%' cellspacing='0' cellpadding='10'"
                f"><tr><td bgcolor='#fdeeee'><span style='color:#8a2f2f'>"
                f"This run stopped early — {_esc(record['error'])}</span>"
                f"</td></tr></table>")
        # /email runs carry a block the plain-run renderer knows nothing about —
        # and it's the part you actually come back for: who got the email.
        email = record.get("email") or {}
        if email:
            sent = email.get("sent") or []
            failed = email.get("failed") or []
            total = email.get("recipients", len(sent) + len(failed))
            if not sent and not failed:
                line = f"Drafted but never sent — {total} recipient(s) were lined up."
            else:
                line = f"Sent to {len(sent)} of {total} recipient(s)."
                if failed:
                    line += f" {len(failed)} failed."
            parts.append(
                f"<table width='100%' cellspacing='0' cellpadding='10'>"
                f"<tr><td bgcolor='{theme.ACCENT_RAMP[100]}'>"
                f"<b>✉&nbsp; {_esc(email.get('subject', '(no subject)'))}</b><br>"
                f"<span style='color:{theme.NEUTRAL[700]};font-size:12px'>"
                f"{_esc(line)}</span></td></tr></table>")
        parts.append(f"<hr style='height:1px;background:{theme.DIVIDER};border:0'>")

        if not ran:
            parts.append(f"<p style='color:{theme.NEUTRAL[600]}'>This run didn't "
                         f"get as far as a plan — no step was marked needed.</p>")
            return "".join(parts)

        agents = record.get("agents") or {}
        for number, stage in enumerate(ran, start=1):
            _, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))
            url = links.get(stage) or ""
            texts = responses.get(stage) or []
            # Runs saved before the GUI recorded this (and every CLI run) have
            # no agent map — fall back to the stage key rather than a blank.
            ran_by = agents.get(stage) or stage

            parts.append(
                f"<p style='margin:20px 0 2px 0'>"
                f"<span style='font-family:{theme.FONT_HEADING};font-size:20px;"
                f"color:{theme.ACCENT_RAMP[700]}'>{number:02d}</span>"
                f"<span style='font-family:{theme.FONT_HEADING};font-size:18px'>"
                f"&nbsp;&nbsp;{_esc(title)}</span>"
                f"<span style='color:{theme.NEUTRAL[600]};font-size:12px'>"
                f"&nbsp;&nbsp;·&nbsp;&nbsp;{_esc(ran_by)}</span></p>")
            if url:
                parts.append(f"<p style='margin:0 0 8px 0;font-size:12px'>"
                             f"<a href='{_esc(url)}' style='color:"
                             f"{theme.ACCENT_RAMP[700]}'>{_esc(_one_line(url, 70))}"
                             f"</a></p>")

            parts.append(self._sub("What Prism asked"))
            for question in (routing.get(stage) or {}).get("questions") or []:
                parts.append(self._quote(_esc(question), theme.NEUTRAL[100]))

            parts.append(self._sub("What came back"))
            if texts:
                joined = "\n\n———\n\n".join(t for t in texts if t)
                parts.append(self._quote(render_markdown(joined), theme.SURFACE,
                                         raw_html=True)
                             if joined.strip() else self._nothing(url))
            else:
                parts.append(self._nothing(url))

        return "".join(parts)

    @staticmethod
    def _sub(text: str) -> str:
        return (f"<p style='font-family:{theme.FONT_HEADING};font-size:11px;"
                f"color:{theme.NEUTRAL[600]};margin:12px 0 3px 0'>"
                f"{text.upper()}</p>")

    @staticmethod
    def _quote(inner: str, bg: str, raw_html: bool = False) -> str:
        body = inner if raw_html else (
            f"<p style='margin:0;white-space:pre-wrap;color:{theme.NEUTRAL[800]}'>"
            f"{inner}</p>")
        return (f"<table width='100%' cellspacing='0' cellpadding='11' "
                f"style='margin:0 0 4px 0'><tr><td bgcolor='{bg}'>{body}"
                f"</td></tr></table>")

    @staticmethod
    def _nothing(url: str) -> str:
        note = ("Nothing was captured — the step ran, but Prism couldn't read the "
                "answer off the page." if url else "Nothing was captured.")
        return (f"<p style='color:{theme.NEUTRAL[600]};font-style:italic;"
                f"margin:0 0 4px 0'>{note}</p>")


def _esc(text: str) -> str:
    from html import escape
    return escape(str(text))
