"""The WhatsApp workspace: the pure logic (time ladder, reply window, read state,
demo data), the widgets that carry decisions (thread grouping, contact panel
edits), and the Inbox flow — driven with fake workers, so nothing here opens a
socket, starts a thread, or spins an event loop.

The rules this file follows: no processEvents()/exec()/QEventLoop, and nothing
touches the real ~/.prism (readstate and the demo are pointed at a temp dir).
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import chat, demo, readstate  # noqa: E402


def _iso(**ago) -> str:
    return (datetime.now(timezone.utc) - timedelta(**ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def _isolated_state():
    tmp = tempfile.mkdtemp(prefix="prism-wa-")
    readstate.reset_cache()
    demo._state.clear()
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield tmp
    readstate.reset_cache()
    demo._state.clear()


# ── time ─────────────────────────────────────────────────────────────────────

def test_the_time_ladder_goes_clock_yesterday_weekday_date():
    assert ":" in chat.short_time(_iso(minutes=5))
    assert chat.short_time(_iso(days=1, hours=1)) in ("Yesterday", chat.short_time(_iso(days=1, hours=1)))
    assert chat.short_time(_iso(days=3)) == (datetime.now().astimezone() - timedelta(days=3)).strftime("%a")
    old = chat.short_time(_iso(days=40))
    assert old.split()[0].isdigit() and len(old.split()) == 2


def test_an_unparseable_stamp_is_an_empty_string_not_a_crash():
    assert chat.short_time("") == ""
    assert chat.short_time("not a date") == ""
    assert chat.clock("nope") == ""


def test_the_reply_window_is_24_hours_from_their_last_message():
    open_ = chat.window_left([{"direction": "in", "created_at": _iso(hours=3)}])
    assert open_ is not None and timedelta(hours=20) < open_ < timedelta(hours=21, minutes=1)
    closed = chat.window_left([{"direction": "in", "created_at": _iso(hours=30)}])
    assert closed.total_seconds() < 0


def test_only_inbound_messages_open_the_window_and_the_newest_counts():
    assert chat.window_left([{"direction": "out", "created_at": _iso(minutes=1)}]) is None
    assert chat.window_left([]) is None
    msgs = [{"direction": "in", "created_at": _iso(hours=40)},
            {"direction": "in", "created_at": _iso(hours=2)},
            {"direction": "out", "created_at": _iso(minutes=5)}]
    assert chat.window_left(msgs).total_seconds() > 0


def test_human_delta_reads_naturally():
    assert chat.human_delta(timedelta(hours=21, minutes=12)) == "21h 12m"
    assert chat.human_delta(timedelta(minutes=45)) == "45m"
    assert chat.human_delta(timedelta(seconds=10)) == "1m"


def test_a_person_is_the_same_colour_everywhere_and_grey_when_opted_out():
    assert chat.avatar_colour("Asha Patel") == chat.avatar_colour("Asha Patel")
    assert chat.avatar_colour("Asha Patel", opted_out=True) != chat.avatar_colour("Asha Patel")


# ── read state ───────────────────────────────────────────────────────────────

def test_unread_means_last_message_is_inbound_and_newer_than_what_was_read():
    row = {"id": "c1", "last_direction": "in", "last_active_at": "2026-09-20T08:00:00Z"}
    assert readstate.is_unread(row)
    readstate.mark_read("c1", row["last_active_at"])
    assert not readstate.is_unread(row)
    newer = dict(row, last_active_at="2026-09-20T09:00:00Z")
    assert readstate.is_unread(newer)


def test_your_own_last_message_is_never_unread():
    assert not readstate.is_unread({"id": "c1", "last_direction": "out",
                                    "last_active_at": "2026-09-20T08:00:00Z"})


def test_read_state_survives_a_restart_and_never_goes_backwards():
    readstate.mark_read("c1", "2026-09-20T09:00:00Z")
    readstate.mark_read("c1", "2026-09-20T08:00:00Z")          # older: ignored
    readstate.reset_cache()                                    # "restart"
    assert not readstate.is_unread({"id": "c1", "last_direction": "in",
                                    "last_active_at": "2026-09-20T09:00:00Z"})


def test_a_corrupt_read_file_costs_a_badge_not_the_inbox(_isolated_state):
    path = os.path.join(_isolated_state, "whatsapp_read.json")
    with open(path, "w") as f:
        f.write("{not json")
    readstate.reset_cache()
    assert readstate.is_unread({"id": "c1", "last_direction": "in",
                                "last_active_at": "2026-09-20T09:00:00Z"})


# ── demo data ────────────────────────────────────────────────────────────────

def test_demo_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("PRISM_WHATSAPP_DEMO", raising=False)
    assert not demo.enabled()


def test_demo_can_never_be_switched_on_in_a_frozen_build(monkeypatch):
    monkeypatch.setenv("PRISM_WHATSAPP_DEMO", "1")
    with mock.patch("paths.is_frozen", return_value=True):
        assert not demo.enabled()
    with mock.patch("paths.is_frozen", return_value=False):
        assert demo.enabled()


def test_demo_answers_every_endpoint_in_the_servers_envelope():
    with mock.patch("time.sleep"):
        convos = demo.handle("/conversations", {})["conversations"]
        assert convos and {"id", "contact_name", "last_text", "last_direction",
                           "last_active_at", "opt_out"} <= set(convos[0])
        assert demo.handle("/thread", {"conversation_id": convos[0]["id"]})["messages"]
        assert "contacts" in demo.handle("/contacts", {"search": ""})
        assert demo.handle("/tags", {})["tags"]
        assert "segments" in demo.handle("/segments", {})
        assert "campaigns" in demo.handle("/campaigns", {})
        assert "audience" in demo.handle("/audience", {"tags": []})


def test_demo_opted_out_contacts_are_never_in_an_audience():
    with mock.patch("time.sleep"):
        everyone = demo.handle("/audience", {"tags": []})["audience"]
    assert everyone and not any(c["opt_out"] for c in everyone)


def test_a_demo_reply_lands_in_the_thread_and_moves_the_chat_to_the_top():
    with mock.patch("time.sleep"):
        first = demo.handle("/conversations", {})["conversations"]
        target = first[-1]["id"]
        demo.handle("/reply", {"conversation_id": target, "text": "hello there"})
        after = demo.handle("/conversations", {})["conversations"]
        thread = demo.handle("/thread", {"conversation_id": target})["messages"]
    assert after[0]["id"] == target and thread[-1]["text"] == "hello there"


def test_license_client_answers_from_demo_without_touching_the_network(monkeypatch):
    import licensing
    from addons.whatsapp import license_client as lc
    monkeypatch.setenv("PRISM_WHATSAPP_DEMO", "1")
    with mock.patch("time.sleep"), \
            mock.patch.object(licensing.client, "_post", side_effect=AssertionError("network!")):
        assert lc.list_conversations()


# ── thread ───────────────────────────────────────────────────────────────────

def _msgs():
    return [
        {"direction": "in", "sender": "A", "text": "one", "created_at": _iso(days=2)},
        {"direction": "in", "sender": "A", "text": "two", "created_at": _iso(days=2, seconds=-30)},
        {"direction": "out", "sender": "Harsh", "text": "three", "created_at": _iso(days=2, seconds=-90),
         "status": "read"},
        {"direction": "in", "sender": "A", "text": "four", "created_at": _iso(minutes=5)},
    ]


def test_thread_draws_one_bubble_per_message_and_a_chip_per_day():
    from addons.whatsapp.thread import MessageThread, _DayChip
    t = MessageThread()
    t.resize(800, 600)
    assert t.set_messages(_msgs()) is True
    assert len(t._bubbles) == 4
    chips = [t._col.itemAt(i).widget() for i in range(t._col.count())
             if isinstance(t._col.itemAt(i).widget(), _DayChip)]
    assert len(chips) == 2                                     # two days


def test_a_poll_that_finds_nothing_new_does_not_redraw():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    first = t._bubbles[0]
    assert t.set_messages(_msgs()) is False
    assert t._bubbles[0] is first


def test_a_new_status_is_a_change():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    msgs = _msgs()
    t.set_messages(msgs)
    msgs[2]["status"] = "delivered"
    assert t.set_messages(msgs) is True


def test_an_empty_thread_says_so_instead_of_showing_nothing():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages([])
    assert t._bubbles == []


def test_a_pending_send_can_fail_and_offer_retry():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    b = t.add_pending("hi", sender="You")
    assert b.msg["status"] == "sending"
    got = []
    t.retryRequested.connect(lambda text, bubble: got.append((text, bubble)))
    b.set_status("failed")
    assert b.meta._retry is True
    b.meta.clicked.emit()
    assert got == [("hi", b)]
    b.set_status("sent")
    assert b.meta._retry is False


def test_a_short_message_gets_a_short_bubble():
    from addons.whatsapp.thread import Bubble
    short = Bubble({"direction": "in", "text": "Ok", "created_at": _iso(minutes=1)}, tail=True)
    long_ = Bubble({"direction": "in", "text": "word " * 80, "created_at": _iso(minutes=1)}, tail=True)
    short.fit(560)
    long_.fit(560)
    assert short.body.width() < 200 < long_.body.width() <= 560


def test_the_composer_sends_on_enter_not_on_shift_enter_and_refuses_the_empty():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from addons.whatsapp.thread import Composer
    c = Composer()
    sent = []
    c.submitted.connect(sent.append)
    c._submit()
    assert sent == []                                          # nothing to send
    c.edit.setPlainText("  hello  ")
    c.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier))
    assert sent == [] and "\n" in c.edit.toPlainText()         # shift+enter = newline
    c.edit.setPlainText("  hello  ")
    c.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert sent == ["hello"] and c.edit.toPlainText() == ""


def test_the_composer_refuses_more_than_the_server_will_take():
    from addons.whatsapp.thread import Composer, _MAX_TEXT
    c = Composer()
    sent = []
    c.submitted.connect(sent.append)
    c.edit.setPlainText("x" * (_MAX_TEXT + 1))
    c._submit()
    assert sent == [] and not c.send_btn.isEnabled()


# ── contact panel ────────────────────────────────────────────────────────────

def _panel(**row):
    from addons.whatsapp.contact_panel import ContactPanel
    p = ContactPanel()
    base = {"id": "k1", "name": "Asha", "phone": "9198", "tags": ["vip"], "opt_out": False}
    base.update(row)
    p.set_contact(base)
    return p


def test_removing_a_tag_emits_the_remaining_tags_and_updates_at_once():
    p = _panel(tags=["vip", "hot lead"])
    got = []
    p.tagsChanged.connect(lambda cid, tags: got.append((cid, tags)))
    p._remove_tag("vip")
    assert got == [("k1", ["hot lead"])] and p._row["tags"] == ["hot lead"]


def test_adding_a_tag_is_sorted_and_case_insensitively_unique():
    from PySide6.QtWidgets import QLineEdit
    p = _panel(tags=["vip"])
    got = []
    p.tagsChanged.connect(lambda cid, tags: got.append(tags))
    edit = QLineEdit("Cold")
    p._add_tag(edit)
    assert got == [["Cold", "vip"]]
    dup = QLineEdit("VIP")
    p._add_tag(dup)
    assert len(got) == 1                                       # duplicate ignored


def test_opting_out_needs_no_confirmation_but_opting_back_in_does():
    from PySide6.QtWidgets import QMessageBox
    p = _panel(opt_out=False)
    got = []
    p.optOutChanged.connect(lambda cid, v: got.append(v))
    with mock.patch.object(QMessageBox, "question") as ask:
        p._toggle_opt_out(True)
        ask.assert_not_called()
    assert got == [True]

    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        p._toggle_opt_out(False)
    assert got == [True] and p._row["opt_out"] is True         # declined: unchanged
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        p._toggle_opt_out(False)
    assert got == [True, False]


def test_the_window_section_is_left_out_when_not_asked_for():
    from addons.whatsapp.contact_panel import ContactPanel
    p = ContactPanel()
    p.set_contact({"id": "k", "name": "A", "phone": "1"})     # window defaults to "n/a"
    texts = " ".join(w.text() for w in p.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "REPLY WINDOW" not in texts


# ── the inbox, with fake workers ─────────────────────────────────────────────

class _Sig:
    def __init__(self):
        self._fns = []

    def connect(self, fn):
        self._fns.append(fn)

    def emit(self, *a):
        for fn in list(self._fns):
            fn(*a)


def _fake_worker(script):
    """A worker class whose start() runs `script(self)` synchronously — the
    same signals, none of the thread."""
    class W:
        def __init__(self, *args, **kw):
            self.args, self.kw = args, kw
            self.done, self.failed = _Sig(), _Sig()

        def start(self):
            script(self)
    return W


CONVOS = [
    {"id": "c1", "contact_id": "k1", "contact_name": "Asha Patel", "contact_phone": "9198",
     "opt_out": False, "last_text": "Quote?", "last_direction": "in", "last_active_at": _iso(minutes=3)},
    {"id": "c2", "contact_id": "k2", "contact_name": "Ravi Shah", "contact_phone": "9199",
     "opt_out": False, "last_text": "Thanks", "last_direction": "out", "last_active_at": _iso(hours=2)},
    {"id": "c3", "contact_id": "k3", "contact_name": "Meera", "contact_phone": "9200",
     "opt_out": True, "last_text": "STOP", "last_direction": "in", "last_active_at": _iso(hours=30)},
]
THREADS = {"c1": [{"direction": "in", "text": "Quote?", "created_at": _iso(minutes=3)}],
           "c2": [{"direction": "out", "text": "Thanks", "created_at": _iso(hours=2)}],
           "c3": [{"direction": "in", "text": "STOP", "created_at": _iso(hours=30)}]}


@pytest.fixture
def inbox():
    from addons.whatsapp import inbox as I
    sent = []

    def convos(w): w.done.emit([dict(c) for c in CONVOS])
    def thread(w): w.done.emit(w.args[0], [dict(m) for m in THREADS[w.args[0]]])
    def contacts(w): w.done.emit([{"id": "k1", "name": "Asha Patel", "phone": "9198",
                                   "email": "a@x.in", "tags": ["vip"], "opt_out": False}])
    def tags(w): w.done.emit(["vip"])
    def reply(w): sent.append(dict(w.kw)); w.done.emit({"ok": True})

    with mock.patch.object(I, "ConversationsLoadWorker", _fake_worker(convos)), \
            mock.patch.object(I, "ThreadLoadWorker", _fake_worker(thread)), \
            mock.patch.object(I, "ContactsLoadWorker", _fake_worker(contacts)), \
            mock.patch.object(I, "TagsLoadWorker", _fake_worker(tags)), \
            mock.patch.object(I, "ReplySendWorker", _fake_worker(reply)), \
            mock.patch.object(I.QTimer, "singleShot", lambda *a, **k: None):
        page = I.InboxPage({})
        page.resize(1400, 800)
        page.sent = sent
        page.activate()
        yield page
        page.deactivate()


def test_the_inbox_lists_conversations_and_counts_what_is_unread(inbox):
    counts = []
    inbox.unreadChanged.connect(counts.append)
    inbox._apply_filter()
    assert inbox.list.count() == 3
    assert counts[-1] == 2                                      # Asha and Meera


def test_opening_a_conversation_marks_it_read(inbox):
    inbox.list.setCurrentRow(0)
    assert not readstate.is_unread(CONVOS[0])
    assert inbox.thread._bubbles


def test_the_unread_filter_and_the_search_narrow_the_list(inbox):
    inbox._on_chip("unread")
    assert inbox.list.count() == 2
    inbox._on_chip("opted")
    assert inbox.list.count() == 1
    inbox._on_chip("all")
    inbox.search.setText("ravi")
    inbox._apply_filter()
    assert inbox.list.count() == 1


def test_a_reply_is_sent_to_the_right_person_and_settles_to_sent(inbox):
    inbox.list.setCurrentRow(0)
    inbox._send("On it")
    assert inbox.sent[0]["phone"] == "9198" and inbox.sent[0]["text"] == "On it"
    assert inbox.sent[0]["conversation_id"] == "c1" and inbox.sent[0]["contact_id"] == "k1"
    assert inbox.thread._bubbles[-1].msg["status"] == "sent"
    assert inbox._rows[0]["last_text"] == "On it"              # list updated at once


def test_a_failed_send_is_marked_failed_and_can_be_retried(inbox):
    from addons.whatsapp import inbox as I
    inbox.list.setCurrentRow(0)
    with mock.patch.object(I, "ReplySendWorker",
                           _fake_worker(lambda w: w.failed.emit("n8n is down"))):
        inbox._send("hello")
    bubble = inbox.thread._bubbles[-1]
    assert bubble.msg["status"] == "failed" and inbox._inflight == 0
    inbox._retry("hello", bubble)                               # default worker succeeds
    assert bubble.msg["status"] == "sent"


def test_an_opted_out_contact_cannot_be_replied_to(inbox):
    inbox._on_chip("opted")
    inbox.list.setCurrentRow(0)
    assert not inbox.composer.edit.isEnabled()
    assert "opted out" in inbox.banner.text()


def test_a_closed_window_warns_but_still_lets_you_try(inbox):
    inbox._current = {"id": "cX", "contact_id": "kX", "contact_name": "Someone",
                      "contact_phone": "9", "opt_out": False}
    inbox._update_window([{"direction": "in", "created_at": _iso(hours=30)}])
    assert inbox.composer.edit.isEnabled()                      # you may still try
    assert "24 hours" in inbox.banner.text()
    assert inbox.head_window.text() == "Window closed"


def test_an_open_window_shows_time_left_and_no_warning(inbox):
    inbox._current = {"id": "cX", "contact_id": "kX", "contact_name": "Someone",
                      "contact_phone": "9", "opt_out": False}
    inbox._update_window([{"direction": "in", "created_at": _iso(hours=2)}])
    assert "left" in inbox.head_window.text() and not inbox.banner.text()
    assert inbox.composer.edit.isEnabled()


def test_someone_who_never_wrote_can_only_be_sent_a_template(inbox):
    inbox._current = {"id": "cX", "contact_id": "kX", "contact_name": "Someone",
                      "contact_phone": "9", "opt_out": False}
    inbox._update_window([{"direction": "out", "created_at": _iso(hours=2)}])
    assert inbox.head_window.text() == "Template only"
    assert "24 hours" in inbox.banner.text()


def test_a_load_failure_says_what_went_wrong(inbox):
    from addons.whatsapp import inbox as I
    inbox._rows = []
    inbox._loading_convos = False
    with mock.patch.object(I, "ConversationsLoadWorker",
                           _fake_worker(lambda w: w.failed.emit("licence server unreachable"))):
        inbox.refresh()
    assert "unreachable" in inbox.list_status.text()
    assert inbox.list_stack.currentIndex() == 1


def test_the_contact_rail_folds_away_on_a_narrow_window(inbox):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    inbox.resize(900, 700)
    inbox.resizeEvent(QResizeEvent(QSize(900, 700), QSize(1400, 800)))
    assert inbox._rail.isHidden()
    inbox.resize(1500, 700)
    inbox.resizeEvent(QResizeEvent(QSize(1500, 700), QSize(900, 700)))
    assert not inbox._rail.isHidden()


def test_choosing_to_hide_the_rail_sticks_even_on_a_wide_window(inbox):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    inbox.resize(1500, 700)
    inbox._toggle_rail()                                        # user hides it
    inbox.resizeEvent(QResizeEvent(QSize(1500, 700), QSize(1500, 700)))
    assert inbox._rail.isHidden()


# ── broadcasts ───────────────────────────────────────────────────────────────

AUDIENCE = [{"id": "k1", "name": "Asha", "phone": "9198", "tags": ["vip"], "opt_out": False},
            {"id": "k2", "name": "Ravi", "phone": "9199", "tags": [], "opt_out": False}]


@pytest.fixture
def broadcast():
    from addons.whatsapp import broadcast as B
    calls = {"send": [], "audience": []}

    def audience(w):
        calls["audience"].append(list(w.args[0]))
        w.done.emit([dict(a) for a in AUDIENCE])

    def send(w):
        calls["send"].append(dict(w.kw))
        w.done.emit({"campaign": {"id": "b1"}, "audience_size": 2})

    with mock.patch.object(B, "AudiencePreviewWorker", _fake_worker(audience)), \
            mock.patch.object(B, "BroadcastSendWorker", _fake_worker(send)), \
            mock.patch.object(B, "TagsLoadWorker", _fake_worker(lambda w: w.done.emit(["vip", "cold"]))), \
            mock.patch.object(B, "SegmentsLoadWorker", _fake_worker(lambda w: w.done.emit([]))), \
            mock.patch.object(B, "CampaignsLoadWorker", _fake_worker(lambda w: w.done.emit([]))), \
            mock.patch.object(B.CB.config, "save"):
        page = B.BroadcastPage({})
        page.calls = calls
        page.activate()
        page._preview_timer.stop()
        yield page


def test_send_stays_off_until_there_is_a_template_and_an_audience(broadcast):
    assert broadcast._audience and not broadcast.send_btn.isEnabled()      # no template yet
    broadcast.template_edit.setText("diwali_offer")
    assert broadcast.send_btn.isEnabled()
    assert "2 people" in broadcast.send_btn.text()


def test_the_audience_is_counted_by_the_tags_you_tick(broadcast):
    broadcast._tag_buttons["vip"].setChecked(True)
    broadcast._preview()
    assert broadcast.calls["audience"][-1] == ["vip"]


def test_an_old_audience_count_never_overwrites_a_newer_one(broadcast):
    broadcast._audience_token = 5
    broadcast._on_audience([{"id": "x"}] * 9, token=4)                   # stale
    assert len(broadcast._audience) == 2


def test_declining_the_confirmation_sends_nothing(broadcast):
    from PySide6.QtWidgets import QMessageBox
    broadcast.template_edit.setText("diwali_offer")
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        broadcast._confirm_send()
    assert broadcast.calls["send"] == []


def test_confirming_sends_the_right_template_language_and_tags(broadcast):
    from PySide6.QtWidgets import QMessageBox
    broadcast.template_edit.setText("  diwali_offer ")
    broadcast._tag_buttons["vip"].setChecked(True)
    broadcast.lang.setCurrentIndex(broadcast.lang.findData("hi"))
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        broadcast._confirm_send()
    sent = broadcast.calls["send"][0]
    assert sent["template_name"] == "diwali_offer" and sent["language"] == "hi"
    assert sent["tags"] == ["vip"]


def test_the_success_message_is_still_there_after_a_send(broadcast):
    """Regression: _update_send() used to clear the status line straight after
    it was set, so 'Sent to 2 people' flashed and vanished."""
    from PySide6.QtWidgets import QMessageBox
    broadcast.template_edit.setText("diwali_offer")
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        broadcast._confirm_send()
    assert "Sent to 2 people" in broadcast.status.text()


def test_a_failed_send_keeps_its_error_visible_and_lets_you_retry(broadcast):
    from addons.whatsapp import broadcast as B
    from PySide6.QtWidgets import QMessageBox
    broadcast.template_edit.setText("diwali_offer")
    with mock.patch.object(B, "BroadcastSendWorker",
                           _fake_worker(lambda w: w.failed.emit("n8n refused"))), \
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        broadcast._confirm_send()
    assert "n8n refused" in broadcast.status.text()
    assert broadcast.send_btn.isEnabled()


def test_a_sent_template_is_remembered_for_next_time(broadcast):
    from PySide6.QtWidgets import QMessageBox
    broadcast.template_edit.setText("diwali_offer")
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        broadcast._confirm_send()
    assert broadcast.cfg["whatsapp"]["recent_templates"][0] == "diwali_offer"


# ── contacts ─────────────────────────────────────────────────────────────────

CONTACTS = [
    {"id": "k1", "name": "Asha", "phone": "9198", "tags": ["vip"], "opt_out": False},
    {"id": "k2", "name": "Ravi", "phone": "9199", "tags": [], "opt_out": True},
]


@pytest.fixture
def contacts():
    from addons.whatsapp import contacts as K
    saved = []
    with mock.patch.object(K, "ContactsLoadWorker",
                           _fake_worker(lambda w: w.done.emit([dict(c) for c in CONTACTS]))), \
            mock.patch.object(K, "TagsLoadWorker", _fake_worker(lambda w: w.done.emit(["vip"]))), \
            mock.patch.object(K, "ContactTagsSaveWorker",
                              _fake_worker(lambda w: (saved.append(w.args), w.done.emit({"tags": w.args[1]})))), \
            mock.patch.object(K, "ContactOptOutWorker",
                              _fake_worker(lambda w: w.done.emit({"opt_out": w.args[1]}))):
        page = K.ContactsPage({})
        page.saved = saved
        page.activate()
        yield page


def test_contacts_list_everyone_and_the_filter_splits_by_opt_out(contacts):
    assert contacts.list.count() == 2
    contacts._on_chip("out")
    assert contacts.list.count() == 1
    contacts._on_chip("in")
    assert contacts.list.count() == 1


def test_selecting_a_contact_fills_the_detail_panel(contacts):
    contacts.list.setCurrentRow(0)
    assert contacts.panel.contact_id() == "k1"


def test_tagging_a_contact_saves_and_the_list_reflects_it(contacts):
    contacts.list.setCurrentRow(0)
    contacts.panel._remove_tag("vip")
    assert contacts.saved[0] == ("k1", [])
    assert contacts._rows[0]["tags"] == []


def test_a_failed_save_says_so_and_reloads_the_truth(contacts):
    from addons.whatsapp import contacts as K
    loads = []
    with mock.patch.object(K, "ContactsLoadWorker",
                           _fake_worker(lambda w: (loads.append(1), w.done.emit([dict(c) for c in CONTACTS])))):
        contacts._save_failed("disk full")
    assert "disk full" in contacts.status.text() and loads


def test_no_contacts_is_an_explained_empty_state_not_a_blank_pane(contacts):
    contacts._on_loaded([])
    assert contacts.stack.currentIndex() == 1


def test_a_failed_message_survives_a_redraw_so_the_words_are_never_lost():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    b = t.add_pending("my important reply", sender="You")
    b.set_status("failed")
    newer = _msgs() + [{"direction": "in", "text": "still there?", "created_at": _iso(seconds=5)}]
    t.set_messages(newer)                                       # a poll finds news
    texts = [x.body.text() for x in t._bubbles]
    assert "my important reply" in texts and texts[-1] == "my important reply"
    assert t._bubbles[-1].msg["status"] == "failed"


def test_a_sent_message_is_not_kept_or_duplicated_after_the_server_has_it():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    b = t.add_pending("hello", sender="You")
    b.set_status("sent")
    confirmed = _msgs() + [{"direction": "out", "text": "hello", "created_at": _iso(seconds=1)}]
    t.set_messages(confirmed)
    assert [x.body.text() for x in t._bubbles].count("hello") == 1


def test_a_failed_first_message_in_an_empty_chat_is_still_shown():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages([])
    b = t.add_pending("hi there", sender="You")
    b.set_status("failed")
    t._signature = None
    t.set_messages([])
    assert [x.body.text() for x in t._bubbles] == ["hi there"]
