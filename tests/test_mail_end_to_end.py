"""
The whole "Check my mail" flow, run for real, several times over
────────────────────────────────────────────────────────────────
Each earlier test file pins one part. This one runs the parts together the way
pressing the button does, because every bug in this feature so far has lived in
the joins rather than in any single function:

  · a first check that fetched the oldest mail and showed nothing useful
  · a bookmark that advanced but never came back for what it passed over
  · an inquiry that was fetched, was not a mailshot, and still never appeared
  · a bookmark wiped on every check by a UIDVALIDITY the server never sent

The mailbox below is the shape of a real one: mostly mailshots, a couple of
real inquiries, a reply on an existing thread, and an order.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prism_terminal"))

from core import inbox, mailflow, triage  # noqa: E402
from test_inbox_fetch import FakeMailbox, _connected, CFG  # noqa: E402


def mail(uid, sender, subject, body="", **headers):
    lines = [f"From: {sender}", f"Subject: {subject}",
             f"Message-ID: <{uid}@example.com>",
             "Date: Mon, 24 Aug 2026 10:00:00 +0530",
             "Content-Type: text/plain; charset=utf-8"]
    for key, value in headers.items():
        lines.append(f"{key.replace('_', '-')}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n" + (body or "Regards")).encode()


def a_mailshot(uid, n):
    return mail(uid, f"news{n}@shop.example", f"{n}0% off everything",
                List_Unsubscribe="<https://x/u>")


class TheFlowWeAgreed(unittest.TestCase):
    """newest first · nothing lost · nothing re-read · no AI needed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = mailflow.Paths(self.tmp.name)
        self.know = triage.Knowledge(own_domains={"acme.co.in"})
        # 300 mailshots — more than one check may take, so there is a real
        # backlog — with two genuine inquiries at the newest end.
        self.box_mail = {uid: a_mailshot(uid, uid % 9) for uid in range(1, 301)}
        self.box_mail[299] = mail(
            299, "parthsoni49585@gmail.com",
            "Enquiry for compression springs - request for quotation",
            "Please quote for 5000 nos.")
        self.box_mail[300] = mail(
            300, "buyer@newcustomer.co.in", "RFQ - mild steel brackets",
            "Kindly quote your best price for 200 pcs.")

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, box, state, **kw):
        with _connected(box):
            return mailflow.check(CFG, self.paths, state=state,
                                  knowledge=self.know, local_only=True, **kw)

    # -- the first press of the button ------------------------------------

    def test_the_first_check_finds_the_real_inquiries_immediately(self):
        """Not on the fourth press. This is the whole complaint."""
        box = FakeMailbox(self.box_mail)
        result = self._check(box, None)
        self.assertEqual(result.error, "")
        subjects = [i.message.subject for i in result.new_inquiries]
        self.assertEqual(len(subjects), 2, f"got {subjects}")
        self.assertTrue(any("compression springs" in s for s in subjects))

    def test_it_costs_almost_nothing_to_do_so(self):
        box = FakeMailbox(self.box_mail)
        self._check(box, None)
        self.assertLessEqual(len(box.full_fetches), 5,
                             "300 messages, and only the plausible ones "
                             "should have been downloaded whole")

    def test_no_ai_was_needed(self):
        box = FakeMailbox(self.box_mail)
        result = self._check(box, None)
        sources = {v.source for _m, v in result.sorted_mail}
        self.assertNotIn("ai", sources)
        self.assertNotIn("failed", sources)

    def test_the_register_has_the_rows_afterwards(self):
        box = FakeMailbox(self.box_mail)
        self._check(box, None)
        from core import register
        rows = register.load(self.paths.register_csv)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.get("Inquiry no") for r in rows))

    # -- pressing it again ------------------------------------------------

    def test_a_second_check_with_no_new_mail_does_almost_nothing(self):
        box = FakeMailbox(self.box_mail)
        first = self._check(box, None)

        again = FakeMailbox(self.box_mail)
        second = self._check(again, first.state)
        self.assertEqual(second.new_inquiries, [])
        self.assertLessEqual(len(again.full_fetches), 1,
                             "an idle mailbox must not be re-downloaded")

    def test_the_same_inquiry_is_never_registered_twice(self):
        from core import register
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state
        for _ in range(3):
            box = FakeMailbox(self.box_mail)
            state = self._check(box, state).state
        rows = register.load(self.paths.register_csv)
        self.assertEqual(len(rows), 2, "checking again must not duplicate rows")

    def test_new_mail_arriving_later_is_found(self):
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state

        later = dict(self.box_mail)
        later[301] = mail(301, "third@buyer.example", "Enquiry - springs",
                          "Please quote.")
        box2 = FakeMailbox(later)
        result = self._check(box2, state)
        self.assertEqual(len(result.new_inquiries), 1)
        self.assertEqual(result.new_inquiries[0].message.uid, 301)

    # -- the backlog ------------------------------------------------------

    def test_older_mail_is_caught_up_without_being_re_read(self):
        """The floor walks down; the top never moves back."""
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None, ).state
        tops, floors = [state.last_uid], [state.floor_uid]
        for _ in range(6):
            box = FakeMailbox(self.box_mail)
            state = self._check(box, state).state
            tops.append(state.last_uid)
            floors.append(state.floor_uid)
        self.assertEqual(set(tops), {300}, "the top must stay at the top")
        self.assertEqual(floors, sorted(floors, reverse=True),
                         "the floor must only ever move down")

    def test_every_message_is_seen_exactly_once(self):
        seen = []
        state = None
        for _ in range(25):
            box = FakeMailbox(self.box_mail)
            result = self._check(box, state)
            state = result.state
            seen.extend(m.uid for m, _v in result.sorted_mail)
            if state.backfilled:
                break
        self.assertEqual(sorted(seen), sorted(self.box_mail),
                         "every message once — none skipped, none repeated")

    # -- the things that broke before -------------------------------------

    def test_a_server_that_omits_uidvalidity_keeps_its_bookmark(self):
        """It used to compare the remembered 1 against a missing 0, call that
        a renumber, and wipe the bookmark — re-reading the whole window on
        every single check."""
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state
        self.assertTrue(state.last_uid)

        silent = FakeMailbox(self.box_mail)
        silent.response = lambda name: ("UIDVALIDITY", [None])
        after = self._check(silent, state)
        self.assertEqual(after.state.last_uid, state.last_uid,
                         "a silent server must not reset the bookmark")
        self.assertEqual(after.state.uidvalidity, state.uidvalidity,
                         "and the remembered value must survive")
        self.assertLessEqual(len(silent.full_fetches), 1)

    def test_a_genuine_renumber_does_start_again(self):
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state
        moved = FakeMailbox(self.box_mail, uidvalidity=987654)
        after = self._check(moved, state)
        self.assertEqual(after.state.uidvalidity, 987654)
        self.assertEqual(after.state.last_uid, 300)

    # -- who waits for the backlog ----------------------------------------

    def test_a_watched_check_does_not_wait_for_old_mail(self):
        """What was agreed: newest immediately, the rest "not while you're
        waiting". Every check was doing 60 backlog messages, which is why a
        press of the button still took over a minute."""
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state

        later = dict(self.box_mail)
        later[301] = mail(301, "someone@buyer.example", "Enquiry - springs",
                          "Please quote.")
        watched = FakeMailbox(later)
        result = self._check(watched, state, catch_up_with_new=False)

        self.assertEqual(len(result.new_inquiries), 1, "the new mail is shown")
        fetched = [m.uid for m, _v in result.sorted_mail]
        self.assertEqual(fetched, [301],
                         "and nothing older was fetched to make them wait")

    def test_but_an_idle_check_uses_the_moment_to_catch_up(self):
        """The timer is off until somebody turns it on, so the backlog cannot
        depend on it. When there is nothing new, the person is waiting anyway
        and that moment is spent usefully."""
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state
        before = state.floor_uid

        idle = FakeMailbox(self.box_mail)
        result = self._check(idle, state, catch_up_with_new=False)
        self.assertEqual(result.new_inquiries, [])
        self.assertLess(result.state.floor_uid, before,
                        "an idle press should still move the backlog along")

    def test_a_timer_tick_always_catches_up(self):
        box = FakeMailbox(self.box_mail)
        state = self._check(box, None).state
        before = state.floor_uid

        later = dict(self.box_mail)
        later[301] = mail(301, "someone@buyer.example", "Hello", "Thanks.")
        tick = FakeMailbox(later)
        result = self._check(tick, state, catch_up_with_new=True)
        self.assertLess(result.state.floor_uid, before,
                        "nobody is watching, so the old mail gets read")

    def test_the_backlog_still_finishes_with_the_timer_switched_off(self):
        """End to end on the path a customer who never opens Setup takes."""
        state, rounds = None, 0
        while rounds < 25:
            box = FakeMailbox(self.box_mail)
            state = self._check(box, state, catch_up_with_new=False).state
            rounds += 1
            if state.backfilled:
                break
        self.assertTrue(state.backfilled,
                        "pressing the button must eventually clear the window")

    def test_a_rate_limited_sort_is_reported_not_swallowed(self):
        """Nothing may be dropped in silence."""
        from core import router
        original = router.groq_chat
        router.groq_chat = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("Groq is rate-limiting your API key."))
        try:
            box = FakeMailbox({1: mail(1, "who@unknown.example",
                                       "About the thing", "See attached.")})
            with _connected(box):
                result = mailflow.check(dict(CFG, api_key="k"), self.paths,
                                        knowledge=self.know)
        finally:
            router.groq_chat = original
        self.assertEqual(len(result.unsorted_by_failure), 1)
        self.assertIn("couldn't be sorted", result.headline())


class ManyMailboxesKeepTheirOwnPlace(unittest.TestCase):
    """Each account has its own bookmark. Mixing them up would re-import one
    mailbox and skip another."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = mailflow.Paths(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_accounts_do_not_share_a_bookmark(self):
        sales = FakeMailbox({n: a_mailshot(n, 1) for n in range(1, 31)})
        info = FakeMailbox({n: a_mailshot(n, 2) for n in range(1, 11)})

        with _connected(sales):
            a = mailflow.check(CFG, self.paths, state=None, local_only=True)
        with _connected(info):
            b = mailflow.check(CFG, self.paths, state=None, local_only=True)

        self.assertEqual(a.state.last_uid, 30)
        self.assertEqual(b.state.last_uid, 10)
        self.assertNotEqual(a.state.last_uid, b.state.last_uid)


if __name__ == "__main__":
    unittest.main()
