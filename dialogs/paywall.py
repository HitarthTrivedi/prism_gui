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
import i18n
import licensing
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
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


class PaywallDialog(PrismDialog):
    def __init__(self, feature: str, parent=None, state=None):
        name, icon_name, pitch = PITCH.get(
            feature, (feature.upper(), "grid", ""))
        self.feature = feature
        self.state = state or licensing.state()
        self.relaunch_license = False

        super().__init__(name, parent=parent, icon=icon_name,
                         eyebrow=i18n.t("Add-on"), closable=False)
        self.setWindowTitle(f"{name} — {app_meta.NAME}")
        self.setModal(True)
        self.setMinimumWidth(520)
        # Stacked sheet, not a card grid — see the licence dialog.
        self.body.setSpacing(theme.ROW_GAP)

        if pitch:
            blurb = QLabel(pitch)
            blurb.setObjectName("body")
            blurb.setWordWrap(True)
            self.body.addWidget(blurb)

        self.body.addWidget(self._status())
        already = self._already_have()
        if already is not None:
            self.body.addWidget(already)
        self.body.addStretch(1)
        self._build_footer()

    def _already_have(self) -> QFrame | None:
        """What this licence DOES cover, under the thing it does not.

        The one fact worth adding to a locked screen: somebody who has already
        paid for three of five add-ons is a very different conversation from
        somebody who has bought nothing, and both are looking at this window.
        Real data only — the signed token's own feature list — so a licence
        with nothing on it draws nothing.
        """
        have = sorted(f for f in (self.state.features or [])
                      if f != self.feature)
        if not have or not self.state.usable:
            return None
        wrap = QFrame()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        from dialogs.license_dialog import feature_chips
        col.addWidget(kicker(i18n.t("Already on your licence"), muted=True))
        col.addWidget(feature_chips(have, "ok"))
        return wrap

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
        box.setAttribute(Qt.WA_StyledBackground, True)
        # WELL and a hairline, not NEUTRAL[100] and a DIVIDER: this is an inset
        # panel inside a card surface, and the census found three near-
        # identical greys doing that job across the dialogs. One well, one
        # hairline, one radius.
        box.setStyleSheet(
            f"QFrame#paywallStatus {{ background: {theme.WELL};"
            f" border: 1px solid {theme.HAIRLINE};"
            f" border-radius: {theme.R_CONTROL}px; }}")
        row = QHBoxLayout(box)
        row.setContentsMargins(theme.SPACE_3, theme.SPACE_3,
                               theme.SPACE_3, theme.SPACE_3)
        row.setSpacing(theme.SPACE_3)
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

    def _build_footer(self):
        licence = meta("Licence " + (self.state.license_id or "—"))
        licence.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.footer.add_note(licence)
        self.footer.add_utility(
            self.button(i18n.t("Enter a key"), "secondary", icon_name="key",
                        small=True, on_click=self._enter_key))
        self.footer.add_secondary(
            self.button(i18n.t("Not now"), on_click=self.reject))
        # The one primary, and it is deliberately the sales action rather than
        # "Enter a key": somebody who lands here has just told us they want
        # this add-on, which is the most useful thing they can tell us.
        self.footer.set_primary(
            self.button(i18n.t("Ask us about it"), "primary", icon_name="mail",
                        on_click=self._email_us))

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
