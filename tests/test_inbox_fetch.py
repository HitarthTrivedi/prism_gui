"""
What "Check my mail" is allowed to cost
───────────────────────────────────────
These pin the fix for a real check on a real mailbox, recorded in
~/.prism/logs/inbox-check-2026-08-24.log:

    766 messages match — fetching the oldest 200 this run
    fetched 200/200 in 139.4s
    sorting: 155 placed by local rules, 45 sent to the AI
    ── done in 181.6s — 200 fetched, 0 new inquiry(ies), 0 order(s) ──

Three minutes, and nothing to show for it. Two separate mistakes:

  1. It took the OLDEST 200 of 766, so the first check downloaded month-old
     marketing and the owner's actual inquiries were four checks away.
  2. It downloaded every message in full — body and attachments — purely so
     the rules could read its headers and call it a newsletter.

The tests below are written against that shape: a mailbox with far more mail
than one check may take, most of it announcing in its own headers that no
human wrote it.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prism_terminal"))

from core import inbox, triage  # noqa: E402


def _raw(uid, *, sender="raj@steelworks.co.in", subject="Need a quotation",
         unsubscribe=False, precedence="", auto="", body="Please quote 200 pcs."):
    """One message as bytes, headers and body, the way a server sends it."""
    headers = [f"From: {sender}", f"Subject: {subject}",
               f"Message-ID: <{uid}@example.com>", "Date: Mon, 24 Aug 2026 10:00:00 +0530",
               "Content-Type: text/plain; charset=utf-8"]
    if unsubscribe:
        headers.append("List-Unsubscribe: <https://x.example/u>")
    if precedence:
        headers.append(f"Precedence: {precedence}")
    if auto:
        headers.append(f"Auto-Submitted: {auto}")
    return ("\r\n".join(headers) + "\r\n\r\n" + body).encode("utf-8")


class FakeMailbox:
    """An IMAP server that counts what was asked of it.

    The counting is the point: the bug was not a wrong answer, it was the
    number of round trips and the number of full downloads needed to get it.
    """

    def __init__(self, messages: dict, uidvalidity: int = 1):
        self.messages = messages                  # uid → raw bytes
        self.uidvalidity = uidvalidity
        self.header_batches = 0                   # FETCH ... BODY.PEEK[HEADER]
        self.full_fetches = []                    # uids pulled down whole
        self.searches = []

    # -- the parts inbox.py uses -------------------------------------------
    def select(self, folder, readonly=False):
        assert readonly, "the mailbox must never be opened for writing"
        return "OK", [b"1"]

    def response(self, name):
        return ("OK", [str(self.uidvalidity).encode()]) if name == "UIDVALIDITY" else ("NO", [])

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[1]
            self.searches.append(criteria)
            uids = sorted(self.messages)
            if criteria.startswith("UID "):
                low = int(criteria.split()[1].split(":")[0])
                uids = [u for u in uids if u >= low] or uids[-1:]
            return "OK", [" ".join(str(u) for u in uids).encode()]

        if command == "FETCH":
            wanted, what = args[0], args[1]
            uids = [int(x) for x in wanted.split(",")]
            if "HEADER" in what:
                self.header_batches += 1
                out = []
                for uid in uids:
                    raw = self.messages.get(uid)
                    if raw is None:
                        continue
                    head = raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
                    out.append((f"1 (UID {uid} BODY[HEADER] ".encode(), head))
                return "OK", out
            self.full_fetches.extend(uids)
            out = [(f"1 (UID {u} BODY[] ".encode(), self.messages[u])
                   for u in uids if u in self.messages]
            return "OK", out
        return "NO", []

    def close(self):
        pass

    def logout(self):
        pass


class _connected:
    """Point inbox.fetch_new at a FakeMailbox instead of a real server."""

    def __init__(self, mailbox):
        self.mailbox = mailbox

    def __enter__(self):
        self.original = inbox._connect
        inbox._connect = lambda ic, timeout=60: self.mailbox
        return self.mailbox

    def __exit__(self, *exc):
        inbox._connect = self.original
        return False


CFG = {"inbox": {"address": "sales@acme.co.in", "password": "x",
                 "host": "imap.example.com", "port": 993}}


def _fetch(mailbox, state=None, **kw):
    with _connected(mailbox):
        return inbox.fetch_new(CFG, state, **kw)


# ── the ordering bug ─────────────────────────────────────────────────────────

class TheNewestMailComesFirst(unittest.TestCase):
    """The whole complaint in one sentence: three minutes of waiting to be
    shown a month-old newsletter."""

    def setUp(self):
        # 300 messages, uid 1..300. The newest are the high numbers.
        self.box = FakeMailbox({uid: _raw(uid) for uid in range(1, 301)})

    def test_a_first_check_takes_the_newest_not_the_oldest(self):
        messages, _state, error = _fetch(self.box, limit=50)
        self.assertEqual(error, "")
        uids = [m.uid for m in messages]
        self.assertEqual(max(uids), 300, "the newest message must be in the batch")
        self.assertEqual(min(uids), 251,
                         "a first check took the OLDEST 50 — which is how a "
                         "three-minute check reported zero inquiries")

    def test_they_still_arrive_oldest_first(self):
        """Chosen newest-first, handed back oldest-first: the register has to
        fill in the order things actually happened."""
        messages, _state, _error = _fetch(self.box, limit=50)
        self.assertEqual([m.uid for m in messages],
                         sorted(m.uid for m in messages))

    def test_the_bookmark_sits_at_the_top_afterwards(self):
        _messages, state, _error = _fetch(self.box, limit=50)
        self.assertEqual(state.last_uid, 300)
        self.assertEqual(state.floor_uid, 251,
                         "how far down we reached is what makes the rest a "
                         "backlog rather than lost mail")


# ── the backlog ──────────────────────────────────────────────────────────────

class TheOlderMailIsNotLost(unittest.TestCase):
    """Newest-first is only safe if the remainder is still collected. An
    inquiry three weeks old is still an inquiry."""

    def setUp(self):
        self.box = FakeMailbox({uid: _raw(uid) for uid in range(1, 301)})

    def test_the_backlog_is_worked_through_on_later_checks(self):
        _m, state, _e = _fetch(self.box, limit=50, backfill=0)
        self.assertEqual(state.floor_uid, 251)

        _m2, state2, _e2 = _fetch(self.box, state=state, limit=50, backfill=40)
        self.assertEqual(state2.floor_uid, 211, "the floor must move down")
        self.assertEqual(state2.last_uid, 300, "and the top must not move back")

    def test_every_message_is_eventually_seen(self):
        """Twelve unnoticed checks rather than four three-minute ones."""
        state, seen = None, set()
        for _ in range(20):
            messages, state, _e = _fetch(self.box, state=state, limit=50, backfill=40)
            seen.update(m.uid for m in messages)
            if state.backfilled:
                break
        self.assertEqual(seen, set(range(1, 301)),
                         "mail chosen against must still be collected later")
        self.assertTrue(state.backfilled)

    def test_an_account_from_before_this_change_starts_a_backlog(self):
        """A real config held {"uidvalidity": 0, "last_uid": 9892} and no
        floor. Left alone, floor_uid stays 0, the catch-up never runs, and
        everything the old oldest-first fetch never reached is abandoned —
        which is the opposite of what the bookmark is for."""
        upgraded = inbox.State(uidvalidity=1, last_uid=200, floor_uid=0)
        _m, state, _e = _fetch(self.box, state=upgraded, backfill=40)
        self.assertEqual(state.floor_uid, 160,
                         "the catch-up must start from the old bookmark")
        self.assertEqual(state.last_uid, 300, "and still take what is new")

    def test_a_cleared_backlog_stops_being_searched(self):
        """Once caught up, the steady state must cost one search, not two."""
        state = inbox.State(uidvalidity=1, last_uid=300, floor_uid=1)
        _m, state2, _e = _fetch(self.box, state=state)
        self.assertTrue(state2.backfilled)

        self.box.searches.clear()
        _m3, _state3, _e3 = _fetch(self.box, state=state2)
        self.assertEqual(len(self.box.searches), 1,
                         "a cleared backlog must not be re-searched for ever")


# ── the download bug ─────────────────────────────────────────────────────────

class OnlyMailWorthReadingIsDownloaded(unittest.TestCase):
    """155 of 200 messages were placed by local rules that only ever looked at
    headers — after every one of them had been downloaded in full."""

    def setUp(self):
        mail = {}
        for uid in range(1, 41):            # 40 mailshots, honest about it
            mail[uid] = _raw(uid, sender="news@shop.example",
                             subject="50% off this week", unsubscribe=True)
        for uid in range(41, 46):           # 5 real ones
            mail[uid] = _raw(uid, sender=f"buyer{uid}@steelworks.co.in")
        self.box = FakeMailbox(mail)

    def test_a_mailshot_never_has_its_body_downloaded(self):
        _messages, _state, _error = _fetch(self.box)
        self.assertEqual(sorted(self.box.full_fetches), list(range(41, 46)),
                         "only the five that might be from a person should "
                         "have been pulled down whole")

    def test_the_mailshots_still_come_back(self):
        """Skipping the body is not skipping the message — it still has to be
        counted and sorted, or the totals lie."""
        messages, _state, _error = _fetch(self.box)
        self.assertEqual(len(messages), 45)
        skipped = [m for m in messages if m.headers_only]
        self.assertEqual(len(skipped), 40)
        self.assertTrue(all(m.subject for m in skipped),
                        "headers were read, so the subject is known")

    def test_headers_are_asked_for_in_batches_not_one_at_a_time(self):
        _messages, _state, _error = _fetch(self.box)
        self.assertLessEqual(self.box.header_batches, 2,
                             "one round trip per message is what made a check "
                             "take 139 seconds")

    def test_a_real_message_is_read_in_full(self):
        messages, _state, _error = _fetch(self.box)
        real = [m for m in messages if not m.headers_only]
        self.assertTrue(all("quote" in m.body.lower() for m in real))


class SomebodyWeKnowIsAlwaysReadProperly(unittest.TestCase):
    """The dangerous half of the optimisation. A customer whose mail system
    stamps an unsubscribe link on everything must not become a newsletter."""

    def setUp(self):
        self.box = FakeMailbox({
            1: _raw(1, sender="purchase@bigcustomer.com", unsubscribe=True),
            2: _raw(2, sender="news@shop.example", unsubscribe=True),
        })

    def test_a_known_address_is_downloaded_despite_the_header(self):
        _m, _s, _e = _fetch(self.box, always_full={"purchase@bigcustomer.com"})
        self.assertIn(1, self.box.full_fetches)
        self.assertNotIn(2, self.box.full_fetches)

    def test_knowing_the_company_is_enough(self):
        """One entry has to cover a customer's whole purchase department."""
        _m, _s, _e = _fetch(self.box, always_full={"bigcustomer.com"})
        self.assertIn(1, self.box.full_fetches)

    def test_without_that_knowledge_it_is_treated_as_a_mailshot(self):
        _m, _s, _e = _fetch(self.box, always_full=set())
        self.assertEqual(self.box.full_fetches, [])


