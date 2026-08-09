"""What a customer sees when they open an add-on their licence doesn't include.

This is a sales surface, not an error. Someone clicking "BOQ" has just told us
they want BOQ, which is the most useful thing they can tell us — so the sheet
names what it does, says plainly that it isn't included, and puts one click
between them and an email to us.

Deliberately not a QMessageBox: "Access denied" with a warning triangle reads
as a fault in the software. The item stays clickable in the rail for the same
reason — a greyed-out row sells nothing.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

import app_meta
import licensing
import theme
from widgets import icons
from widgets.controls import heading, kicker, meta

# One line on what each add-on is FOR — the pitch, not the mechanism.
#
# The words come from plans.py so that a feature is described identically
# wherever the customer meets it: here, in Setup's "Included" list, in the
# guide, and on whatever page eventually sells it. The icon is the only thing
# this file still owns, because only the UI cares.
import plans

_ICONS = {
    "core": "grid", "marketing": "image", "leads": "user", "boq": "file",
    "bom": "list", "attendance": "clock", "reel": "video", "email": "mail",
    "dev": "code",
}

PITCH = {key: (f.label, _ICONS.get(key, "grid"), f.pitch or f.blurb)
         for key, f in plans.FEATURES.items()}


class PaywallDialog(QDialog):
    def __init__(self, feature: str, parent=None, state=None):
        super().__init__(parent)
        name, icon_name, pitch = PITCH.get(
            feature, (feature.upper(), "grid", ""))
        self.feature = feature
        self.state = state or licensing.state()
        self.relaunch_license = False

        self.setWindowTitle(f"{name} — {app_meta.NAME}")
        self.setModal(True)
        self.setMinimumWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 24, 26, 20)
        outer.setSpacing(15)

        head = QHBoxLayout()
        head.setSpacing(12)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 26, theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        head.addWidget(glyph)
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(kicker("Add-on", muted=True))
        title.addWidget(heading(name))
        head.addLayout(title, stretch=1)
        outer.addLayout(head)

        if pitch:
            blurb = QLabel(pitch)
            blurb.setObjectName("body")
            blurb.setWordWrap(True)
            outer.addWidget(blurb)

        outer.addWidget(self._status())
        outer.addLayout(self._buttons())

    def _status(self) -> QFrame:
        """Why it is locked. The wording has to distinguish 'you never bought
        this' from 'your licence lapsed' — they need different actions, and
        telling a paying customer to buy something they already own is the
        fastest way to lose them."""
        box = QFrame()
        # Scoped by object name: QLabel subclasses QFrame, so an unscoped
        # QFrame rule draws this border around the text inside the box too and
        # the explanation ends up looking like an input field.
        box.setObjectName("paywallStatus")
        box.setStyleSheet(
            f"QFrame#paywallStatus {{ background: {theme.NEUTRAL[100]};"
            f"border: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(box)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("lock", 16, theme.NEUTRAL[600]))
        glyph.setAlignment(Qt.AlignTop)
        row.addWidget(glyph)

        if self.state.status == licensing.NONE:
            text = ("Prism isn't activated on this computer yet. Enter your "
                    "licence key to unlock what you've bought.")
        elif not self.state.usable:
            text = ("Your licence has ended, so every add-on is paused. "
                    "Renewing switches them all back on.")
        else:
            included = ", ".join(sorted(self.state.features)) or "nothing yet"
            text = (f"This isn't part of your current licence "
                    f"({self.state.plan or 'your plan'} — includes {included}). "
                    f"We can add it to your existing licence; you won't need to "
                    f"reinstall anything.")
        label = QLabel(text)
        label.setObjectName("body")
        label.setWordWrap(True)
        row.addWidget(label, stretch=1)
        return box

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(meta("Licence " + (self.state.license_id or "—")), stretch=1)

        key_btn = QPushButton(" Enter a key")
        key_btn.setObjectName("smallBtn")
        key_btn.setCursor(Qt.PointingHandCursor)
        icons.button_icon(key_btn, "key", 14, theme.TEXT)
        key_btn.clicked.connect(self._enter_key)
        row.addWidget(key_btn)

        close = QPushButton("Not now")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        row.addWidget(close)

        ask = QPushButton(" Ask us about it")
        ask.setObjectName("primaryBtn")
        ask.setCursor(Qt.PointingHandCursor)
        ask.setDefault(True)
        icons.button_icon(ask, "mail", 15, theme.BG)
        ask.clicked.connect(self._email_us)
        row.addWidget(ask)
        return row

    def _enter_key(self):
        # Handled by the caller so the licence dialog is parented to the window
        # rather than to a sheet that is about to close.
        self.relaunch_license = True
        self.accept()

    def _email_us(self):
        from urllib.parse import quote
        name = PITCH.get(self.feature, (self.feature,))[0]
        subject = quote(f"{app_meta.NAME} — adding {name}")
        body = quote(
            f"Hello,\n\nI'd like to add {name} to our Prism licence.\n\n"
            f"(Details for support:)\n"
            f"Licence: {self.state.license_id or 'not activated'}\n"
            f"Plan: {self.state.plan or '—'}\n"
            f"Computer: {licensing.device_fingerprint()}\n"
            f"Version: {app_meta.VERSION}\n")
        QDesktopServices.openUrl(
            f"mailto:{app_meta.SUPPORT_EMAIL}?subject={subject}&body={body}")
        self.accept()
