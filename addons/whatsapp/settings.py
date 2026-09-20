"""The Settings tab — is it connected, your number's credentials, a test send.

Inbox, Contacts and Broadcasts need nothing configured here: they go through
Prism's licence server, which already knows which seat is calling. What is left
is small and honest:

  · Connection — a live check that your data is reachable, with the real error
    when it is not, instead of a screen that silently shows nothing.
  · Your WhatsApp number — the Cloud API phone-number ID and token, used ONLY
    by the manual test send below. Stored on this computer.
  · Send a test message — straight to Meta, outside the CRM; not logged and not
    part of any conversation. For checking a number works, not for customers.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPlainTextEdit, QScrollArea,
                               QVBoxLayout, QWidget)

import core_bridge as CB
import i18n
import theme
from addons.whatsapp import demo
from addons.whatsapp.workers import TagsLoadWorker, WhatsAppSendWorker
from widgets import controls as C


class SettingsPage(QWidget):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        wa = self.cfg.get("whatsapp") or {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        scroll.setWidget(host)
        page = QHBoxLayout(host)
        page.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        col = QVBoxLayout()
        col.setSpacing(theme.SPACE_4)
        page.addStretch(1)
        page.addLayout(col, stretch=0)
        page.addStretch(1)

        # ── connection ───────────────────────────────────────────────────────
        card = C.Card()
        card.setFixedWidth(680)
        cc = card.body((theme.SPACE_5,) * 4, theme.SPACE_3)
        head = QHBoxLayout()
        head.addWidget(C.label(i18n.t("Connection"), level="CARD_TITLE"), stretch=1)
        self.conn_pill = C.Pill(i18n.t("Checking…"), "quiet")
        head.addWidget(self.conn_pill)
        cc.addLayout(head)
        self.conn_text = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        cc.addWidget(self.conn_text)
        row = QHBoxLayout()
        row.addWidget(C.button(i18n.t("Check again"), "secondary", small=True,
                               on_click=self.check))
        row.addStretch(1)
        cc.addLayout(row)
        col.addWidget(card)

        # ── your number ──────────────────────────────────────────────────────
        card = C.Card()
        card.setFixedWidth(680)
        cc = card.body((theme.SPACE_5,) * 4, theme.SPACE_3)
        head = QHBoxLayout()
        head.addWidget(C.label(i18n.t("Your WhatsApp number"), level="CARD_TITLE"), stretch=1)
        self.number_pill = C.Pill("", "quiet")
        head.addWidget(self.number_pill)
        cc.addLayout(head)
        cc.addWidget(C.label(
            i18n.t("Only the test message below uses these. They're kept on this "
                   "computer and sent to nobody but Meta."),
            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.pnid_edit = QLineEdit(wa.get("phone_number_id", ""))
        self.pnid_edit.setPlaceholderText(i18n.t("From Meta: WhatsApp, then API Setup"))
        self.pnid_edit.setMinimumHeight(38)
        cc.addWidget(self._field(i18n.t("Phone number ID"), self.pnid_edit))
        self.token_edit = QLineEdit(wa.get("token", ""))
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText(i18n.t("Access token"))
        self.token_edit.setMinimumHeight(38)
        cc.addWidget(self._field(i18n.t("Access token"), self.token_edit))
        row = QHBoxLayout()
        self.save_status = QLabel("")
        row.addWidget(self.save_status, stretch=1)
        row.addWidget(C.button(i18n.t("Save"), "secondary", small=True, icon_name="check",
                               on_click=self._save))
        cc.addLayout(row)
        col.addWidget(card)
        self._set_number_pill()

        # ── test message ─────────────────────────────────────────────────────
        card = C.Card()
        card.setFixedWidth(680)
        cc = card.body((theme.SPACE_5,) * 4, theme.SPACE_3)
        cc.addWidget(C.label(i18n.t("Send a test message"), level="CARD_TITLE"))
        cc.addWidget(C.label(
            i18n.t("Straight to Meta, outside the CRM — it isn't logged and isn't part of "
                   "any conversation. A plain message only reaches someone who wrote to "
                   "you in the last 24 hours."),
            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.to_edit = QLineEdit(wa.get("last_to", ""))
        self.to_edit.setPlaceholderText(i18n.t("Full number with country code, e.g. 919812345678"))
        self.to_edit.setMinimumHeight(38)
        cc.addWidget(self._field(i18n.t("To"), self.to_edit))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText(i18n.t("Your message"))
        self.body_edit.setFixedHeight(84)
        cc.addWidget(self._field(i18n.t("Message"), self.body_edit))
        row = QHBoxLayout()
        self.send_status = QLabel("")
        self.send_status.setWordWrap(True)
        row.addWidget(self.send_status, stretch=1)
        self.send_btn = C.button(i18n.t("Send test message"), "primary", on_click=self._send)
        row.addWidget(self.send_btn)
        cc.addLayout(row)
        self.log = QListWidget()
        self.log.setFrameShape(QFrame.NoFrame)
        self.log.setMaximumHeight(110)
        self.log.setStyleSheet("QListWidget { background: transparent; }")
        cc.addWidget(self.log)
        col.addWidget(card)
        col.addStretch(1)

    def _field(self, label: str, widget) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(C.label(label.upper(), level="LABEL", colour=theme.NEUTRAL[500]))
        lay.addWidget(widget)
        return box

    # ── connection ───────────────────────────────────────────────────────────
    def activate(self):
        self.check()

    def check(self):
        self.conn_pill.setText(i18n.t("Checking…"))
        self.conn_pill.set_tone("quiet")
        self.conn_text.setText("")
        w = TagsLoadWorker()
        w.done.connect(self._connected)
        w.failed.connect(self._not_connected)
        self._w = w
        w.start()

    def _connected(self, _tags):
        self.conn_pill.setText(i18n.t("Connected"))
        self.conn_pill.set_tone("ok")
        if demo.enabled():
            self.conn_pill.setText(i18n.t("Demo data"))
            self.conn_pill.set_tone("warn")
            self.conn_text.setText(i18n.t(
                "You're looking at sample conversations for design and testing — nothing here "
                "is real, and nothing you do is sent."))
        else:
            self.conn_text.setText(i18n.t(
                "Your inbox, contacts and broadcasts are reaching Prism's licence server, "
                "and it can reach your WhatsApp data."))

    def _not_connected(self, error: str):
        self.conn_pill.setText(i18n.t("Not connected"))
        self.conn_pill.set_tone("err")
        self.conn_text.setText(error)

    # ── credentials ──────────────────────────────────────────────────────────
    def _set_number_pill(self):
        ok = bool(self.pnid_edit.text().strip() and self.token_edit.text().strip())
        self.number_pill.setText(i18n.t("Set") if ok else i18n.t("Not set"))
        self.number_pill.set_tone("ok" if ok else "quiet")

    def _save(self):
        block = dict(self.cfg.get("whatsapp") or {})
        block["phone_number_id"] = self.pnid_edit.text().strip()
        block["token"] = self.token_edit.text().strip()
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception as e:                              # noqa: BLE001
            self.save_status.setStyleSheet(f"color: {theme.ERR_INK};")
            self.save_status.setText(i18n.t("Couldn't save: {e}").format(e=e))
            return
        self.save_status.setStyleSheet(f"color: {theme.OK_INK};")
        self.save_status.setText(i18n.t("Saved."))
        self._set_number_pill()

    # ── test send ────────────────────────────────────────────────────────────
    def _send(self):
        pnid = self.pnid_edit.text().strip()
        token = self.token_edit.text().strip()
        to = self.to_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        if not pnid or not token:
            self._say(i18n.t("Add your phone number ID and access token above first."), "err")
            return
        if not to or not body:
            self._say(i18n.t("Enter a recipient number and a message."), "err")
            return
        block = dict(self.cfg.get("whatsapp") or {})
        block["last_to"] = to
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception:                                   # noqa: BLE001
            pass
        self.send_btn.setEnabled(False)
        self._say(i18n.t("Sending…"), "muted")
        w = WhatsAppSendWorker(pnid, token, to, body)
        w.done.connect(lambda wamid, t=to: self._sent(t, wamid))
        w.failed.connect(lambda e, t=to: self._failed(t, e))
        self._send_worker = w
        w.start()

    def _sent(self, to: str, wamid: str):
        self.send_btn.setEnabled(True)
        self._say(i18n.t("Sent."), "ok")
        self.log.insertItem(0, "%s  to %s  ok  %s" % (
            datetime.now().strftime("%I:%M %p").lstrip("0"), to, wamid))

    def _failed(self, to: str, error: str):
        self.send_btn.setEnabled(True)
        self._say(i18n.t("Failed: {e}").format(e=error), "err")
        self.log.insertItem(0, "%s  to %s  FAILED  %s" % (
            datetime.now().strftime("%I:%M %p").lstrip("0"), to, error))

    def _say(self, text: str, tone: str):
        colour = {"err": theme.ERR_INK, "ok": theme.OK_INK}.get(tone, theme.NEUTRAL[600])
        self.send_status.setStyleSheet(f"color: {colour};")
        self.send_status.setText(text)