class WhatCountsAsAMailshot(unittest.TestCase):
    """Only a statement by the SENDER counts. Nothing is guessed from the
    subject and nothing from the body, because the decision is made before the
    body exists — and a wrong guess here loses an order."""

    def test_an_unsubscribe_link_counts(self):
        self.assertTrue(inbox.says_it_is_bulk(
            inbox.Message(from_addr="a@b.com", list_unsubscribe="<http://x>")))

    def test_bulk_precedence_counts(self):
        self.assertTrue(inbox.says_it_is_bulk(
            inbox.Message(from_addr="a@b.com", precedence="bulk")))

    def test_an_out_of_office_counts(self):
        self.assertTrue(inbox.says_it_is_bulk(
            inbox.Message(from_addr="a@b.com", auto_submitted="auto-replied")))

    def test_a_do_not_reply_address_counts(self):
        for local in ("no-reply", "donotreply", "mailer-daemon", "notifications"):
            self.assertTrue(inbox.says_it_is_bulk(
                inbox.Message(from_addr=f"{local}@b.com")), local)

    def test_a_person_asking_for_a_price_does_not(self):
        self.assertFalse(inbox.says_it_is_bulk(
            inbox.Message(from_addr="raj@steelworks.co.in",
                          subject="50% off — urgent enquiry")),
            "a subject that reads like marketing is not the sender saying so")

    def test_auto_submitted_no_is_not_a_robot(self):
        """`Auto-Submitted: no` is the header explicitly saying a human sent
        it — reading it as bulk would drop real mail."""
        self.assertFalse(inbox.says_it_is_bulk(
            inbox.Message(from_addr="a@b.com", auto_submitted="no")))


