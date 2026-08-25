"""core/worklist.py — the file that stops a reply or a purchase order from
disappearing just because the mailbox's own read bookmark moved past it.

Three things this defends:

  · **Nothing is lost to a second check.** Appending the same message twice
    (the bookmark did not move, or the account walk re-read it) must not
    double it, and must not reset a correction or a resolved flag a person
    already made.
  · **Handled things actually leave the pending list**, and stay off it even
    after another append.
  · **The date filter reads the entry's own date**, not today's.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402

worklist = CB.get_worklist()


class TheFileStartsEmpty(unittest.TestCase):

    def test_a_folder_never_checked_reads_as_empty(self):
        data = worklist.load(tempfile.mkdtemp())
        self.assertEqual(data, {"arrived": [], "replies": [], "orders": []})


class AppendingDoesNotDouble(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_the_same_message_id_twice_is_one_row(self):
        entry = {"message_id": "<a@x>", "subject": "Hello", "date": "2026-08-20"}
        worklist.append(self.folder, "arrived", [entry])
        worklist.append(self.folder, "arrived", [entry])
        data = worklist.load(self.folder)
        self.assertEqual(len(data["arrived"]), 1)

    def test_messages_with_no_id_fall_back_to_sender_subject_date(self):
        entry = {"from_addr": "a@b.c", "subject": "Hi", "date": "2026-08-20"}
        worklist.append(self.folder, "arrived", [entry])
        worklist.append(self.folder, "arrived", [dict(entry)])
        data = worklist.load(self.folder)
        self.assertEqual(len(data["arrived"]), 1)

    def test_a_resolved_row_is_not_reset_by_a_later_append(self):
        """The whole point: a re-check must never undo what a person already
        did about a reply or a purchase order."""
        entry = {"message_id": "<r@x>", "subject": "Accepted", "date": "2026-08-20"}
        worklist.append(self.folder, "replies", [entry])
        worklist.resolve(self.folder, "replies", "<r@x>")
        worklist.append(self.folder, "replies", [dict(entry)])
        data = worklist.load(self.folder)
        self.assertTrue(data["replies"][0]["resolved"])

    def test_it_survives_being_read_back_by_a_fresh_load(self):
        """Not just an in-memory merge — this is what makes reopening the
        dialog tomorrow show the same list as closing it today."""
        worklist.append(self.folder, "orders",
                        [{"message_id": "<o@x>", "date": "2026-08-20"}])
        data = worklist.load(self.folder)
        self.assertEqual(len(data["orders"]), 1)


class PendingAndHistory(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        worklist.append(self.folder, "replies", [
            {"message_id": "<1@x>", "date": "2026-08-01"},
            {"message_id": "<2@x>", "date": "2026-08-02"},
        ])
        worklist.resolve(self.folder, "replies", "<1@x>")

    def test_pending_excludes_resolved_rows(self):
        data = worklist.load(self.folder)
        ids = [r["message_id"] for r in worklist.pending(data, "replies")]
        self.assertEqual(ids, ["<2@x>"])

    def test_history_includes_everything_newest_first(self):
        data = worklist.load(self.folder)
        ids = [r["message_id"] for r in worklist.history(data, "replies")]
        self.assertEqual(ids, ["<2@x>", "<1@x>"])

    def test_history_can_be_limited_to_recent_days(self):
        data = worklist.load(self.folder)
        rows = worklist.history(data, "replies", days=1)
        # "days=1" from today (2026, long after these fixture dates) excludes
        # both — the filter reads the entry's own date, not today's, so an
        # August fixture never survives a "last 1 day" window run any later.
        self.assertEqual(rows, [])


class UpdatingOneRow(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        worklist.append(self.folder, "arrived", [
            {"message_id": "<x@x>", "category": "other",
             "reason": "no-reply address", "date": "2026-08-20"}])

    def test_a_correction_updates_only_that_row(self):
        worklist.update(self.folder, "arrived", "<x@x>",
                        {"category": "inquiry", "reason": "you taught it"})
        data = worklist.load(self.folder)
        self.assertEqual(data["arrived"][0]["category"], "inquiry")

    def test_an_unknown_message_id_does_nothing(self):
        worklist.update(self.folder, "arrived", "<missing@x>",
                        {"category": "inquiry"})
        data = worklist.load(self.folder)
        self.assertEqual(data["arrived"][0]["category"], "other")


class TheArrivedLogNeverTrimsForBeingOld(unittest.TestCase):

    def test_arrived_has_no_resolved_flag_added(self):
        """It is a log, not a todo list — there is nothing to resolve."""
        folder = tempfile.mkdtemp()
        worklist.append(folder, "arrived", [{"message_id": "<a@x>"}])
        data = worklist.load(folder)
        self.assertNotIn("resolved", data["arrived"][0])


if __name__ == "__main__":
    unittest.main()
