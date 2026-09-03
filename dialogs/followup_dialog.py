"""Follow up — the refinement step after a whole task has finished.

When a task completes, Prism offers this: read the result, then either accept
it and be done, or type a change and (optionally) add or swap files, and Prism
sends that follow-up to whichever step's assigned agent it is actually about —
worked out automatically, not picked by hand. The re-done result comes back and
this can offer another follow-up, so it is a refinement loop, not a one-shot.

Closing with the X is "I'm done" — an accidental close should never start
another run.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QTextEdit,
                               QWidget)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C


class FollowupDialog(PrismDialog):
    """Post-completion refinement. Read submitted()/followup_text()/file_paths()
    after exec()."""

    def __init__(self, result_summary: str = "", parent=None,
                 artifacts: list[str] | None = None):
        super().__init__(
            i18n.t("Anything to change?"),
            i18n.t("The task is done. Tell Prism what to adjust and it will "
                   "send your note to the right step — or close this if it's "
                   "good."),
            icon="check", parent=parent, closable=True)
        self.setWindowTitle("Follow up")
        self.resize(640, 560)
        self.setMinimumSize(500, 420)
        self._submitted = False
        self._paths: list[str] = []

        root = self.body

        # What THIS task actually produced — the files, shown first, because for
        # an agentic step the deliverable IS the file (the BOQ PDF, the doc, the
        # images); the chat holds only process notes. A person opens the file to
        # judge the result, so it leads, and the text recap sits under it.
        artifacts = [p for p in (artifacts or []) if p
                     and not p.endswith(".link.txt") and os.path.isfile(p)]
        if artifacts:
            root.addWidget(QLabel(i18n.t("What Prism produced")))
            for path in artifacts:
                root.addWidget(self._artifact_row(path))

        if result_summary:
            recap = QTextEdit()
            recap.setReadOnly(True)
            recap.setPlainText(result_summary)
            recap.setFixedHeight(120 if artifacts else 150)
            root.addWidget(QLabel(i18n.t("Notes from the run")
                                  if artifacts else i18n.t("What came back")))
            root.addWidget(recap)

        root.addWidget(QLabel(i18n.t("Your follow-up")))
        self._note = QTextEdit()
        self._note.setPlaceholderText(
            i18n.t("e.g. make the images brighter · shorten the post · use the "
                   "new brochure I'm attaching…"))
        root.addWidget(self._note, stretch=1)

        # Attachments to fold into the follow-up.
        self._files_label = QLabel("")
        self._files_label.setObjectName("meta")
        self._files_label.setWordWrap(True)
        self._files_label.setVisible(False)
        root.addWidget(self._files_label)

        self.footer.add_utility(
            self.button(i18n.t("Add files"), icon_name="paperclip",
                        on_click=self._add_files))
        self.footer.add_secondary(
            self.button(i18n.t("No, I'm done"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Send follow-up"), "primary",
                        icon_name="arrow-up", on_click=self._send))

    # ── result ───────────────────────────────────────────────────────────
    def submitted(self) -> bool:
        return self._submitted

    def followup_text(self) -> str:
        return self._note.toPlainText().strip()

    def file_paths(self) -> list[str]:
        return list(self._paths)

    # ── returned media ────────────────────────────────────────────────────
    def _artifact_row(self, path: str) -> QWidget:
        """One produced file: its name (with a size hint) and an Open button
        that hands it to the OS — the person judges the deliverable by opening
        it, so opening is one click, not a hunt through the Artifacts folder."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        name = os.path.basename(path)
        try:
            kb = os.path.getsize(path) / 1024
            size = f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
        except OSError:
            size = ""
        label = QLabel(f"{name}  ·  {size}" if size else name)
        label.setObjectName("meta")
        label.setWordWrap(True)
        lay.addWidget(label, stretch=1)

        lay.addWidget(self.button(
            i18n.t("Open"), icon_name="external", small=True,
            on_click=lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.abspath(path)))))
        return row

    # ── actions ──────────────────────────────────────────────────────────
    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, i18n.t("Add files"))
        for p in paths:
            if p and p not in self._paths:
                self._paths.append(p)
        if self._paths:
            names = ", ".join(os.path.basename(p) for p in self._paths)
            self._files_label.setText(
                i18n.t("Attaching: {names}").format(names=names))
            self._files_label.setVisible(True)

    def _send(self):
        if not self.followup_text() and not self._paths:
            self._note.setFocus()
            self._note.setStyleSheet(f"border: 1px solid {theme.ERR_INK};")
            return
        self._submitted = True
        self.accept()
