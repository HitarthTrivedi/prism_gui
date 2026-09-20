"""The Inbox — every conversation, the live thread, and who you are talking to.

Three panes, the shape every messenger and support desk has converged on:

    conversations  |  the thread + composer  |  the contact

It stays current on its own (a quiet poll while the tab is on screen), tells you
what you have not read (per seat — see readstate.py), and treats a send as
instant: the bubble is on screen the moment you press Enter and settles to sent
or to a red Retry. Nothing here blocks the window; every call runs on a worker.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import readstate
from addons.whatsapp.chat import (CONVO_ROW_H, ConversationDelegate,
                                  avatar_colour, human_delta, window_left)
from addons.whatsapp.contact_panel import ContactPanel
from addons.whatsapp.thread import Banner, Composer, MessageThread
from addons.whatsapp.workers import (ContactOptOutWorker, ContactsLoadWorker,
                                     ContactTagsSaveWorker,
                                     ConversationsLoadWorker, ReplySendWorker,
                                     TagsLoadWorker, ThreadLoadWorker)
from widgets import controls as C

POLL_MS = 15000
_NARROW = 1120                       # below this the contact rail folds away


def _card(objname: str) -> QFrame:
    f = QFrame()
    f.setObjectName(objname)
    f.setAttribute(Qt.WA_StyledBackground, True)
    f.setStyleSheet(
        f"#{objname} {{ background: {theme.CARD}; border: 1px solid {theme.HAIRLINE};"
        f" border-radius: {theme.R_CARD}px; }}")
    return f


class InboxPage(QWidget):
    unreadChanged = Signal(int)
    statusChanged = Signal(str, bool)           # message, is_error

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._rows: list = []
        self._contacts: dict = {}
        self._current = None                    # the selected conversation row
        self._thread_stamp: dict = {}           # id -> last_active_at it was loaded at
        self._inflight = 0                      # sends still travelling
        self._loading_convos = False
        self._filter = "all"
        self._rail_pref = None                  # None = automatic, else user's choice
        self._first_load = True
        self._last_error = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        root.setSpacing(0)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(theme.SPACE_3)
        self.split.setStyleSheet("QSplitter::handle { background: transparent; }")
        root.addWidget(self.split)
        self.split.addWidget(self._build_list())
        self.split.addWidget(self._build_thread())
        self.contact_panel = ContactPanel()
        self.contact_panel.tagsChanged.connect(self._save_tags)
        self.contact_panel.optOutChanged.connect(self._save_opt_out)
        rail = _card("waRail")
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.contact_panel)
        rail.setMinimumWidth(270)
        rail.setMaximumWidth(340)
        self._rail = rail
        self.split.addWidget(rail)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([340, 600, 300])

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(lambda: self.refresh(silent=True))
        find = QShortcut(QKeySequence("Ctrl+F"), self)
        find.setContext(Qt.WidgetWithChildrenShortcut)
        find.activated.connect(lambda: self.search.setFocus(Qt.ShortcutFocusReason))

        self._show_thread_page(False)

    # ── construction ─────────────────────────────────────────────────────────
    def _build_list(self) -> QWidget:
        card = _card("waList")
        card.setMinimumWidth(290)
        card.setMaximumWidth(440)
        col = QVBoxLayout(card)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_4, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_3)

        self.search = C.SearchField(i18n.t("Search conversations"))
        self.search.changed.connect(lambda _t: self._apply_filter())
        col.addWidget(self.search)
        self.chips = C.FilterChips([("all", i18n.t("All")), ("unread", i18n.t("Unread")),
                                    ("opted", i18n.t("Opted out"))], current="all")
        self.chips.changed.connect(self._on_chip)
        col.addWidget(self.chips)

        self.list_stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(ConversationDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }")
        self.list.currentItemChanged.connect(self._on_selected)
        self.list_stack.addWidget(self.list)
        self.list_empty = C.EmptyState("inbox", i18n.t("No conversations yet"),
                                       i18n.t("When someone messages your WhatsApp number, "
                                              "the chat appears here."))
        self.list_stack.addWidget(self.list_empty)
        col.addWidget(self.list_stack, stretch=1)

        self.list_status = C.label("", level="META", colour=theme.NEUTRAL[500])
        col.addWidget(self.list_status)
        return card

    def _build_thread(self) -> QWidget:
        card = _card("waThread")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.thread_stack = QStackedWidget()
        outer.addWidget(self.thread_stack)

        self.thread_empty = C.EmptyState(
            "message", i18n.t("Pick a conversation"),
            i18n.t("Choose someone on the left to read the chat and reply."))
        self.thread_stack.addWidget(self.thread_empty)

        live = QWidget()
        lc = QVBoxLayout(live)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(0)

        head = QFrame()
        head.setObjectName("waThreadHead")
        head.setAttribute(Qt.WA_StyledBackground, True)
        head.setStyleSheet(f"#waThreadHead {{ border-bottom: 1px solid {theme.HAIRLINE}; }}")
        hr = QHBoxLayout(head)
        hr.setContentsMargins(theme.SPACE_5, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        hr.setSpacing(theme.SPACE_3)
        self.head_avatar_holder = QHBoxLayout()
        self.head_avatar_holder.setContentsMargins(0, 0, 0, 0)
        hr.addLayout(self.head_avatar_holder)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.head_name = C.label("", level="SECTION", weight=700)
        self.head_sub = C.label("", level="META", colour=theme.NEUTRAL[600])
        titles.addWidget(self.head_name)
        titles.addWidget(self.head_sub)
        hr.addLayout(titles, stretch=1)
        self.head_window = C.Pill("", "quiet")
        self.head_window.hide()
        hr.addWidget(self.head_window)
        self.rail_btn = C.icon_button("user", i18n.t("Show or hide contact details"),
                                      on_click=self._toggle_rail)
        hr.addWidget(self.rail_btn)
        lc.addWidget(head)

        self.thread = MessageThread()
        self.thread.retryRequested.connect(self._retry)
        lc.addWidget(self.thread, stretch=1)

        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_4)
        fl.setSpacing(theme.SPACE_2)
        self.banner = Banner()
        fl.addWidget(self.banner)
        self.composer = Composer()
        self.composer.submitted.connect(self._send)
        fl.addWidget(self.composer)
        lc.addWidget(foot)
        self.thread_stack.addWidget(live)
        return card

    def _show_thread_page(self, live: bool):
        self.thread_stack.setCurrentIndex(1 if live else 0)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def activate(self):
        """The tab came on screen: load now, then keep quietly current."""
        self.refresh(silent=not self._first_load)
        self._timer.start()
        if self._first_load:
            self._first_load = False
            self._load_side_data()

    def deactivate(self):
        self._timer.stop()

    def _load_side_data(self):
        cw = ContactsLoadWorker()
        cw.done.connect(self._on_contacts)
        cw.failed.connect(lambda _e: None)
        self._contacts_worker = cw
        cw.start()
        tw = TagsLoadWorker()
        tw.done.connect(self.contact_panel.set_known_tags)
        tw.failed.connect(lambda _e: None)
        self._tags_worker = tw
        tw.start()

    def _on_contacts(self, rows: list):
        self._contacts = {r.get("id"): r for r in rows or []}
        if self._current:
            self._show_contact()

    # ── conversations ────────────────────────────────────────────────────────
    def refresh(self, silent: bool = False):
        if self._loading_convos:
            return
        self._loading_convos = True
        if not silent:
            self.list_status.setText(i18n.t("Loading…"))
        w = ConversationsLoadWorker()
        w.done.connect(self._on_convos)
        w.failed.connect(self._on_convos_failed)
        self._convos_worker = w
        w.start()

    def _on_convos_failed(self, error: str):
        self._loading_convos = False
        self._last_error = error
        self.list_status.setText(i18n.t("Couldn't refresh — {e}").format(e=error))
        self.list_status.setStyleSheet(f"color: {theme.ERR_INK};")
        self.statusChanged.emit(error, True)
        if not self._rows:
            self.list_empty.set_text(i18n.t("Couldn't load your inbox"), error)
            self.list_stack.setCurrentIndex(1)

    def _on_convos(self, rows: list):
        self._loading_convos = False
        self._last_error = ""
        self._rows = rows or []
        self.list_status.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        self.list_status.setText(i18n.t("Updated {t}").format(
            t=datetime.now().strftime("%I:%M %p").lstrip("0")))
        self.statusChanged.emit("", False)
        self._apply_filter()
        # the open chat has news: fetch it quietly, no "Loading…" flash
        if self._current:
            fresh = next((r for r in self._rows if r.get("id") == self._current.get("id")), None)
            if fresh is not None:
                self._current = fresh
                if fresh.get("last_active_at") != self._thread_stamp.get(fresh.get("id")):
                    self._load_thread(fresh.get("id"), silent=True)

    def _visible_rows(self) -> list:
        term = self.search.text().strip().lower()
        out = []
        for r in self._rows:
            if self._filter == "unread" and not readstate.is_unread(r):
                continue
            if self._filter == "opted" and not r.get("opt_out"):
                continue
            if term:
                hay = " ".join((r.get("contact_name") or "", r.get("contact_phone") or "",
                                r.get("last_text") or "")).lower()
                if term not in hay:
                    continue
            out.append(r)
        return out

    def _apply_filter(self):
        rows = self._visible_rows()
        keep = (self._current or {}).get("id")
        self.list.blockSignals(True)
        self.list.clear()
        selected_row = -1
        for i, r in enumerate(rows):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, r)
            item.setSizeHint(QSize(0, CONVO_ROW_H))
            self.list.addItem(item)
            if r.get("id") == keep:
                selected_row = i
        if selected_row >= 0:
            self.list.setCurrentRow(selected_row)
        self.list.blockSignals(False)
        unread = sum(1 for r in self._rows if readstate.is_unread(r))
        self.unreadChanged.emit(unread)
        if rows:
            self.list_stack.setCurrentIndex(0)
        else:
            if not self._rows:
                self.list_empty.set_text(i18n.t("No conversations yet"),
                                         i18n.t("When someone messages your WhatsApp number, "
                                                "the chat appears here."))
            else:
                self.list_empty.set_text(i18n.t("Nothing matches"),
                                         i18n.t("Try a different search or filter."))
            self.list_stack.setCurrentIndex(1)

    def _on_chip(self, value: str):
        self._filter = value
        self._apply_filter()

    def _repaint_list(self):
        self.list.viewport().update()
        self.unreadChanged.emit(sum(1 for r in self._rows if readstate.is_unread(r)))

    # ── one conversation ─────────────────────────────────────────────────────
    def _on_selected(self, item, _previous=None):
        if item is None:
            return
        row = item.data(Qt.UserRole) or {}
        self._current = row
        self._show_thread_page(True)
        who = row.get("contact_name") or row.get("contact_phone") or i18n.t("Unknown")
        self._set_head(row, who)
        self.banner.hide()
        self.composer.set_active(True, i18n.t("Type a message — Enter to send, Shift+Enter for a new line"))
        self.thread.show_note(i18n.t("Loading…"))
        self._show_contact()
        self._load_thread(row.get("id"))
        self.composer.focus()

    def _set_head(self, row: dict, who: str):
        while self.head_avatar_holder.count():
            w = self.head_avatar_holder.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.head_avatar_holder.addWidget(
            C.Avatar(who, 40, avatar_colour(who, bool(row.get("opt_out")))))
        self.head_name.setText(who)
        phone = row.get("contact_phone") or ""
        self.head_sub.setText(("+" + phone.lstrip("+")) if phone else "")

    def _merged_contact(self, row: dict) -> dict:
        base = dict(self._contacts.get(row.get("contact_id")) or {})
        base.setdefault("id", row.get("contact_id"))
        base["name"] = base.get("name") or row.get("contact_name") or ""
        base["phone"] = base.get("phone") or row.get("contact_phone") or ""
        base["opt_out"] = bool(base.get("opt_out") or row.get("opt_out"))
        return base

    def _show_contact(self, window="n/a"):
        if self._current:
            self.contact_panel.set_contact(self._merged_contact(self._current), window)

    def _load_thread(self, cid, silent: bool = False):
        w = ThreadLoadWorker(cid)
        w.done.connect(lambda c, msgs, s=silent: self._on_thread(c, msgs, s))
        w.failed.connect(self._on_thread_failed)
        self._thread_worker = w
        w.start()

    def _on_thread_failed(self, cid, error: str):
        if self._current and self._current.get("id") == cid and not self.thread._bubbles:
            self.thread.show_note(
                i18n.t("Couldn't load this conversation.\n{e}").format(e=error), tone="error")

    def _on_thread(self, cid, messages: list, silent: bool):
        if not self._current or self._current.get("id") != cid:
            return
        if silent and self._inflight:
            return                              # a send is mid-flight; don't redraw under it
        self._thread_stamp[cid] = self._current.get("last_active_at")
        self.thread.set_messages(messages)
        readstate.mark_read(cid, self._current.get("last_active_at") or "")
        self._repaint_list()
        self._update_window(messages)

    def _update_window(self, messages: list):
        left = window_left(messages)
        row = self._current or {}
        opted = bool(self._merged_contact(row).get("opt_out")) if row else False
        if left is None:
            self.head_window.setText(i18n.t("Template only"))
            self.head_window.set_tone("quiet")
        elif left.total_seconds() > 0:
            self.head_window.setText(i18n.t("Reply window · {t} left").format(t=human_delta(left)))
            self.head_window.set_tone("ok")
        else:
            self.head_window.setText(i18n.t("Window closed"))
            self.head_window.set_tone("warn")
        self.head_window.show()
        self._show_contact(left if left is not None else None)

        if opted:
            self.banner.show_note(i18n.t(
                "This contact opted out. Replies are turned off — you can change that in "
                "the contact details."), "err")
            self.composer.set_active(False, i18n.t("Opted out — messaging is turned off"))
        elif left is None or left.total_seconds() <= 0:
            self.banner.show_note(i18n.t(
                "It's been over 24 hours since they wrote, so WhatsApp will only deliver an "
                "approved template — a plain reply may not reach them."), "warn")
            self.composer.set_active(True)
        else:
            self.banner.hide()
            self.composer.set_active(True)

    # ── sending ──────────────────────────────────────────────────────────────
    def _send(self, text: str, bubble=None):
        row = self._current
        if not row:
            return
        if bubble is None:
            bubble = self.thread.add_pending(text, sender=i18n.t("You"))
        else:
            bubble.set_status("sending")
        self._inflight += 1
        w = ReplySendWorker(phone=row.get("contact_phone", ""), text=text,
                            conversation_id=row.get("id", ""),
                            contact_id=row.get("contact_id", ""))
        w.done.connect(lambda _d, b=bubble, t=text, r=row: self._sent(b, t, r))
        w.failed.connect(lambda e, b=bubble: self._send_failed(b, e))
        # kept so a fast second send does not drop the first worker's reference
        self._send_workers = getattr(self, "_send_workers", [])
        self._send_workers.append(w)
        w.start()

    def _sent(self, bubble, text: str, row: dict):
        self._inflight = max(0, self._inflight - 1)
        bubble.set_status("sent")
        # reflect it on the conversation row immediately; the next poll confirms it
        for r in self._rows:
            if r.get("id") == row.get("id"):
                r["last_text"], r["last_direction"] = text, "out"
                r["last_active_at"] = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
                readstate.mark_read(r["id"], r["last_active_at"])
        self._rows.sort(key=lambda r: r.get("last_active_at") or "", reverse=True)
        self._apply_filter()
        QTimer.singleShot(1800, lambda: self._settle(row.get("id")))

    def _settle(self, cid):
        if self._current and self._current.get("id") == cid and not self._inflight:
            self.refresh(silent=True)
            self._thread_stamp.pop(cid, None)
            self._load_thread(cid, silent=True)

    def _send_failed(self, bubble, error: str):
        self._inflight = max(0, self._inflight - 1)
        bubble.set_status("failed")
        self.statusChanged.emit(error, True)
        self.banner.show_note(i18n.t("Couldn't send: {e}").format(e=error), "err")

    def _retry(self, text: str, bubble):
        self.banner.hide()
        self._send(text, bubble=bubble)

    # ── contact edits ────────────────────────────────────────────────────────
    def _save_tags(self, contact_id, tags: list):
        w = ContactTagsSaveWorker(contact_id, tags)
        w.done.connect(lambda row, cid=contact_id: self._contact_saved(cid, row))
        w.failed.connect(lambda e: self._contact_failed(e))
        self._save_worker = w
        w.start()

    def _save_opt_out(self, contact_id, opted_out: bool):
        w = ContactOptOutWorker(contact_id, opted_out)
        w.done.connect(lambda row, cid=contact_id: self._contact_saved(cid, row))
        w.failed.connect(lambda e: self._contact_failed(e))
        self._save_worker = w
        w.start()

    def _contact_saved(self, cid, row: dict):
        if row:
            self._contacts[cid] = {**self._contacts.get(cid, {}), **row}
        for r in self._rows:
            if r.get("contact_id") == cid and row and "opt_out" in row:
                r["opt_out"] = bool(row["opt_out"])
        if self._current and self._current.get("contact_id") == cid and row and "opt_out" in row:
            self._current["opt_out"] = bool(row["opt_out"])
            self._set_head(self._current, self.head_name.text())
            self._load_thread(self._current.get("id"), silent=True)
        self._apply_filter()

    def _contact_failed(self, error: str):
        self.statusChanged.emit(error, True)
        self.banner.show_note(i18n.t("Couldn't save that change: {e}").format(e=error), "err")
        self._show_contact()                    # put the panel back to what is really saved

    # ── layout ───────────────────────────────────────────────────────────────
    def _toggle_rail(self):
        # isHidden(), not "not isVisible()": the latter is also true whenever the
        # page itself is off screen, which would turn "hide" into "show".
        self._rail_pref = self._rail.isHidden()
        self._rail.setVisible(self._rail_pref)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._rail_pref is None:
            self._rail.setVisible(self.width() >= _NARROW)
