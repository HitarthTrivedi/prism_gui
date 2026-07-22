"""Shown once the run finishes: what each step produced, with an Open button
per step so the user opens only the ones they actually need instead of
scrolling through everything."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QFrame, QApplication, QDialogButtonBox,
)

import theme
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import Chip, heading
from widgets.markdown import render_markdown


class StageResultDialog(QDialog):
    """One step's full output, popped out into its own window."""

    def __init__(self, stage: str, agent: str, text: str, url: str, parent=None,
                 unfinished: bool = False):
        super().__init__(parent)
        _, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))
        self.setWindowTitle(f"{title} · {agent}")
        self.resize(680, 520)
        root = QVBoxLayout(self)
        root.setSpacing(11)
        root.addWidget(heading(title))
        if url:
            # When Prism didn't get the text, this link is the whole result —
            # the tool keeps working in that tab after we stop watching.
            label = (f"The result is still being made in {agent} — open it"
                     if unfinished else f"Open in {agent}")
            link = QLabel(f'<a href="{url}" style="color:{theme.ACCENT_RAMP[700]}">'
                          f'{label}</a>')
            link.setOpenExternalLinks(True)
            root.addWidget(link)
        body = QTextEdit()
        body.setReadOnly(True)
        if text:
            body.setHtml(render_markdown(text))
        elif url:
            body.setPlainText(
                "No text was captured here — the link above is where this step "
                "landed, and it is the one to open.")
        else:
            body.setPlainText("(no response text captured)")
        root.addWidget(body)
        row = QHBoxLayout()
        copy_btn = QPushButton(" Copy")
        copy_btn.setObjectName("smallBtn")
        icons.button_icon(copy_btn, "copy", 14, theme.TEXT)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(text or body.toPlainText()))
        row.addWidget(copy_btn)
        row.addStretch(1)
        root.addLayout(row)


class _StageRow(QFrame):
    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(12)

        stage = info["stage"]
        icon_name, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))
        ok = info.get("ok", True)
        url = info.get("url", "")
        # Either the wait cap expired or the step broke — in both cases the tool
        # may still deliver at its link, so the row says "still going", not
        # "done", and never "failed" without offering that link.
        unfinished = bool(info.get("timed_out")) or (not ok and bool(url))

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 18, theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        row.addWidget(glyph)

        text = QVBoxLayout()
        text.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(title)
        name.setObjectName("h5")
        head.addWidget(name)
        tool = QLabel(info["agent"])
        tool.setObjectName("tagNeutral")
        head.addWidget(tool)
        if info.get("timed_out"):
            head.addWidget(Chip("still generating", "clock", "tagWarn"))
        elif not ok and url:
            # It broke on our side but the tab lives on — "failed" alone would
            # send the user away from a page that may still deliver.
            head.addWidget(Chip("failed · link kept", "alert", "tagWarn"))
        else:
            head.addWidget(Chip("done" if ok else "failed",
                                "check" if ok else "alert",
                                "tagOk" if ok else "tagErr"))
        head.addStretch(1)
        text.addLayout(head)
        snippet = QLabel(info.get("snippet", ""))
        snippet.setObjectName("meta")
        snippet.setWordWrap(True)
        text.addWidget(snippet)
        row.addLayout(text, stretch=1)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("smallBtn")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(lambda: StageResultDialog(
            stage, info["agent"], info.get("text", ""), url,
            self.window(), unfinished).exec())
        row.addWidget(open_btn)


class CompletionDialog(QDialog):
    def __init__(self, stage_infos: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("All done")
        self.resize(620, 460)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(13)

        head = QHBoxLayout()
        head.setSpacing(9)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("check", 20, theme.ACCENT))
        head.addWidget(mark)
        head.addWidget(heading("Prism finished the work"), stretch=1)
        root.addLayout(head)

        pending = [i for i in stage_infos
                   if i.get("timed_out") or (not i.get("ok", True) and i.get("url"))]
        sub = QLabel(
            "Here's what each step produced — open only the ones you need."
            if not pending else
            f"Here's what each step produced. {len(pending)} of them ran past "
            "Prism's wait — their tools are still working, so open those links "
            "to collect the finished result.")
        sub.setObjectName("meta")
        sub.setWordWrap(True)
        root.addWidget(sub)

        for info in stage_infos:
            root.addWidget(_StageRow(info))
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        root.addWidget(buttons)
