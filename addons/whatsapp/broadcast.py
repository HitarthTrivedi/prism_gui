"""The Broadcasts tab — one approved template, to a chosen audience, tracked.

Three ideas make it hard to get wrong:

  · The audience is BUILT, not typed. Pick tags (or a saved segment) and the
    exact number of people it reaches is on screen — recounted a moment after
    every change — before anything is sent. Opted-out contacts are never in it.
  · Sending asks first. A broadcast cannot be recalled, so the last click is a
    confirmation that says what will go, to how many.
  · History shows what actually happened: sent, failed, and how far along.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QCompleter, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

import core_bridge as CB
import i18n
import theme
from addons.whatsapp.chat import short_time
from addons.whatsapp.workers import (AudiencePreviewWorker, BroadcastSendWorker,
                                     CampaignsLoadWorker, SegmentDeleteWorker,
                                     SegmentSaveWorker, SegmentsLoadWorker,
                                     TagsLoadWorker)
from widgets import controls as C

_LANGS = (("en_US", "English (US)"), ("en", "English"), ("hi", "Hindi"),
          ("gu", "Gujarati"), ("mr", "Marathi"), ("ta", "Tamil"), ("bn", "Bengali"))
_EVERYONE = "__everyone__"


def _card(title: str, sub: str = "") -> tuple:
    """A glass card with a heading; returns (card, body layout)."""
    card = C.Card()
    col = card.body((theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5), theme.SPACE_3)
    col.addWidget(C.label(title, level="CARD_TITLE"))
    if sub:
        col.addWidget(C.label(sub, level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
    return card, col


class _CampaignRow(QFrame):
    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("waCampaign")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#waCampaign {{ background: rgba(255,255,255,0.55);"
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
        total = int(row.get("total") or 0)
        sent = int(row.get("sent") or 0)
        failed = int(row.get("failed") or 0)
        status = (row.get("status") or "").lower()
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(C.label(row.get("template_name") or i18n.t("Untitled"),
                              level="SUPPORT", weight=700), stretch=1)
        tone = {"done": "ok", "sending": "info", "failed": "err"}.get(status, "quiet")
        label = {"done": i18n.t("Sent"), "sending": i18n.t("Sending"),
                 "failed": i18n.t("Failed")}.get(status, status.capitalize() or "—")
        top.addWidget(C.Pill(label, tone))
        col.addLayout(top)
        who = row.get("segment_name") or i18n.t("Everyone opted in")
        when = short_time(row.get("created_at", ""))
        col.addWidget(C.label(f"{who}  ·  {when}" if when else who, level="META",
                              colour=theme.NEUTRAL[600]))
        col.addWidget(C.ProgressBar((sent + failed) / total if total else 0.0,
                                    hue=theme.OK if not failed else theme.WARN))
        line = i18n.t("{s} sent").format(s=sent)
        if failed:
            line += i18n.t("  ·  {f} failed").format(f=failed)
        line += i18n.t("  ·  {t} total").format(t=total)
        col.addWidget(C.label(line, level="META", colour=theme.NEUTRAL[600]))


class BroadcastPage(QWidget):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._tags: list = []
        self._segments: list = []
        self._audience: list = []
        self._audience_token = 0
        self._tag_buttons: dict = {}
        self._loaded = False
        self._sending = False

        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        root.setSpacing(theme.SPACE_4)

        # ── left: compose + audience + send ──────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.viewport().setAutoFillBackground(False)
        left_host = QWidget()
        left_host.setStyleSheet("background: transparent;")
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, theme.SPACE_2, 0)
        left.setSpacing(theme.SPACE_4)
        left_scroll.setWidget(left_host)
        left_col = QVBoxLayout()
        left_col.setSpacing(theme.SPACE_3)
        left_col.addWidget(left_scroll, stretch=1)
        root.addLayout(left_col, stretch=3)

        card, col = _card(i18n.t("1 · Message"),
                          i18n.t("WhatsApp only lets a business start a conversation with an "
                                 "approved template. Enter the name exactly as it appears in "
                                 "your Meta template manager."))
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText(i18n.t("e.g. diwali_offer"))
        self.template_edit.setMinimumHeight(38)
        recents = list((self.cfg.get("whatsapp") or {}).get("recent_templates") or [])
        if recents:
            comp = QCompleter(recents, self.template_edit)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            self.template_edit.setCompleter(comp)
        self.template_edit.textChanged.connect(lambda _t: self._update_send())
        col.addWidget(self._field(i18n.t("Template name"), self.template_edit))
        self.lang = QComboBox()
        for code, name in _LANGS:
            self.lang.addItem(name, code)
        self.lang.setMinimumHeight(38)
        col.addWidget(self._field(i18n.t("Language"), self.lang))
        left.addWidget(card)

        card, col = _card(i18n.t("2 · Audience"),
                          i18n.t("Everyone who is opted in, or narrow it by tag. "
                                 "Opted-out contacts are never included."))
        seg_row = QHBoxLayout()
        seg_row.setSpacing(theme.SPACE_2)
        self.segment_box = QComboBox()
        self.segment_box.setMinimumHeight(38)
        self.segment_box.currentIndexChanged.connect(self._on_segment)
        seg_row.addWidget(self.segment_box, stretch=1)
        self.save_seg_btn = C.button(i18n.t("Save as segment"), "secondary", small=True,
                                     on_click=self._save_segment)
        seg_row.addWidget(self.save_seg_btn)
        self.del_seg_btn = C.button(i18n.t("Delete"), "tertiary", small=True,
                                    on_click=self._delete_segment)
        seg_row.addWidget(self.del_seg_btn)
        col.addWidget(self._field(i18n.t("Saved segment"), seg_row))
        self.tags_holder = QWidget()
        self.tags_flow = C.FlowLayout(self.tags_holder, h_space=6, v_space=6)
        col.addWidget(self._field(i18n.t("Tags (match any)"), self.tags_holder))
        self.no_tags = C.label(i18n.t("No tags yet — add tags to contacts and they'll appear here."),
                               level="META", colour=theme.NEUTRAL[500])
        col.addWidget(self.no_tags)
        col.addWidget(C.hairline())
        self.count_label = C.label("", level="SECTION", weight=700)
        col.addWidget(self.count_label)
        self.names_label = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        col.addWidget(self.names_label)
        left.addWidget(card)

        send_card = C.Card()
        sc = send_card.body((theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4),
                            theme.SPACE_2)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        sc.addWidget(self.status)
        self.send_btn = C.button(i18n.t("Send broadcast"), "primary", on_click=self._confirm_send)
        sc.addWidget(self.send_btn)
        left.addStretch(1)
        left_col.addWidget(send_card)

        # ── right: history ──────────────────────────────────────────────────
        hist, hcol = _card(i18n.t("Past broadcasts"))
        self.hist_scroll = QScrollArea()
        self.hist_scroll.setWidgetResizable(True)
        self.hist_scroll.setFrameShape(QFrame.NoFrame)
        self.hist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hist_scroll.viewport().setAutoFillBackground(False)
        self.hist_host = QWidget()
        self.hist_host.setStyleSheet("background: transparent;")
        self.hist_col = QVBoxLayout(self.hist_host)
        self.hist_col.setContentsMargins(0, 0, 0, 0)
        self.hist_col.setSpacing(theme.SPACE_2)
        self.hist_scroll.setWidget(self.hist_host)
        hcol.addWidget(self.hist_scroll, stretch=1)
        hist.setMinimumWidth(320)
        root.addWidget(hist, stretch=2)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._preview)
        self._rebuild_segments()
        self._set_count(None)
        self._update_send()

    def _field(self, label: str, content) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(C.label(label.upper(), level="LABEL", colour=theme.NEUTRAL[500]))
        if isinstance(content, QHBoxLayout):
            col.addLayout(content)
        else:
            col.addWidget(content)
        return box

    # ── loading ──────────────────────────────────────────────────────────────
    def activate(self):
        for cls, done, attr in ((TagsLoadWorker, self._on_tags, "_w_tags"),
                                (SegmentsLoadWorker, self._on_segments, "_w_segs"),
                                (CampaignsLoadWorker, self._on_campaigns, "_w_camps")):
            w = cls()
            w.done.connect(done)
            w.failed.connect(self._on_load_failed)
            setattr(self, attr, w)
            w.start()
        if not self._loaded:
            self._loaded = True
            self._preview()

    def _on_load_failed(self, error: str):
        self._say(i18n.t("Couldn't load some data — {e}").format(e=error), "err")

    def _on_tags(self, tags: list):
        self._tags = list(tags or [])
        checked = set(self._checked())
        for btn in self._tag_buttons.values():
            btn.setParent(None)
            btn.deleteLater()
        self._tag_buttons = {}
        while self.tags_flow.count():
            self.tags_flow.takeAt(0)
        for tag in self._tags:
            btn = QPushButton(tag)
            btn.setObjectName("chipBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(tag in checked)
            btn.toggled.connect(lambda _c: self._changed())
            self.tags_flow.addWidget(btn)
            self._tag_buttons[tag] = btn
        self.no_tags.setVisible(not self._tags)
        self.tags_holder.setVisible(bool(self._tags))

    def _on_segments(self, rows: list):
        self._segments = list(rows or [])
        self._rebuild_segments()

    def _rebuild_segments(self, select: str = ""):
        self.segment_box.blockSignals(True)
        self.segment_box.clear()
        self.segment_box.addItem(i18n.t("Everyone opted in"), _EVERYONE)
        for seg in getattr(self, "_segments", []):
            self.segment_box.addItem(seg.get("name", ""), seg.get("id"))
        idx = self.segment_box.findText(select) if select else 0
        self.segment_box.setCurrentIndex(max(0, idx))
        self.segment_box.blockSignals(False)
        self.del_seg_btn.setEnabled(self.segment_box.currentData() != _EVERYONE)

    def _on_campaigns(self, rows: list):
        while self.hist_col.count():
            widget = self.hist_col.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not rows:
            empty = C.label(i18n.t("Nothing sent yet. Your broadcasts will be listed here "
                                   "with how many were delivered."), level="SUPPORT",
                            colour=theme.NEUTRAL[600], wrap=True)
            self.hist_col.addWidget(empty)
        for r in rows:
            self.hist_col.addWidget(_CampaignRow(r))
        self.hist_col.addStretch(1)

    # ── audience ─────────────────────────────────────────────────────────────
    def _checked(self) -> list:
        return [t for t, b in self._tag_buttons.items() if b.isChecked()]

    def _on_segment(self, _index: int):
        data = self.segment_box.currentData()
        self.del_seg_btn.setEnabled(data != _EVERYONE)
        tags = set()
        if data != _EVERYONE:
            seg = next((s for s in self._segments if s.get("id") == data), {})
            tags = set((seg.get("filter") or {}).get("tags") or [])
        for tag, btn in self._tag_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(tag in tags)
            btn.blockSignals(False)
        self._changed()

    def _changed(self):
        self._set_count(None)
        self._preview_timer.start()

    def _preview(self):
        self._audience_token += 1
        token = self._audience_token
        w = AudiencePreviewWorker(self._checked())
        w.done.connect(lambda rows, t=token: self._on_audience(rows, t))
        w.failed.connect(lambda e, t=token: self._on_audience_failed(e, t))
        self._w_aud = w
        w.start()

    def _on_audience(self, rows: list, token: int):
        if token != self._audience_token:
            return                              # a newer selection superseded this one
        self._audience = rows or []
        self._set_count(len(self._audience))

    def _on_audience_failed(self, error: str, token: int):
        if token != self._audience_token:
            return
        self._audience = []
        self._update_send()
        self.count_label.setText(i18n.t("Couldn't count the audience"))
        self.names_label.setText(error)

    def _set_count(self, n):
        if n is None:
            self.count_label.setText(i18n.t("Counting…"))
            self.names_label.setText("")
            self.send_btn.setEnabled(False)
            return
        if n == 0:
            self.count_label.setText(i18n.t("No one matches"))
            self.names_label.setText(i18n.t("Pick different tags, or everyone who is opted in."))
        else:
            self.count_label.setText(i18n.t("{n} people will receive this").format(n=n))
            names = [(r.get("name") or r.get("phone") or "") for r in self._audience[:6]]
            more = n - len(names)
            self.names_label.setText(", ".join(names) + (i18n.t(" and {m} more").format(m=more)
                                                         if more > 0 else ""))
        self._update_send()

    def _update_send(self):
        ok = bool(self.template_edit.text().strip()) and bool(self._audience) and not self._sending
        self.send_btn.setEnabled(ok)
        if self._audience and not self.template_edit.text().strip():
            self._say(i18n.t("Enter the template name to continue."), "muted")
        elif ok:
            self._say("", "muted")
        self.send_btn.setText(i18n.t("Send to {n} people").format(n=len(self._audience))
                              if self._audience else i18n.t("Send broadcast"))

    def _say(self, text: str, tone: str):
        colour = {"err": theme.ERR_INK, "ok": theme.OK_INK}.get(tone, theme.NEUTRAL[600])
        self.status.setStyleSheet(f"color: {colour};")
        self.status.setText(text)

    # ── segments ─────────────────────────────────────────────────────────────
    def _save_segment(self):
        tags = self._checked()
        name, ok = QInputDialog.getText(self, i18n.t("Save as segment"),
                                        i18n.t("Name this segment:"))
        if not ok or not name.strip():
            return
        w = SegmentSaveWorker(name.strip(), tags)
        w.done.connect(lambda _r, n=name.strip(): self._segment_saved(n))
        w.failed.connect(lambda e: self._say(i18n.t("Couldn't save the segment — {e}").format(e=e), "err"))
        self._w_seg_save = w
        w.start()

    def _segment_saved(self, name: str):
        w = SegmentsLoadWorker()
        w.done.connect(lambda rows, n=name: (self._on_segments(rows), self._select_segment(n)))
        w.failed.connect(self._on_load_failed)
        self._w_segs = w
        w.start()

    def _select_segment(self, name: str):
        idx = self.segment_box.findText(name)
        if idx >= 0:
            self.segment_box.setCurrentIndex(idx)

    def _delete_segment(self):
        sid = self.segment_box.currentData()
        if sid == _EVERYONE:
            return
        name = self.segment_box.currentText()
        if QMessageBox.question(
                self, i18n.t("Delete segment?"),
                i18n.t("Delete “{n}”? Contacts and their tags are not affected.").format(n=name),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        w = SegmentDeleteWorker(sid)
        w.done.connect(self.activate)
        w.failed.connect(lambda e: self._say(i18n.t("Couldn't delete — {e}").format(e=e), "err"))
        self._w_seg_del = w
        w.start()

    # ── sending ──────────────────────────────────────────────────────────────
    def _confirm_send(self):
        template = self.template_edit.text().strip()
        n = len(self._audience)
        if not template or not n:
            return
        if QMessageBox.question(
                self, i18n.t("Send this broadcast?"),
                i18n.t("Send the template “{t}” to {n} people?\n\nThis can't be recalled "
                       "once it starts. Opted-out contacts are skipped.").format(t=template, n=n),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        seg = ""
        if self.segment_box.currentData() != _EVERYONE:
            seg = self.segment_box.currentText()
        self._sending = True
        self.send_btn.setEnabled(False)
        self.send_btn.setText(i18n.t("Sending…"))
        self._say("", "muted")
        w = BroadcastSendWorker(template_name=template, language=self.lang.currentData(),
                                tags=self._checked(), segment_name=seg)
        w.done.connect(lambda res, t=template: self._sent(res, t))
        w.failed.connect(self._send_failed)
        self._w_send = w
        w.start()

    def _sent(self, result: dict, template: str):
        self._sending = False
        n = (result or {}).get("audience_size", 0)
        self._remember(template)
        self._update_send()
        self._say(i18n.t("Sent to {n} people. Delivery is tracked below.").format(n=n), "ok")
        self.activate()

    def _send_failed(self, error: str):
        self._sending = False
        self._update_send()
        self._say(i18n.t("Couldn't send — {e}").format(e=error), "err")

    def _remember(self, template: str):
        block = dict(self.cfg.get("whatsapp") or {})
        recents = [t for t in block.get("recent_templates", []) if t != template]
        block["recent_templates"] = ([template] + recents)[:8]
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception:                                   # noqa: BLE001
            pass
