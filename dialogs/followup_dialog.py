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

from PySide6.QtWidgets import QFileDialog, QLabel, QTextEdit

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C


class FollowupDialog(PrismDialog):
    """Post-completion refinement. Read submitted()/followup_text()/file_paths()
    after exec()."""

    def __init__(self, result_summary: str = "", parent=None):
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

        if result_summary:
            recap = QTextEdit()
            recap.setReadOnly(True)
            recap.setPlainText(result_summary)
            recap.setFixedHeight(150)
            root.addWidget(QLabel(i18n.t("What came back")))
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