# ── what the AI is asked to sort ─────────────────────────────────────────────

class TheAssistantIsNotPaidToReadNothing(unittest.TestCase):
    """The same run was rate-limited by Groq halfway through, which cost 32 of
    its 181 seconds and left 20 messages unsorted. Every message that never
    needed to be sent is a step away from that."""

    def test_a_body_less_message_is_never_sent_to_the_ai(self):
        msg = inbox.Message(uid=1, from_addr="odd@nowhere.example",
                            subject="", body="", headers_only=True)
        calls = []

        def _fail(*a, **k):
            calls.append(a)
            raise AssertionError("this message has no body to send")

        from core import router
        original = router.groq_chat
        router.groq_chat = _fail
        try:
            verdicts = triage.classify([msg], api_key="k", model="m")
        finally:
            router.groq_chat = original
        self.assertEqual(calls, [])
        self.assertNotEqual(verdicts[0].category, triage.UNSORTED)

    def test_a_mailshot_is_sorted_by_rules_alone(self):
        msg = inbox.Message(uid=1, from_addr="news@shop.example",
                            subject="50% off", list_unsubscribe="<http://x>",
                            headers_only=True)
        verdicts = triage.classify([msg], api_key="")
        self.assertEqual(verdicts[0].category, triage.PROMOTION)
        self.assertEqual(verdicts[0].source, "rule")


