"""The only way Prism tells someone something went wrong.

A QMessageBox with a technical string in it is a phone call. This is the
replacement: what happened, what to do about it as numbered steps, and — where
Prism can do something for them — a button that goes straight there.

Three deliberate choices:

  · The steps are the point, so they get the visual weight, not the error.
  · The technical detail is present but folded away. A business owner does not
    want it; the person they forward the screenshot to does.
  · "Save diagnostics" only appears when contacting us is genuinely the next
    step. Offering it every time trains people to send a file instead of
    reading the fix.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

import friendly
import i18n
import theme
from widgets import icons
from widgets.controls import heading, meta


class ProblemDialog(QDialog):
    """Shows a friendly.Problem. `chosen_action` is the action key the user
    pressed, or "" — the caller decides what to do with it, because only the
    window knows how to open its own Settings."""

    def __init__(self, problem: friendly.Problem, detail: str = "", parent=None):
        super().__init__(parent)
        self.problem = problem
        self.chosen_action = ""
        self._detail = detail or ""
        self.setWindowTitle(i18n.t("Prism"))
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(16)

        # ── what happened ──────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(13)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("alert", 24, "#8a5a2f"))
        glyph.setAlignment(Qt.AlignTop)
        head.addWidget(glyph)

        titles = QVBoxLayout()
        titles.setSpacing(6)
        titles.addWidget(heading(problem.title))
        what = QLabel(problem.what)
        what.setWordWrap(True)
        what.setStyleSheet(f"color: {theme.NEUTRAL[700]}; font-size: 14px;")
        titles.addWidget(what)
        head.addLayout(titles, stretch=1)
        root.addLayout(head)

        # ── what to do ─────────────────────────────────────────────────
        if problem.steps:
            box = QFrame()
            box.setObjectName("stepsBox")
            box.setStyleSheet(
                f"QFrame#stepsBox {{ background: {theme.ACCENT_RAMP[100]};"
                f"border: 1px solid {theme.DIVIDER}; border-radius: 4px; }}")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(18, 15, 18, 15)
            inner.setSpacing(9)
            inner.addWidget(_kicker(i18n.t("Try this")))
            for index, step in enumerate(problem.steps, 1):
                inner.addWidget(_Step(index, step))
            root.addWidget(box)

        # ── the technical detail, folded away ──────────────────────────
        if self._detail:
            self._detail_label = QLabel(self._detail)
            self._detail_label.setWordWrap(True)
            self._detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._detail_label.setStyleSheet(
                f"color: {theme.NEUTRAL[600]}; font-size: 11.5px;"
                f"font-family: monospace;")
            self._detail_label.setVisible(False)
            self._toggle = QPushButton(i18n.t("Show technical details"))
            self._toggle.setObjectName("linkBtn")
            self._toggle.setCursor(Qt.PointingHandCursor)
            self._toggle.setFlat(True)
            self._toggle.setStyleSheet(
                f"text-align: left; border: none; color: {theme.NEUTRAL[600]};"
                f"font-size: 12px; padding: 0;")
            self._toggle.clicked.connect(self._toggle_detail)
            root.addWidget(self._toggle, alignment=Qt.AlignLeft)
            root.addWidget(self._detail_label)

        # ── the way out ────────────────────────────────────────────────
        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        if problem.ask_support:
            save = QPushButton(i18n.t(" Save details to send us"))
            save.setObjectName("smallBtn")
            save.setCursor(Qt.PointingHandCursor)
            save.setToolTip(i18n.t(
                "Writes a file describing what happened. Your API key, "
                "passwords and licence key are not in it."))
            icons.button_icon(save, "file", 14, theme.TEXT)
            save.clicked.connect(self._save_diagnostics)
            buttons.addWidget(save)
        buttons.addStretch(1)

        if problem.action:
            go = QPushButton(i18n.t(problem.action_label or "Fix this"))
            go.setObjectName("primaryBtn")
            go.setCursor(Qt.PointingHandCursor)
            go.setMinimumHeight(38)
            go.clicked.connect(self._take_action)
            buttons.addWidget(go)
            close = QPushButton(i18n.t("Not now"))
        else:
            close = QPushButton(i18n.t("OK"))
            close.setObjectName("primaryBtn")
            close.setMinimumHeight(38)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    # ── behaviour ──────────────────────────────────────────────────────
    def _toggle_detail(self):
        showing = not self._detail_label.isVisible()
        self._detail_label.setVisible(showing)
        self._toggle.setText(i18n.t("Hide technical details") if showing
                             else i18n.t("Show technical details"))
        self.adjustSize()

    def _take_action(self):
        self.chosen_action = self.problem.action
        self.accept()

    def _save_diagnostics(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import os
        import time

        import diagnostics
        suggested = os.path.join(
            os.path.expanduser("~"),
            f"prism-problem-{time.strftime('%Y%m%d-%H%M')}.txt")
        target, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save details"), suggested, "Text (*.txt)")
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(friendly.as_text(self.problem))
                f.write("\n\n" + "=" * 60 + "\n\n")
                if self._detail:
                    f.write(f"Technical detail:\n{self._detail}\n\n")
                f.write(diagnostics.report())
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, i18n.t("Prism"), i18n.t(
                "Couldn't write the file: {error}").format(error=e))
            return
        QMessageBox.information(self, i18n.t("Prism"), i18n.t(
            "Saved to {path}\n\nEmail it to us and we'll be able to see "
            "exactly what happened.").format(path=target))


class _Step(QWidget):
    """One numbered instruction. The number is a real column so the wrapped
    text lines up under itself rather than under the digit."""

    def __init__(self, index: int, text: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        number = QLabel(str(index))
        number.setFixedWidth(18)
        number.setAlignment(Qt.AlignTop | Qt.AlignRight)
        number.setStyleSheet(
            f"color: {theme.ACCENT_RAMP[700]}; font-weight: 700; "
            f"font-size: 13.5px;")
        row.addWidget(number)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {theme.NEUTRAL[800]}; font-size: 13.5px;")
        row.addWidget(body, stretch=1)


def _kicker(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setStyleSheet(
        f"color: {theme.ACCENT_RAMP[800]}; font-size: 10.5px; "
        f"font-weight: 700; letter-spacing: 1.2px;")
    return label


def show_problem(parent, error: object, context: str = "") -> str:
    """Explain an error and show it. Returns the action key the user chose.

    The one call every error site should make. Also logs the real error, so
    the friendly version on screen never costs us the technical one.
    """
    try:
        import diagnostics
        diagnostics.write("ERROR", f"[{context or 'general'}] {error}")
    except Exception:                                   # noqa: BLE001
        pass
    problem = friendly.explain(error, context)
    dialog = ProblemDialog(problem, detail=str(error), parent=parent)
    dialog.exec()
    return dialog.chosen_action
