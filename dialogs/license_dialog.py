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
import i18n
import licensing
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from widgets.controls import heading, kicker, meta

# What each entitlement is called in front of a customer. The internal ids
# ("boq") must never reach the screen.
# Kept as a name for compatibility, but the content now lives in plans.py so
# the paywall, Setup's "Included" list, the guide and whatever mints the keys
# all describe a feature the same way.
import plans

FEATURE_NAMES = {key: f"{f.label} — {f.blurb}" for key, f in plans.FEATURES.items()}


def feature_label(feature: str) -> str:
    return FEATURE_NAMES.get(feature, feature.upper())


def short_feature_label(feature: str) -> str:
    """Just the name, for a chip. "BOQ", not "BOQ — Bills of Quantities".

    plans.py writes each label as name-plus-gloss because that is the right
    length for a list with room to breathe. In a row of chips it is the wrong
    length twice over: it clips, and five of them read as five sentences.
    """
    entry = plans.FEATURES.get(feature)
    if entry is None:
        return feature.upper()
    return entry.label.split("—")[0].strip() or entry.label


def feature_chips(features, tone: str = "ok"):
    """A reflowing row of feature pills. Used by the licence sheet and the
    paywall, so "what you have" looks the same in both.

    Each pill rides in its own cell with a trailing stretch: a Pill is
    fixed-size and a grid cell is not, so without the stretch every chip
    floats in the middle of its column and five of them read as a ragged
    scatter rather than a list.
    """
    grid = C.CardGrid(min_col_width=132, gap=theme.SPACE_1 + 2)
    cells = []
    for key in features:
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(C.Pill(short_feature_label(key), tone))
        row.addStretch(1)
        cells.append(cell)
    grid.add_all(cells)
    return grid


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
            # Name the server this build actually talks to. Hardcoding a
            # hostname here once sent a real diagnosis down the wrong path —
            # the address was fine and the request was simply timing out.
            host = licensing.client.server_url()
            self.failed.emit(
                f"Couldn't reach the licence server at {host}. Check this "
                "computer's internet connection and try again — if you're on "
                "a company network, it may need to allow that address.")
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(f"Something went wrong activating Prism: {e}")