# ── the bookmark on disk ─────────────────────────────────────────────────────

class TheBookmarkSurvivesRestarts(unittest.TestCase):

    def test_the_new_fields_round_trip(self):
        state = inbox.State(uidvalidity=7, last_uid=900, floor_uid=700,
                            backfilled=True)
        again = inbox.State.from_dict(state.to_dict())
        self.assertEqual(again, state)

    def test_a_config_written_before_this_change_still_loads(self):
        """Existing installs have only the two old keys."""
        old = inbox.State.from_dict({"uidvalidity": 7, "last_uid": 900})
        self.assertEqual(old.last_uid, 900)
        self.assertEqual(old.floor_uid, 0)
        self.assertFalse(old.backfilled)

    def test_a_renumbered_mailbox_forgets_the_floor_too(self):
        """UIDVALIDITY changing makes every remembered position meaningless —
        including how far down we had reached."""
        box = FakeMailbox({uid: _raw(uid) for uid in range(1, 21)}, uidvalidity=999)
        stale = inbox.State(uidvalidity=1, last_uid=15, floor_uid=10)
        _m, state, _e = _fetch(box, state=stale)
        self.assertEqual(state.uidvalidity, 999)
        self.assertEqual(state.last_uid, 20, "the window is read again")

    def test_the_servers_uidvalidity_is_actually_read(self):
        """It never was. imaplib's response() returns (NAME, data), so the old
        `typ == "OK"` test could not be true and every mailbox recorded 0 —
        which is exactly what a real config held against a live Gmail account.
        With 0 on both sides the renumber check silently compares nothing."""
        box = FakeMailbox({1: _raw(1)}, uidvalidity=41234)
        _m, state, _e = _fetch(box)
        self.assertEqual(state.uidvalidity, 41234)

    def test_a_server_that_says_nothing_is_still_survivable(self):
        box = FakeMailbox({1: _raw(1)})
        box.response = lambda name: ("UIDVALIDITY", [None])
        _m, state, _e = _fetch(box)
        self.assertEqual(state.uidvalidity, 0)

    def test_a_corrupt_saved_value_does_not_crash_the_check(self):
        state = inbox.State.from_dict({"last_uid": "banana", "floor_uid": "x"})
        self.assertEqual(state.last_uid, 0)
        self.assertEqual(state.floor_uid, 0)


# ── the promises this module already made ────────────────────────────────────

class TheMailboxIsStillNeverModified(unittest.TestCase):
    """Rule 1 of the module docstring, re-checked because the fetching was
    rewritten underneath it."""

    def test_headers_are_peeked_not_read(self):
        source = (Path(__file__).resolve().parent.parent
                  / "prism_terminal" / "core" / "inbox.py").read_text(encoding="utf-8")
        self.assertIn("BODY.PEEK[HEADER]", source)
        self.assertNotIn("BODY[HEADER]\"", source.replace("BODY.PEEK[HEADER]", ""))

    def test_the_folder_is_opened_read_only(self):
        box = FakeMailbox({1: _raw(1)})
        _m, _s, error = _fetch(box)          # FakeMailbox.select asserts readonly
        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
