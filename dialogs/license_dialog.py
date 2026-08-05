"""The licence screens — activation, and what a customer sees when it ends.

Three states, one dialog, because they are the same screen with different copy
and the customer's way out of all three is the same field:

  · NO LICENCE  first launch. Paste the key we emailed. Nothing else is
                reachable, and there is no trial button — trials are keys we
                issue.
  · ENDED       the trial or subscription is over. Says when, says how to
                carry on, and lets them straight back in with a new key.
  · CHANGE KEY  from Setup → Licence, to move to a paid licence.

Two things this screen must get right, because they decide whether a stuck
customer contacts us or gives up:

  · The way out is always visible. Every state shows the support address, and
    every failure shows the server's own wording rather than a code.
  · It never blocks. Activation is a network call on a worker thread; the
    window stays alive and the button says what it is doing.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

import app_meta
import licensing
import theme
from widgets import icons
from widgets.controls import heading, kicker, meta

# What each entitlement is called in front of a customer. The internal ids
# ("boq") must never reach the screen.
FEATURE_NAMES = {
    "core": "The pipeline — plan a task and run it across your AI tools",
    "boq": "BOQ — bills of quantities from a CAD drawing or a written spec",
    "email": "Email — draft and send from your attached files",
    "reel": "Reel & Studio — rendered video from a script",
    "bom": "BOM & Stock — match a parts list against your inventory",
}


def feature_label(feature: str) -> str:
    return FEATURE_NAMES.get(feature, feature.upper())


def format_key(text: str) -> str:
    """Group as the customer types: PRSM-XXXXX-XXXXX-XXXXX-XXXXX."""
    body = licensing.keyformat.normalise(text)[4:][:20]
    groups = [body[i:i + 5] for i in range(0, len(body), 5)]
    return "-".join(["PRSM"] + [g for g in groups if g]) if body else ""


class _ActivateWorker(QThread):
    """One activation attempt, off the UI thread.

    A corporate proxy can hold a connection for the full timeout, and a frozen
    window during that would read as a crash — which is exactly the moment a
    customer decides the software is broken.
    """

    ok = Signal(object)
    failed = Signal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key

    def run(self):
        try:
            self.ok.emit(licensing.activate(self._key))
        except licensing.ServerError as e:
            # The server writes this as customer-facing copy, so show it as-is.
            self.failed.emit(e.message)
        except licensing.Unreachable:
            self.failed.emit(
                "Couldn't reach the licence server. Check this computer's "
                "internet connection and try again — if you're on a company "
                "network, it may need to allow api.alphakore.in.")
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(f"Something went wrong activating Prism: {e}")


class LicenseDialog(QDialog):
    """Activation. `mode` picks the framing, not the mechanics."""

    def __init__(self, parent=None, mode: str = "activate"):
        super().__init__(parent)
        self.setWindowTitle(f"{app_meta.NAME} — Licence")
        self.setModal(True)
        # Minimum, not resize: the key field has to show all four groups plus
        # the prefix without eliding, and a customer checking a key they were
        # emailed against what they typed cannot do it through an ellipsis.
        self.setMinimumWidth(580)
        self._worker: _ActivateWorker | None = None
        self._state = licensing.state()
        self._mode = mode

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())

        body = QWidget()
        page = QVBoxLayout(body)
        page.setContentsMargins(26, 22, 26, 22)
        page.setSpacing(14)
        page.addWidget(self._explainer())
        page.addLayout(self._key_row())
        page.addWidget(self._message_label())
        page.addWidget(self._support())
        outer.addWidget(body, stretch=1)
        outer.addWidget(self._footer())

        self.key_edit.setFocus()

    # ── chrome ─────────────────────────────────────────────────────────────
    def _header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("licHeader")
        bar.setStyleSheet(f"QFrame#licHeader {{ background: {theme.SURFACE};"
                          f"border-bottom: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(26, 20, 26, 20)
        row.setSpacing(13)

        mark = QLabel()
        mark.setPixmap(icons.logo_pixmap(34))
        mark.setAlignment(Qt.AlignTop)
        row.addWidget(mark)

        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(kicker(app_meta.PUBLISHER, muted=True))
        title.addWidget(heading(self._title(), level=2))
        row.addLayout(title, stretch=1)
        return bar

    def _title(self) -> str:
        if self._mode == "expired":
            return "Your licence has ended"
        if self._mode == "problem":
            return "Prism can't verify your licence"
        if self._mode == "change":
            return "Enter a licence key"
        return f"Activate {app_meta.NAME}"

    def _explainer(self) -> QLabel:
        if self._mode == "problem":
            # NOT "your licence has ended" — the usual causes are a wrong
            # system clock or a licence file that got copied between machines,
            # and telling a paying customer their licence expired sends them
            # chasing the wrong thing.
            text = (self._state.message or
                    "Prism couldn't check this computer's licence.")
            text += ("\n\nThis is usually a wrong date on the computer, or a "
                     "licence copied from another machine. Check the date and "
                     "time, connect to the internet, and restart Prism — or "
                     "paste your key again below.")
        elif self._mode == "expired":
            ended = self._state.license_ends
            when = time.strftime("%d %B %Y", time.localtime(ended)) if ended else ""
            kind = "trial" if self._state.kind == "trial" else "subscription"
            text = (
                f"Your {kind} ended on {when}. "
                if when else f"Your {kind} has ended. ")
            text += (
                "Prism will still open, and everything you've already produced "
                "stays in History — but new runs are paused until it's renewed.\n\n"
                "Get in touch and we'll sort you out, or paste a new key below.")
        elif self._mode == "change":
            text = ("Paste the new key. It replaces the one on this computer — "
                    "your settings, favourites and history are untouched.")
        else:
            text = (f"{app_meta.NAME} runs on a licence key. Paste the one we "
                    "emailed you below.\n\n"
                    "Don't have one yet? Get in touch and we'll set up a trial.")
        label = QLabel(text)
        label.setObjectName("body")
        label.setWordWrap(True)
        return label

    def _key_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(9)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("PRSM-XXXXX-XXXXX-XXXXX-XXXXX")
        self.key_edit.setMaxLength(29)
        font = QFont(theme.FONT_BODY, 13)
        # Fixed pitch so the four groups line up as they are typed; a key read
        # aloud over the phone is much easier to check against a steady grid.
        font.setStyleHint(QFont.Monospace)
        self.key_edit.setFont(font)
        self.key_edit.textChanged.connect(self._on_typed)
        self.key_edit.returnPressed.connect(self._activate)
        row.addWidget(self.key_edit, stretch=1)

        self.activate_btn = QPushButton(" Activate")
        self.activate_btn.setObjectName("primaryBtn")
        self.activate_btn.setCursor(Qt.PointingHandCursor)
        self.activate_btn.setDefault(True)
        self.activate_btn.setEnabled(False)
        icons.button_icon(self.activate_btn, "check", 15, theme.BG)
        self.activate_btn.clicked.connect(self._activate)
        row.addWidget(self.activate_btn)
        return row

    def _message_label(self) -> QLabel:
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        return self.message

    def _support(self) -> QWidget:
        wrap = QFrame()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("mail", 15, theme.NEUTRAL[600]))
        row.addWidget(glyph)
        link = QPushButton(app_meta.SUPPORT_EMAIL)
        link.setObjectName("linkBtn")
        link.setCursor(Qt.PointingHandCursor)
        link.clicked.connect(self._email_us)
        row.addWidget(link)
        row.addWidget(meta("· we usually reply the same working day"), stretch=1)
        return wrap

    def _footer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("licFooter")
        bar.setStyleSheet(f"QFrame#licFooter {{ background: {theme.SURFACE};"
                          f"border-top: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(26, 13, 26, 13)
        row.setSpacing(9)

        self.device_label = meta(f"This computer: {licensing.device_fingerprint()}")
        self.device_label.setToolTip(
            "Your licence is tied to this computer. Quote this code if you "
            "ever need us to free up a seat.")
        row.addWidget(self.device_label, stretch=1)

        # An expired licence still opens the app; a never-activated one has
        # nothing to fall back to, so its only other exit is to quit.
        if self._mode in ("expired", "problem"):
            later = QPushButton("Continue without it")
            later.setToolTip("Prism opens read-only: History and Setup work, "
                             "new runs don't.")
            later.clicked.connect(self.reject)
        elif self._mode == "change":
            later = QPushButton("Cancel")
            later.clicked.connect(self.reject)
        else:
            later = QPushButton("Quit")
            later.clicked.connect(self.reject)
        later.setCursor(Qt.PointingHandCursor)
        row.addWidget(later)
        return bar

    # ── behaviour ──────────────────────────────────────────────────────────
    def _on_typed(self, raw: str):
        formatted = format_key(raw)
        if formatted != raw:
            self.key_edit.blockSignals(True)
            self.key_edit.setText(formatted)
            self.key_edit.setCursorPosition(len(formatted))
            self.key_edit.blockSignals(False)
        # The checksum catches a typo here, offline, before we spend a network
        # round trip and a rate-limit slot on it.
        self.activate_btn.setEnabled(licensing.keyformat.is_well_formed(formatted))
        self.message.setVisible(False)

    def _say(self, text: str, ok: bool = False):
        self.message.setText(text)
        self.message.setStyleSheet(
            f"color: {theme.ACCENT_RAMP[800] if ok else '#8a2f2f'}; font-size: 13px;")
        self.message.setVisible(True)

    def _busy(self, on: bool):
        self.activate_btn.setEnabled(not on)
        self.activate_btn.setText(" Checking…" if on else " Activate")
        self.key_edit.setEnabled(not on)

    def _activate(self):
        if not self.activate_btn.isEnabled():
            return
        self._busy(True)
        self.message.setVisible(False)
        self._worker = _ActivateWorker(self.key_edit.text(), self)
        self._worker.ok.connect(self._on_activated)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_activated(self, state):
        self._busy(False)
        names = ", ".join(sorted(state.features))
        self._say(f"Activated for {state.customer or 'you'} — {names}. "
                  f"{max(state.days_left, 0)} days remaining.", ok=True)
        self.accept()

    def _on_failed(self, message: str):
        self._busy(False)
        self._say(message)

    def _email_us(self):
        from urllib.parse import quote
        subject = quote(f"{app_meta.NAME} licence — {self._mode}")
        # Pre-fill what we would otherwise have to ask for in the first reply.
        body = quote(
            f"(Please keep the details below — they tell us which licence and "
            f"machine to look at.)\n\n"
            f"Version: {app_meta.VERSION}\n"
            f"Computer: {licensing.device_fingerprint()}\n"
            f"Licence: {self._state.license_id or 'not activated'}\n")
        QDesktopServices.openUrl(
            f"mailto:{app_meta.SUPPORT_EMAIL}?subject={subject}&body={body}")

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
