"""WhatsApp — Prism's window onto the CRM n8n runs.

Plan B, as it actually landed: n8n (on its own always-on host) is the whole
WhatsApp engine — it holds the Meta credentials, receives every inbound
message, runs the AI qualification and the conversation bot, and is the one
place that ever calls Meta's Graph API. Everything it does lands in
Supabase. This window is Prism's answer to "what is happening on WhatsApp
right now, and let me act on it" — not a second engine.

Every read and every send in Inbox, Contacts and Broadcast goes through
Prism's own licence server (addons.whatsapp.license_client), which holds the
Supabase service_role key and the n8n webhook URLs so this machine never has
to. There is nothing to "connect" here any more — a seat that can open this
add-on at all can already do everything below, because the server rechecks
the same licence and feature on every call.

Four tabs, in the order a day's work touches them:

  · Inbox     — every conversation, as an actual chat: an avatar-led
                conversation list and a message-bubble thread, the shape
                WhatsApp Web and every CRM built on top of it already taught
                people to read. Reply, and n8n sends it and logs it (never
                Meta directly from here — see license_client.py).
  · Contacts  — the same table, searchable; the one write Prism ever made to
                Supabase itself is a contact's opt-out flag, because it never
                sends anything.
  · Send      — the original one-off Cloud API sender (addons.whatsapp.
                cloud_api), kept for a manual test message outside the CRM —
                the one place this add-on still holds a Meta credential
                directly, entered per machine in Settings.
  · Settings  — the WhatsApp number's own Cloud API credentials, for Send
                only.

Every network call — the licence server, or Meta for the Send tab — runs off
the UI thread through addons.whatsapp.workers, never inline here.

Sizing rule that matters more than it looks: every tab's fixed-action row
(Refresh, the composer, Save/Send) is a plain, non-stretched widget added
AFTER the one stretchy element in its column — never inside something that
can grow past the window. A tab whose content might still outgrow a small
screen is wrapped in its own QScrollArea, so the fallback is a scrollbar,
never a button nobody can reach.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QScrollArea, QSizePolicy, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from addons.whatsapp.workers import (
    AudiencePreviewWorker, BroadcastSendWorker, CampaignsLoadWorker,
    ContactOptOutWorker, ContactsLoadWorker, ContactTagsSaveWorker,
    ConversationsLoadWorker, ReplySendWorker, SegmentDeleteWorker,
    SegmentSaveWorker, SegmentsLoadWorker, TagsLoadWorker, ThreadLoadWorker,
    WhatsAppSendWorker,
)
from dialogs.base import PrismDialog
from widgets import controls as C

_INBOX, _CONTACTS, _SEND, _BROADCAST, _SETTINGS = range(5)


# ── small chat-shaped widgets ────────────────────────────────────────────────

class _ConvoRow(QFrame):
    """One row in the conversation list: avatar, name, last message, time —
    the row shape WhatsApp Web, Intercom and every inbox built since have all
    converged on, because it answers "who, said what, how long ago" without a
    click."""

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("waConvoRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#waConvoRow {{ background: transparent; border-radius: {theme.R_CONTROL}px; }}")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                                 theme.SPACE_2, theme.SPACE_2)
        outer.setSpacing(theme.SPACE_3)

        who = row.get("contact_name") or row.get("contact_phone") or i18n.t("Unknown")
        hue = theme.WARN if row.get("opt_out") else theme.OK
        outer.addWidget(C.Avatar(who, 36, hue), alignment=Qt.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.label(who, level="SUPPORT", weight=600), stretch=1)
        if row.get("opt_out"):
            top.addWidget(C.Pill(i18n.t("opted out"), "warn"))
        col.addLayout(top)
        preview = (row.get("last_text") or "").strip().splitlines()
        preview = preview[0] if preview else i18n.t("No messages yet.")
        prefix = i18n.t("You: ") if row.get("last_direction") == "out" else ""
        line = C.label(prefix + preview, level="META", colour=theme.NEUTRAL[600])
        line.setWordWrap(False)
        col.addWidget(line)
        outer.addLayout(col, stretch=1)


class _MessageBubble(QFrame):
    """One message, aligned by who sent it — the other half of the same
    pattern: outbound tinted and right-aligned, inbound on the card colour
    and left-aligned, exactly what WhatsApp itself trained everyone to read
    as "mine" vs "theirs" without a label."""

    def __init__(self, text: str, outbound: bool, sender: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("waBubble")
        bg = theme.OK_BG if outbound else theme.CARD
        border = theme.HAIRLINE if not outbound else "transparent"
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#waBubble {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: {theme.R_CARD}px; }}")
        self.setMaximumWidth(420)
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_2,
                               theme.SPACE_3, theme.SPACE_2)
        col.setSpacing(2)
        if sender and not outbound:
            col.addWidget(C.label(sender, level="LABEL", weight=700,
                                  colour=theme.OK_INK))
        body = C.label(text or "", level="BODY", wrap=True)
        col.addWidget(body)


def _bubble_row(text: str, outbound: bool, sender: str = "") -> QWidget:
    """A bubble plus the stretch that pushes it to the right side (outbound)
    or leaves it on the left (inbound)."""
    wrap = QWidget()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    bubble = _MessageBubble(text, outbound, sender)
    if outbound:
        row.addStretch(1)
        row.addWidget(bubble)
    else:
        row.addWidget(bubble)
        row.addStretch(1)
    return wrap


class WhatsAppDialog(PrismDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("WhatsApp"),
            i18n.t("Your team's WhatsApp, run by n8n. This window reads what "
                   "n8n has logged and hands any reply or send back to it — "
                   "nothing here talks to WhatsApp on its own."),
            icon="message", parent=parent)
        self.setWindowTitle("WhatsApp")
        self.setMinimumSize(760, 560)
        self.cfg = cfg if isinstance(cfg, dict) else {}

        self._send_worker = None
        self._convos_worker = None
        self._thread_worker = None
        self._contacts_worker = None
        self._optout_worker = None
        self._reply_worker = None
        self._tags_worker = None
        self._contact_tags_worker = None
        self._segments_worker = None
        self._segment_save_worker = None
        self._segment_delete_worker = None
        self._audience_worker = None
        self._campaigns_worker = None
        self._broadcast_worker = None

        self._conversations: list = []
        self._current_conversation = None      # the selected row, or None
        self._current_contact = None           # the selected row, or None
        self._contacts_loaded = False
        self._segments: list = []
        self._broadcast_loaded = False

        root = self.body
        root.setSpacing(theme.ROW_GAP)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_inbox_tab(), i18n.t("Inbox"))
        self.tabs.addTab(self._build_contacts_tab(), i18n.t("Contacts"))
        self.tabs.addTab(self._build_send_tab(), i18n.t("Send"))
        self.tabs.addTab(self._build_broadcast_tab(), i18n.t("Broadcast"))
        self.tabs.addTab(self._build_settings_tab(), i18n.t("Settings"))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, stretch=1)

        self.footer.add_utility(
            self.button(i18n.t("Save settings"), "secondary",
                        icon_name="check", small=True,
                        on_click=self._save_settings))
        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))

        # Sized last, once every tab's real content exists — a resize() before
        # the layout has anything in it gets overridden by Qt's own sizeHint
        # the moment a tall tab is built, which is what left the composer and
        # the Refresh button below the visible window before this.
        self.resize(1040, 760)

        self._refresh_conversations()

    # ── small builders ────────────────────────────────────────────────────
    def _scrollable(self, inner: QWidget) -> QWidget:
        """Wrap a tab's content in its own scroll area — the fallback for a
        screen too small for everything at once. Every fixed-action widget
        still sits at a knowable place; scrolling is how you reach it on a
        short window, not a redesign of where it lives."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(inner)
        return scroll

    def _card(self, icon: str, title: str, *, pill: C.Pill = None) -> tuple:
        """A Card with a header row (icon + title + optional status pill) and
        its own body column. Returns (card, body_column) — build into the
        column, add the card to the page."""
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_3)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_2)
        head.addWidget(C.IconPad(icon, theme.OK, 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(title, level="CARD_TITLE"), stretch=1)
        if pill is not None:
            head.addWidget(pill)
        col.addLayout(head)
        col.addWidget(C.hairline())
        return card, col

    def _status_pill(self, connected: bool) -> C.Pill:
        return C.Pill(i18n.t("Connected") if connected else i18n.t("Not set"),
                     "ok" if connected else "quiet")

    def _labelled(self, label: str, widget) -> QFrame:
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(C.meta(label))
        box.addWidget(widget)
        holder = QFrame()
        holder.setLayout(box)
        return holder

    # ── Inbox ──────────────────────────────────────────────────────────────
    def _build_inbox_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, theme.SPACE_3, 0, 0)
        outer.setSpacing(0)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # -- left: the conversation list --------------------------------
        self.convo_count_pill = C.Pill("0", "neutral")
        left_card, lcol = self._card("inbox", i18n.t("Conversations"),
                                     pill=self.convo_count_pill)
        self.convo_list = QListWidget()
        self.convo_list.setSpacing(2)
        self.convo_list.setFrameShape(QListWidget.NoFrame)
        self.convo_list.currentRowChanged.connect(self._on_convo_selected)
        lcol.addWidget(self.convo_list, stretch=1)
        refresh_row = QHBoxLayout()
        refresh_row.setContentsMargins(0, 0, 0, 0)
        refresh_row.addWidget(self.button(i18n.t("Refresh"), "secondary",
                                          small=True, icon_name="clock",
                                          on_click=self._refresh_conversations))
        refresh_row.addStretch(1)
        lcol.addLayout(refresh_row)
        left_card.setMinimumWidth(280)
        split.addWidget(left_card)

        # -- right: the thread, as a real chat -----------------------------
        right_card, rcol = self._card("message", i18n.t("Conversation"))
        self.thread_header = C.label(i18n.t("Pick a conversation"),
                                     level="SUPPORT", weight=600)
        rcol.addWidget(self.thread_header)

        self.thread_scroll = QScrollArea()
        self.thread_scroll.setWidgetResizable(True)
        self.thread_scroll.setFrameShape(QScrollArea.NoFrame)
        self._thread_host = QWidget()
        self._thread_col = QVBoxLayout(self._thread_host)
        self._thread_col.setContentsMargins(0, theme.SPACE_2, 0, theme.SPACE_2)
        self._thread_col.setSpacing(theme.SPACE_2)
        self._thread_col.addStretch(1)
        self.thread_scroll.setWidget(self._thread_host)
        rcol.addWidget(self.thread_scroll, stretch=1)

        # The composer: fixed height, added after the one stretchy widget
        # above it, so it never competes for space and never scrolls away.
        composer = QHBoxLayout()
        composer.setContentsMargins(0, 0, 0, 0)
        composer.setSpacing(theme.SPACE_2)
        self.reply_edit = QLineEdit()
        self.reply_edit.setPlaceholderText(
            i18n.t("Type a reply — n8n sends it and logs it"))
        self.reply_edit.returnPressed.connect(self._send_reply)
        self.reply_btn = self.button(i18n.t("Send"), "primary",
                                     icon_name="message",
                                     on_click=self._send_reply)
        composer.addWidget(self.reply_edit, stretch=1)
        composer.addWidget(self.reply_btn)
        rcol.addLayout(composer)
        self.inbox_status = QLabel("")
        self.inbox_status.setWordWrap(True)
        self.inbox_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        rcol.addWidget(self.inbox_status)

        split.addWidget(right_card)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)

        outer.addWidget(split, stretch=1)
        return page

    def _refresh_conversations(self):
        self._convos_worker = ConversationsLoadWorker()
        self._convos_worker.done.connect(self._on_conversations_loaded)
        self._convos_worker.failed.connect(self._on_conversations_failed)
        self._convos_worker.start()

    def _on_conversations_loaded(self, rows: list):
        self._conversations = rows or []
        self.convo_list.clear()
        for row in self._conversations:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row)
            item.setSizeHint(_ConvoRow(row).sizeHint())
            self.convo_list.addItem(item)
            self.convo_list.setItemWidget(item, _ConvoRow(row))
        self.convo_count_pill.setText(str(len(self._conversations)))
        if not self._conversations:
            self.thread_header.setText(i18n.t("No conversations yet."))

    def _on_conversations_failed(self, error: str):
        self.thread_header.setText(
            i18n.t("Couldn't load conversations: {e}").format(e=error))

    def _on_convo_selected(self, index: int):
        if index < 0 or index >= len(self._conversations):
            self._current_conversation = None
            return
        row = self._conversations[index]
        self._current_conversation = row
        who = row.get("contact_name") or row.get("contact_phone") or i18n.t("Unknown")
        self.thread_header.setText(who)
        self._render_thread([], loading=True)
        self._thread_worker = ThreadLoadWorker(row.get("id"))
        self._thread_worker.done.connect(self._on_thread_loaded)
        self._thread_worker.failed.connect(self._on_thread_failed)
        self._thread_worker.start()

    def _clear_thread(self):
        while self._thread_col.count() > 1:      # keep the trailing stretch
            item = self._thread_col.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _render_thread(self, messages: list, *, loading: bool = False,
                       error: str = ""):
        self._clear_thread()
        if loading:
            self._thread_col.insertWidget(0, C.label(i18n.t("Loading…"), level="META"))
            return
        if error:
            self._thread_col.insertWidget(0, C.label(error, level="META",
                                                      colour=theme.ERR_INK, wrap=True))
            return
        if not messages:
            self._thread_col.insertWidget(0, C.label(i18n.t("No messages yet."),
                                                      level="META"))
            return
        for i, m in enumerate(messages):
            outbound = m.get("direction") == "out"
            sender = "" if outbound else (m.get("sender") or "")
            self._thread_col.insertWidget(
                i, _bubble_row(m.get("text", ""), outbound, sender))

    def _on_thread_loaded(self, conversation_id, messages: list):
        if not self._current_conversation or \
                self._current_conversation.get("id") != conversation_id:
            return                                    # selection moved on
        self._render_thread(messages)

    def _on_thread_failed(self, conversation_id, error: str):
        if not self._current_conversation or \
                self._current_conversation.get("id") != conversation_id:
            return
        self._render_thread(
            [], error=i18n.t("Couldn't load this conversation: {e}").format(e=error))

    def _send_reply(self):
        row = self._current_conversation
        if not row:
            self.inbox_status.setText(i18n.t("Pick a conversation first."))
            return
        text = self.reply_edit.text().strip()
        if not text:
            return
        self.reply_btn.setEnabled(False)
        self.inbox_status.setText(i18n.t("Sending…"))
        self._reply_worker = ReplySendWorker(
            phone=row.get("contact_phone", ""), text=text,
            conversation_id=row.get("id", ""), contact_id=row.get("contact_id", ""))
        self._reply_worker.done.connect(lambda _data: self._on_reply_sent(text))
        self._reply_worker.failed.connect(self._on_reply_failed)
        self._reply_worker.start()

    def _on_reply_sent(self, text: str):
        self.reply_btn.setEnabled(True)
        self.reply_edit.clear()
        self.inbox_status.setText(i18n.t("Sent."))
        # Drop the placeholder ("No messages yet." / loading) before the
        # first real bubble ever lands, so the two never stack.
        if self._thread_col.count() == 2 and \
                isinstance(self._thread_col.itemAt(0).widget(), QLabel):
            self._clear_thread()
        self._thread_col.insertWidget(
            max(0, self._thread_col.count() - 1),
            _bubble_row(text, True))

    def _on_reply_failed(self, error: str):
        self.reply_btn.setEnabled(True)
        self.inbox_status.setText(i18n.t("Couldn't send: {e}").format(e=error))

    # ── Contacts ───────────────────────────────────────────────────────────
    def _build_contacts_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, theme.SPACE_3, 0, 0)
        outer.setSpacing(theme.CARD_GAP)

        self.contacts_count_pill = C.Pill("0", "neutral")
        card, col = self._card("user", i18n.t("Contacts"),
                               pill=self.contacts_count_pill)

        self.contact_search = QLineEdit()
        self.contact_search.setPlaceholderText(
            i18n.t("Search by name, phone or email"))
        self.contact_search.returnPressed.connect(self._refresh_contacts)
        col.addWidget(self.contact_search)

        self.contacts_list = QListWidget()
        self.contacts_list.setSpacing(2)
        self.contacts_list.setFrameShape(QListWidget.NoFrame)
        self.contacts_list.currentRowChanged.connect(self._on_contact_selected)
        col.addWidget(self.contacts_list, stretch=1)

        self.contact_tags_label = C.label(i18n.t("Pick a contact to tag it."),
                                          level="META", colour=theme.NEUTRAL[600])
        self.contact_tags_label.setWordWrap(True)
        col.addWidget(self.contact_tags_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(theme.SPACE_2)
        self.optout_btn = self.button(i18n.t("Toggle opt-out"), "secondary",
                                      icon_name="x", on_click=self._toggle_opt_out)
        self.optout_btn.setEnabled(False)
        actions.addWidget(self.optout_btn)
        self.edit_tags_btn = self.button(i18n.t("Edit tags"), "secondary",
                                         icon_name="pencil", on_click=self._edit_tags)
        self.edit_tags_btn.setEnabled(False)
        actions.addWidget(self.edit_tags_btn)
        self.contacts_status = QLabel("")
        self.contacts_status.setWordWrap(True)
        actions.addWidget(self.contacts_status, stretch=1)
        col.addLayout(actions)

        outer.addWidget(card, stretch=1)
        return page

    def _refresh_contacts(self):
        self.contacts_status.setText(i18n.t("Loading…"))
        self._contacts_worker = ContactsLoadWorker(
            search=self.contact_search.text().strip())
        self._contacts_worker.done.connect(self._on_contacts_loaded)
        self._contacts_worker.failed.connect(self._on_contacts_failed)
        self._contacts_worker.start()

    def _on_contacts_loaded(self, rows: list):
        self._contacts_loaded = True
        self.contacts_list.clear()
        for row in rows or []:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row)
            widget = self._contact_row(row)
            item.setSizeHint(widget.sizeHint())
            self.contacts_list.addItem(item)
            self.contacts_list.setItemWidget(item, widget)
        self.contacts_count_pill.setText(str(len(rows or [])))
        self.contacts_status.setText(
            "" if rows else i18n.t("No contacts match."))

    def _contact_row(self, row: dict) -> QWidget:
        frame = QFrame()
        line = QHBoxLayout(frame)
        line.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                                theme.SPACE_2, theme.SPACE_2)
        line.setSpacing(theme.SPACE_3)
        label = row.get("name") or row.get("phone") or i18n.t("Unknown")
        line.addWidget(C.Avatar(label, 32,
                                theme.WARN if row.get("opt_out") else theme.ACCENT))
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addWidget(C.label(label, level="SUPPORT", weight=600))
        sub = row.get("phone") or ""
        tags = [t for t in (row.get("tags") or []) if isinstance(t, str) and t]
        if tags:
            sub = (sub + "  ·  " if sub else "") + ", ".join(tags)
        col.addWidget(C.label(sub, level="META", colour=theme.NEUTRAL[600]))
        line.addLayout(col, stretch=1)
        if row.get("opt_out"):
            line.addWidget(C.Pill(i18n.t("opted out"), "warn"))
        return frame

    def _on_contacts_failed(self, error: str):
        self.contacts_status.setText(
            i18n.t("Couldn't load contacts: {e}").format(e=error))

    def _on_contact_selected(self, index: int):
        self.optout_btn.setEnabled(index >= 0)
        self.edit_tags_btn.setEnabled(index >= 0)
        if index < 0:
            self._current_contact = None
            self.contact_tags_label.setText(i18n.t("Pick a contact to tag it."))
            return
        row = self.contacts_list.item(index).data(Qt.UserRole) or {}
        self._current_contact = row
        tags = [t for t in (row.get("tags") or []) if isinstance(t, str) and t]
        who = row.get("name") or row.get("phone") or i18n.t("Unknown")
        self.contact_tags_label.setText(
            i18n.t("{who} — tags: {tags}").format(
                who=who, tags=", ".join(tags) if tags else i18n.t("none")))

    def _edit_tags(self):
        row = self._current_contact
        if not row:
            return
        current = ", ".join(t for t in (row.get("tags") or []) if isinstance(t, str))
        text, ok = QInputDialog.getText(
            self, i18n.t("Edit tags"),
            i18n.t("Comma-separated, e.g. vip, hot lead"), text=current)
        if not ok:
            return
        tags = [t.strip() for t in text.split(",") if t.strip()]
        self.edit_tags_btn.setEnabled(False)
        self._contact_tags_worker = ContactTagsSaveWorker(row.get("id"), tags)
        self._contact_tags_worker.done.connect(lambda _row: self._refresh_contacts())
        self._contact_tags_worker.failed.connect(self._on_tags_save_failed)
        self._contact_tags_worker.start()

    def _on_tags_save_failed(self, error: str):
        self.edit_tags_btn.setEnabled(True)
        self.contacts_status.setText(i18n.t("Couldn't save tags: {e}").format(e=error))

    def _toggle_opt_out(self):
        item = self.contacts_list.currentItem()
        if item is None:
            return
        row = item.data(Qt.UserRole) or {}
        self.optout_btn.setEnabled(False)
        self._optout_worker = ContactOptOutWorker(
            row.get("id"), not row.get("opt_out"))
        self._optout_worker.done.connect(lambda _row: self._refresh_contacts())
        self._optout_worker.failed.connect(self._on_optout_failed)
        self._optout_worker.start()

    def _on_optout_failed(self, error: str):
        self.optout_btn.setEnabled(True)
        self.contacts_status.setText(
            i18n.t("Couldn't update: {e}").format(e=error))

    # ── Send (the original one-off Cloud API sender) ──────────────────────
    def _build_send_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, theme.SPACE_3, 0, 0)
        root.setSpacing(theme.CARD_GAP)

        card, col = self._card("message", i18n.t("A manual test message"))
        col.addWidget(C.label(
            i18n.t("Outside the CRM, sent straight to Meta — not logged in "
                   "Supabase, not part of any conversation history."),
            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.to_edit = QLineEdit((self.cfg.get("whatsapp") or {}).get("last_to", ""))
        self.to_edit.setPlaceholderText(
            i18n.t("Full number with country code, e.g. 919812345678"))
        col.addWidget(self._labelled(i18n.t("To"), self.to_edit))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText(
            i18n.t("Your message — a plain reply only reaches someone who "
                   "wrote to you in the last 24 hours"))
        self.body_edit.setFixedHeight(70)
        col.addWidget(self._labelled(i18n.t("Message"), self.body_edit))
        self.send_status = QLabel("")
        self.send_status.setWordWrap(True)
        col.addWidget(self.send_status)
        self.send_btn = self.button(i18n.t("Send test message"), "primary",
                                    icon_name="message", on_click=self._send)
        col.addWidget(self.send_btn)
        root.addWidget(card)

        log_card, log_col = self._card("list", i18n.t("Results"))
        self.send_log = QListWidget()
        self.send_log.setFrameShape(QListWidget.NoFrame)
        log_col.addWidget(self.send_log, stretch=1)
        root.addWidget(log_card, stretch=1)
        return page

    def _send(self):
        wa = self.cfg.get("whatsapp") or {}
        pnid, token = (wa.get("phone_number_id") or "").strip(), (wa.get("token") or "").strip()
        to = self.to_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        if not pnid or not token:
            self.send_status.setText(
                i18n.t("Add your phone number ID and access token in Settings first."))
            return
        if not to or not body:
            self.send_status.setText(
                i18n.t("Enter a recipient number and a message."))
            return
        self._save_last_to(to)
        self.send_btn.setEnabled(False)
        self.send_status.setText(i18n.t("Sending…"))
        self._send_worker = WhatsAppSendWorker(pnid, token, to, body)
        self._send_worker.done.connect(self._on_sent)
        self._send_worker.failed.connect(self._on_send_failed)
        self._send_worker.start()

    def _on_sent(self, wamid: str):
        self.send_btn.setEnabled(True)
        self.send_status.setText(i18n.t("Sent. Message id: {id}").format(id=wamid))
        self.send_log.insertItem(0, "→ %s  ok  %s" % (self.to_edit.text().strip(), wamid))

    def _on_send_failed(self, error: str):
        self.send_btn.setEnabled(True)
        self.send_status.setText(i18n.t("Failed: {e}").format(e=error))
        self.send_log.insertItem(0, "→ %s  FAILED  %s" % (self.to_edit.text().strip(), error))

    def _save_last_to(self, to: str):
        block = dict(self.cfg.get("whatsapp") or {})
        block["last_to"] = to
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception:                                # noqa: BLE001
            pass

    # ── Broadcast — compose, pick an audience, send, track ────────────────
    def _build_broadcast_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(0, theme.SPACE_3, theme.SPACE_2, theme.SPACE_3)
        root.setSpacing(theme.CARD_GAP)

        card, col = self._card("message", i18n.t("Compose"))
        col.addWidget(C.label(
            i18n.t("A broadcast always opens with an approved template — "
                   "Meta requires one for any message outside a reply "
                   "window — sent by n8n and logged the same as any other "
                   "send."), level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.broadcast_template_edit = QLineEdit()
        self.broadcast_template_edit.setPlaceholderText(
            i18n.t("Approved template name, e.g. hello_world"))
        col.addWidget(self._labelled(i18n.t("Template name"), self.broadcast_template_edit))
        self.broadcast_lang_edit = QLineEdit("en_US")
        col.addWidget(self._labelled(i18n.t("Language code"), self.broadcast_lang_edit))
        root.addWidget(card)

        self.audience_count_pill = C.Pill("0", "neutral")
        card, col = self._card("user", i18n.t("Audience"),
                               pill=self.audience_count_pill)
        col.addWidget(C.label(
            i18n.t("Opted-in contacts only. Pick tags to narrow it, or leave "
                   "none checked to reach everyone opted in."),
            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.tags_list = QListWidget()
        self.tags_list.setFrameShape(QListWidget.NoFrame)
        self.tags_list.setMaximumHeight(120)
        self.tags_list.itemChanged.connect(lambda _item: self._preview_audience())
        col.addWidget(self.tags_list)

        seg_row = QHBoxLayout()
        seg_row.setContentsMargins(0, 0, 0, 0)
        seg_row.setSpacing(theme.SPACE_2)
        self.segments_list = QListWidget()
        self.segments_list.setFrameShape(QListWidget.NoFrame)
        self.segments_list.setMaximumHeight(90)
        self.segments_list.currentRowChanged.connect(self._on_segment_selected)
        seg_row.addWidget(self.segments_list, stretch=1)
        seg_buttons = QVBoxLayout()
        seg_buttons.setContentsMargins(0, 0, 0, 0)
        seg_buttons.setSpacing(theme.SPACE_1)
        seg_buttons.addWidget(self.button(i18n.t("Save as segment"), "secondary",
                                          small=True, icon_name="check",
                                          on_click=self._save_segment))
        self.delete_segment_btn = self.button(
            i18n.t("Delete"), "secondary", small=True, icon_name="x",
            on_click=self._delete_segment)
        self.delete_segment_btn.setEnabled(False)
        seg_buttons.addWidget(self.delete_segment_btn)
        seg_row.addLayout(seg_buttons)
        col.addWidget(C.label(i18n.t("Saved segments"), level="META",
                              colour=theme.NEUTRAL[600]))
        col.addLayout(seg_row)

        self.audience_status = QLabel("")
        self.audience_status.setWordWrap(True)
        col.addWidget(self.audience_status)
        root.addWidget(card)

        self.broadcast_status = QLabel("")
        self.broadcast_status.setWordWrap(True)
        root.addWidget(self.broadcast_status)
        self.broadcast_btn = self.button(i18n.t("Send broadcast"), "primary",
                                         icon_name="message",
                                         on_click=self._send_broadcast)
        root.addWidget(self.broadcast_btn)

        self.campaigns_count_pill = C.Pill("0", "neutral")
        card, col = self._card("list", i18n.t("Past campaigns"),
                               pill=self.campaigns_count_pill)
        self.campaigns_list = QListWidget()
        self.campaigns_list.setFrameShape(QListWidget.NoFrame)
        col.addWidget(self.campaigns_list)
        root.addWidget(card)

        outer.addWidget(self._scrollable(host), stretch=1)
        return page

    def _refresh_tags(self):
        self._tags_worker = TagsLoadWorker()
        self._tags_worker.done.connect(self._on_tags_loaded)
        self._tags_worker.failed.connect(
            lambda e: self.audience_status.setText(
                i18n.t("Couldn't load tags: {e}").format(e=e)))
        self._tags_worker.start()

    def _on_tags_loaded(self, tags: list):
        self.tags_list.blockSignals(True)
        self.tags_list.clear()
        for tag in tags:
            item = QListWidgetItem(tag)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.tags_list.addItem(item)
        self.tags_list.blockSignals(False)
        self._preview_audience()

    def _checked_tags(self) -> list:
        return [self.tags_list.item(i).text()
                for i in range(self.tags_list.count())
                if self.tags_list.item(i).checkState() == Qt.Checked]

    def _preview_audience(self):
        self._audience_worker = AudiencePreviewWorker(self._checked_tags())
        self._audience_worker.done.connect(self._on_audience_previewed)
        self._audience_worker.failed.connect(
            lambda e: self.audience_status.setText(
                i18n.t("Couldn't check the audience: {e}").format(e=e)))
        self._audience_worker.start()

    def _on_audience_previewed(self, rows: list):
        self.audience_count_pill.setText(str(len(rows)))
        names = ", ".join((r.get("name") or r.get("phone") or "") for r in rows[:5])
        self.audience_status.setText(
            i18n.t("Will reach: {names}{more}").format(
                names=names or i18n.t("nobody yet"),
                more=i18n.t(" and {n} more").format(n=len(rows) - 5) if len(rows) > 5 else "")
            if rows else i18n.t("No opted-in contacts match this filter."))

    def _refresh_segments(self):
        self._segments_worker = SegmentsLoadWorker()
        self._segments_worker.done.connect(self._on_segments_loaded)
        self._segments_worker.start()

    def _on_segments_loaded(self, rows: list):
        self._segments = rows or []
        self.segments_list.clear()
        for row in self._segments:
            filt = row.get("filter") or {}
            tags = filt.get("tags") or []
            item = QListWidgetItem(f"{row.get('name', '')}  ({', '.join(tags) or i18n.t('everyone')})")
            item.setData(Qt.UserRole, row)
            self.segments_list.addItem(item)

    def _on_segment_selected(self, index: int):
        self.delete_segment_btn.setEnabled(index >= 0)
        if index < 0:
            return
        row = self.segments_list.item(index).data(Qt.UserRole) or {}
        tags = set((row.get("filter") or {}).get("tags") or [])
        self.tags_list.blockSignals(True)
        for i in range(self.tags_list.count()):
            item = self.tags_list.item(i)
            item.setCheckState(Qt.Checked if item.text() in tags else Qt.Unchecked)
        self.tags_list.blockSignals(False)
        self._preview_audience()

    def _save_segment(self):
        tags = self._checked_tags()
        name, ok = QInputDialog.getText(
            self, i18n.t("Save as segment"), i18n.t("Name this segment:"))
        if not ok or not name.strip():
            return
        self._segment_save_worker = SegmentSaveWorker(name.strip(), tags)
        self._segment_save_worker.done.connect(lambda _row: self._refresh_segments())
        self._segment_save_worker.failed.connect(
            lambda e: self.audience_status.setText(
                i18n.t("Couldn't save the segment: {e}").format(e=e)))
        self._segment_save_worker.start()

    def _delete_segment(self):
        item = self.segments_list.currentItem()
        if item is None:
            return
        row = item.data(Qt.UserRole) or {}
        self._segment_delete_worker = SegmentDeleteWorker(row.get("id"))
        self._segment_delete_worker.done.connect(self._refresh_segments)
        self._segment_delete_worker.failed.connect(
            lambda e: self.audience_status.setText(
                i18n.t("Couldn't delete the segment: {e}").format(e=e)))
        self._segment_delete_worker.start()

    def _refresh_campaigns(self):
        self._campaigns_worker = CampaignsLoadWorker()
        self._campaigns_worker.done.connect(self._on_campaigns_loaded)
        self._campaigns_worker.start()

    def _on_campaigns_loaded(self, rows: list):
        self.campaigns_list.clear()
        self.campaigns_count_pill.setText(str(len(rows or [])))
        for row in rows or []:
            text = "{name} — {sent}/{total} sent, {failed} failed · {status}".format(
                name=row.get("template_name", ""), sent=row.get("sent", 0),
                total=row.get("total", 0), failed=row.get("failed", 0),
                status=row.get("status", ""))
            self.campaigns_list.addItem(QListWidgetItem(text))

    def _send_broadcast(self):
        template = self.broadcast_template_edit.text().strip()
        language = self.broadcast_lang_edit.text().strip() or "en_US"
        if not template:
            self.broadcast_status.setText(i18n.t("Enter the template name first."))
            return
        tags = self._checked_tags()
        segment_name = ""
        seg_item = self.segments_list.currentItem()
        if seg_item is not None:
            segment_name = (seg_item.data(Qt.UserRole) or {}).get("name", "")
        self.broadcast_btn.setEnabled(False)
        self.broadcast_status.setText(i18n.t("Sending…"))
        self._broadcast_worker = BroadcastSendWorker(
            template_name=template, language=language,
            tags=tags, segment_name=segment_name)
        self._broadcast_worker.done.connect(self._on_broadcast_sent)
        self._broadcast_worker.failed.connect(self._on_broadcast_failed)
        self._broadcast_worker.start()

    def _on_broadcast_sent(self, result: dict):
        self.broadcast_btn.setEnabled(True)
        self.broadcast_status.setText(
            i18n.t("Sent to {n} contacts.").format(n=result.get("audience_size", 0)))
        self._refresh_campaigns()

    def _on_broadcast_failed(self, error: str):
        self.broadcast_btn.setEnabled(True)
        self.broadcast_status.setText(i18n.t("Couldn't send: {e}").format(e=error))

    # ── Settings ───────────────────────────────────────────────────────────
    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(0, theme.SPACE_3, theme.SPACE_2, theme.SPACE_3)
        root.setSpacing(theme.CARD_GAP)
        wa = self.cfg.get("whatsapp") or {}

        # -- WhatsApp number ---------------------------------------------
        self._wa_pill = self._status_pill(
            bool(wa.get("phone_number_id") and wa.get("token")))
        card, col = self._card("message", i18n.t("Your WhatsApp number"),
                               pill=self._wa_pill)
        self.pnid_edit = QLineEdit(wa.get("phone_number_id", ""))
        self.pnid_edit.setPlaceholderText(
            i18n.t("Phone number ID — from Meta → WhatsApp → API Setup"))
        col.addWidget(self._labelled(i18n.t("Phone number ID"), self.pnid_edit))
        self.token_edit = QLineEdit(wa.get("token", ""))
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText(
            i18n.t("Access token — kept on this computer, never sent anywhere "
                   "but Meta"))
        col.addWidget(self._labelled(i18n.t("Access token"), self.token_edit))
        root.addWidget(card)

        col2 = C.label(
            i18n.t("Inbox, Contacts and Broadcast need nothing set up here — "
                   "they go through your Prism licence, which already knows "
                   "which seat you are."), level="SUPPORT",
            colour=theme.NEUTRAL[600], wrap=True)
        root.addWidget(col2)

        self.settings_status = QLabel("")
        self.settings_status.setWordWrap(True)
        root.addWidget(self.settings_status)
        root.addStretch(1)

        outer.addWidget(self._scrollable(host), stretch=1)
        return page

    def _save_settings(self):
        block = dict(self.cfg.get("whatsapp") or {})
        block["phone_number_id"] = self.pnid_edit.text().strip()
        block["token"] = self.token_edit.text().strip()
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
            self.settings_status.setText(i18n.t("Saved."))
        except Exception as e:                          # noqa: BLE001
            self.settings_status.setText(i18n.t("Could not save: {e}").format(e=e))
            return
        self._set_pill(self._wa_pill, bool(block["phone_number_id"] and block["token"]))

    def _set_pill(self, pill: C.Pill, connected: bool):
        pill.set_tone("ok" if connected else "quiet")
        pill.setText(i18n.t("Connected") if connected else i18n.t("Not set"))

    # ── plumbing ───────────────────────────────────────────────────────────
    def _on_tab_changed(self, index: int):
        if index == _CONTACTS and not self._contacts_loaded:
            self._refresh_contacts()
        elif index == _BROADCAST and not self._broadcast_loaded:
            self._broadcast_loaded = True
            self._refresh_tags()
            self._refresh_segments()
            self._refresh_campaigns()

    def _stop_worker(self, worker):
        if worker is not None and worker.isRunning():
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(5000):
                worker.terminate()
                worker.wait(1000)

    def closeEvent(self, event):
        """Wind up every worker before the dialog is destroyed — a running
        QThread collected mid-call aborts the process."""
        for worker in (self._send_worker, self._convos_worker, self._thread_worker,
                       self._contacts_worker, self._optout_worker, self._reply_worker,
                       self._tags_worker, self._contact_tags_worker, self._segments_worker,
                       self._segment_save_worker, self._segment_delete_worker,
                       self._audience_worker, self._campaigns_worker, self._broadcast_worker):
            self._stop_worker(worker)
        super().closeEvent(event)
