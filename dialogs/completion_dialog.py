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

    def __init__(self, stage: str, agent: str, text: str, url: str, parent=None):
        super().__init__(parent)
        _, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))
        self.setWindowTitle(f"{title} · {agent}")
        self.resize(680, 520)
        root = QVBoxLayout(self)
        root.setSpacing(11)
        root.addWidget(heading(title))
        if url:
            link = QLabel(f'<a href="{url}" style="color:{theme.ACCENT_RAMP[700]}">'
                          f'Open in {agent}</a>')
            link.setOpenExternalLinks(True)
            root.addWidget(link)
        body = QTextEdit()
        body.setReadOnly(True)
        if text:
            body.setHtml(render_markdown(text))
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
            stage, info["agent"], info.get("text", ""), info.get("url", ""),
            self.window()).exec())
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

        sub = QLabel("Here's what each step produced — open only the ones you need.")
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