class LicenseDialog(PrismDialog):
    """Activation. `mode` picks the framing, not the mechanics."""

    def __init__(self, parent=None, mode: str = "activate"):
        self._state = licensing.state()
        self._mode = mode
        mark = QLabel()
        mark.setPixmap(icons.logo_pixmap(34))
        mark.setAlignment(Qt.AlignTop)
        # No close X. Every one of the three modes already carries its own
        # named way out in the footer — Quit, Continue without it, Cancel —
        # and those three do different things. A generic X beside them would
        # be a fourth exit whose meaning a customer has to guess at exactly
        # the moment they are least willing to guess.
        super().__init__(self._title(), self._lede(), parent=parent,
                         leading=mark, eyebrow=app_meta.PUBLISHER,
                         closable=False)
        self.setWindowTitle(f"{app_meta.NAME} — Licence")
        self.setModal(True)
        # Minimum, not resize: the key field has to show all four groups plus
        # the prefix without eliding, and a customer checking a key they were
        # emailed against what they typed cannot do it through an ellipsis.
        self.setMinimumWidth(580)
        self._worker: _ActivateWorker | None = None

        # A stacked sheet, not a grid of cards: the 16px card gutter between
        # five single-column elements is what left a third of this small window
        # reading as bare canvas.
        self.body.setSpacing(theme.ROW_GAP)
        self.body.addWidget(self._explainer())
        self.body.addLayout(self._key_row())
        self.body.addWidget(self._message_label())
        self.body.addWidget(self._support())
        unlocked = self._unlocked()
        if unlocked is not None:
            self.body.addWidget(unlocked)
        self.body.addStretch(1)
        self._build_footer()

        self.key_edit.setFocus()
        self.tab_chain(self.key_edit, self.activate_btn)

    # ── chrome ─────────────────────────────────────────────────────────────
    def _lede(self) -> str:
        """One line under the title, saying what this window wants.

        The explainer paragraph below spells out the situation; this is the
        half-second version, and it is what stops the header reading as a
        bare error banner.
        """
        if self._mode == "problem":
            return i18n.t("Check the date on this computer, then paste your "
                          "key again.")
        if self._mode == "expired":
            return i18n.t("Paste a renewed key to switch new runs back on.")
        if self._mode == "change":
            return i18n.t("The new key replaces the one on this computer.")
        return i18n.t("Paste the key we emailed you to switch Prism on.")

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
        row.setSpacing(theme.SPACE_2)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("PRSM-XXXXX-XXXXX-XXXXX-XXXXX")
        self.key_edit.setAccessibleName(i18n.t("Licence key"))
        self.key_edit.setMaxLength(29)
        self.key_edit.setMinimumHeight(C.MIN_TARGET + 10)
        font = QFont(theme.FONT_BODY, 13)
        # Fixed pitch so the four groups line up as they are typed; a key read
        # aloud over the phone is much easier to check against a steady grid.
        font.setStyleHint(QFont.Monospace)
        self.key_edit.setFont(font)
        self.key_edit.textChanged.connect(self._on_typed)
        self.key_edit.returnPressed.connect(self._activate)
        row.addWidget(self.key_edit, stretch=1)

        # The one primary on this surface, and it sits beside the field it
        # acts on rather than in the footer — the footer's job here is the way
        # OUT (Quit / Continue without it / Cancel), and putting the way in and
        # the way out shoulder to shoulder is how somebody quits by accident.
        self.activate_btn = C.button(i18n.t(" Activate"), "primary", "check",
                                     on_click=self._activate)
        self.activate_btn.setDefault(True)
        self.activate_btn.setEnabled(False)
        self.activate_btn.setMinimumHeight(C.MIN_TARGET + 10)
        row.addWidget(self.activate_btn)
        return row

    def _message_label(self) -> QLabel:
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        return self.message

    def _support(self) -> QWidget:
        """The way out, always on screen.

        Boxed rather than left as a bare line: this is the one thing on the
        screen a stuck customer needs to see, and an unstyled email address
        under a form is the easiest thing on any page to skip past.
        """
        wrap = QFrame()
        wrap.setObjectName("licSupport")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        wrap.setStyleSheet(
            f"#licSupport {{ background: {theme.WELL};"
            f" border: 1px solid {theme.HAIRLINE};"
            f" border-radius: {theme.R_CONTROL}px; }}")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(theme.SPACE_3, theme.SPACE_2,
                               theme.SPACE_3, theme.SPACE_2)
        row.setSpacing(theme.SPACE_2)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("mail", 15, theme.NEUTRAL[600]))
        row.addWidget(glyph)
        row.addWidget(meta(i18n.t("Stuck? Write to us —")))
        link = QPushButton(app_meta.SUPPORT_EMAIL)
        link.setObjectName("linkBtn")
        link.setCursor(Qt.PointingHandCursor)
        link.setMinimumHeight(C.MIN_TARGET)
        link.clicked.connect(self._email_us)
        row.addWidget(link)
        row.addWidget(meta("· we usually reply the same working day"), stretch=1)
        return wrap

    def _unlocked(self) -> QWidget | None:
        """What the key on this licence already covers.

        Only drawn when there is a real answer. On first activation there is no
        licence to read yet, so nothing is shown rather than a guess at what
        the customer bought — the whole point of the feature list is that the
        signed token says what it says.
        """
        features = sorted(getattr(self._state, "features", None) or [])
        if not features or self._mode == "activate":
            return None
        wrap = QFrame()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        col.addWidget(kicker(i18n.t("This licence covers"), muted=True))
        col.addWidget(feature_chips(
            features, "ok" if self._state.usable else "neutral"))
        return wrap

    def _build_footer(self):
        self.device_label = meta(f"This computer: {licensing.device_fingerprint()}")
        self.device_label.setToolTip(
            "Your licence is tied to this computer. Quote this code if you "
            "ever need us to free up a seat.")
        self.device_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.footer.add_note(self.device_label)

        # An expired licence still opens the app; a never-activated one has
        # nothing to fall back to, so its only other exit is to quit. All three
        # are secondaries — Activate, next to the key field, is this window's
        # one primary.
        if self._mode in ("expired", "problem"):
            later = self.button(
                i18n.t("Continue without it"), on_click=self.reject,
                tooltip="Prism opens read-only: History and Setup work, "
                        "new runs don't.")
        elif self._mode == "change":
            later = self.button(i18n.t("Cancel"), on_click=self.reject)
        else:
            later = self.button(i18n.t("Quit"), on_click=self.reject)
        self.footer.add_secondary(later)

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
        """The server's own answer, in the semantic tone that matches it.

        Success used to render in accent blue, which rotates with the role —
        in a green profile "Activated" and "That key is not valid" came out in
        neighbouring hues. Both tones are now the semantic ones, which never
        rotate, and both sit on their own tint so the result is a block rather
        than a stray sentence under a form.
        """
        ink = theme.OK_INK if ok else theme.ERR_INK
        tint = theme.OK_BG if ok else theme.ERR_BG
        self.message.setText(text)
        self.message.setStyleSheet(
            f"color: {ink}; background: {tint};"
            f" border: 1px solid {theme.OK if ok else theme.ERR_LINE};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
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
