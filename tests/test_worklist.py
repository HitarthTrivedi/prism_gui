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

import json
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
        self.assertEqual(data, {"arrived": [], "replies": [], "orders": [],
                                "sent": []})


class OneFilePerSection(unittest.TestCase):
    """The owner asked for "a file for every section and every phase" — so
    that opening the folder by eye shows replies.json holding the replies
    and nothing else."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_each_kind_lands_in_its_own_file(self):
        worklist.append(self.folder, "arrived", [{"message_id": "<a@x>"}])
        worklist.append(self.folder, "replies", [{"message_id": "<r@x>"}])
        names = sorted(os.listdir(os.path.join(self.folder, "worklist")))
        self.assertEqual(names, ["arrived.json", "replies.json"])
        self.assertFalse(os.path.exists(
            os.path.join(self.folder, "worklist.json")))

    def test_writing_one_kind_does_not_touch_another(self):
        worklist.append(self.folder, "arrived", [{"message_id": "<a@x>"}])
        before = os.path.getmtime(worklist.path_for(self.folder, "arrived"))
        worklist.append(self.folder, "orders", [{"message_id": "<o@x>"}])
        self.assertEqual(
            os.path.getmtime(worklist.path_for(self.folder, "arrived")), before)

    def test_paths_know_the_folder(self):
        paths = CB.get_mailflow().Paths(self.folder)
        self.assertEqual(paths.worklist_dir,
                         os.path.join(self.folder, "worklist"))


class MigratingTheOldFile(unittest.TestCase):
    """An older Prism kept everything in one worklist.json. It must fold
    into the per-section files without losing a row, without doubling one,
    and without ever deleting the original."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.legacy = os.path.join(self.folder, "worklist.json")

    def _write_legacy(self, data):
        import json
        with open(self.legacy, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_the_rows_come_across_and_the_old_file_is_kept_as_a_backup(self):
        self._write_legacy({"arrived": [{"message_id": "<a@x>"}],
                            "replies": [{"message_id": "<r@x>",
                                         "resolved": True}],
                            "orders": []})
        data = worklist.load(self.folder)
        self.assertEqual([r["message_id"] for r in data["arrived"]], ["<a@x>"])
        self.assertTrue(data["replies"][0]["resolved"])
        self.assertFalse(os.path.exists(self.legacy))
        self.assertTrue(os.path.exists(self.legacy + ".bak"))

    def test_running_twice_changes_nothing(self):
        self._write_legacy({"arrived": [{"message_id": "<a@x>"}]})
        first = worklist.load(self.folder)
        second = worklist.load(self.folder)
        self.assertEqual(first, second)
        self.assertEqual(len(second["arrived"]), 1)

    def test_a_per_section_row_wins_over_the_old_file(self):
        """The per-section file may carry a newer resolved flag; the old
        file must not undo it."""
        worklist.append(self.folder, "replies", [{"message_id": "<r@x>"}])
        worklist.resolve(self.folder, "replies", "<r@x>")
        self._write_legacy({"replies": [{"message_id": "<r@x>",
                                         "resolved": False}]})
        data = worklist.load(self.folder)
        self.assertEqual(len(data["replies"]), 1)
        self.assertTrue(data["replies"][0]["resolved"])

    def test_an_unreadable_old_file_is_left_exactly_where_it_is(self):
        with open(self.legacy, "w", encoding="utf-8") as f:
            f.write("{ not json")
        data = worklist.load(self.folder)
        self.assertEqual(data["arrived"], [])
        self.assertTrue(os.path.exists(self.legacy))

    def test_the_owners_real_shape_migrates_cleanly(self):
        """The exact key set the previous release wrote."""
        self._write_legacy({"arrived": [
            {"message_id": f"<{i}@x>", "from_name": "A", "from_addr": "a@b.c",
             "subject": f"s{i}", "date": "2026-08-25", "category": "other",
             "reason": "", "source": "rule"} for i in range(19)],
            "replies": [], "orders": []})
        data = worklist.load(self.folder)
        self.assertEqual(len(data["arrived"]), 19)
        self.assertEqual(data["sent"], [])


class TheSentLog(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_two_reminders_on_one_day_are_two_rows(self):
        for _ in range(2):
            worklist.log_sent(self.folder, "reminder", to="a@b.c",
                              subject="Reminder", inquiry_no="INQ/1")
        data = worklist.load(self.folder)
        self.assertEqual(len(data["sent"]), 2)

    def test_it_is_a_log_with_no_resolved_flag(self):
        worklist.log_sent(self.folder, "quotation", to="a@b.c",
                          subject="Q", inquiry_no="INQ/1", quotation_no="QTN/1")
        row = worklist.load(self.folder)["sent"][0]
        self.assertNotIn("resolved", row)
        for key in ("kind", "date", "time", "to", "subject", "inquiry_no",
                    "quotation_no"):
            self.assertIn(key, row)

    def test_sent_for_reads_back_one_inquiry_oldest_first(self):
        from datetime import datetime
        worklist.log_sent(self.folder, "quotation", to="a@b.c", subject="Q",
                          inquiry_no="INQ/1", when=datetime(2026, 8, 24, 9, 0))
        worklist.log_sent(self.folder, "reminder", to="a@b.c", subject="R",
                          inquiry_no="INQ/1", when=datetime(2026, 8, 25, 9, 0))
        worklist.log_sent(self.folder, "reminder", to="x@y.z", subject="R",
                          inquiry_no="INQ/2")
        rows = worklist.sent_for(worklist.load(self.folder), "INQ/1")
        self.assertEqual([r["kind"] for r in rows], ["quotation", "reminder"])
        self.assertEqual(rows[0]["date"], "2026-08-24")


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


class WhatTheWorkingFileCapEvictsIsArchivedNotDeleted(unittest.TestCase):
    """The bug this guards against: the working file's cap used to just
    drop the oldest rows once a mailbox had sorted enough mail — "All mail"
    quietly showed fewer messages than had ever arrived. Now the cap still
    keeps the working file small, but nothing it evicts is gone."""

    def test_arrived_evictions_land_in_the_archive_file(self):
        folder = tempfile.mkdtemp()
        entries = [{"message_id": f"<{i}@x>", "date": "2026-08-01"}
                   for i in range(worklist.ARRIVED_KEEP + 5)]
        worklist.append(folder, "arrived", entries)

        data = worklist.load(folder)
        self.assertEqual(len(data["arrived"]), worklist.ARRIVED_KEEP)
        # The oldest 5 are the ones evicted — still present, just moved.
        self.assertTrue(worklist.has_archive(folder, "arrived"))
        archive_path = worklist.archive_path_for(folder, "arrived")
        with open(archive_path, "r", encoding="utf-8") as f:
            archived = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(archived), 5)
        self.assertEqual([r["message_id"] for r in archived],
                         [f"<{i}@x>" for i in range(5)])

    def test_no_archive_file_before_the_cap_is_reached(self):
        folder = tempfile.mkdtemp()
        worklist.append(folder, "arrived", [{"message_id": "<a@x>"}])
        self.assertFalse(worklist.has_archive(folder, "arrived"))


if __name__ == "__main__":
    unittest.main()
