"""core/history.py — the one file that reads as the whole story of an
inquiry: the enquiry as it arrived, every quotation and reminder sent, every
reply and PO that came back, and how it was decided. Plain text, append-only,
in one folder — see the module docstring for why.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402

history = CB.get_history()


class OneEntryPerEvent(unittest.TestCase):

    def test_a_fresh_folder_gets_the_file_and_the_content(self):
        folder = tempfile.mkdtemp()
        history.append(folder, "Enquiry received",
                       who="Rajesh <rajesh@acme.in>",
                       subject="Need 5000 compression springs",
                       body="Please quote your best rate.",
                       when=datetime(2026, 8, 30, 23, 27))
        path = history.path_for(folder)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("30-08-2026 23:27", text)
        self.assertIn("Enquiry received", text)
        self.assertIn("Rajesh <rajesh@acme.in>", text)
        self.assertIn("Subject: Need 5000 compression springs", text)
        self.assertIn("Please quote your best rate.", text)

    def test_events_accumulate_in_the_order_written(self):
        folder = tempfile.mkdtemp()
        history.append(folder, "Enquiry received", body="first")
        history.append(folder, "Quotation sent", body="second")
        history.append(folder, "Order accepted — converted", body="third")
        with open(history.path_for(folder), encoding="utf-8") as f:
            text = f.read()
        self.assertLess(text.index("first"), text.index("second"))
        self.assertLess(text.index("second"), text.index("third"))

    def test_missing_folder_is_created(self):
        parent = tempfile.mkdtemp()
        folder = os.path.join(parent, "not-yet-on-disk")
        history.append(folder, "Enquiry received", body="hello")
        self.assertTrue(os.path.exists(history.path_for(folder)))

    def test_no_folder_does_nothing_and_never_raises(self):
        history.append("", "Enquiry received", body="hello")   # must not raise

    def test_a_blank_body_still_records_the_event(self):
        folder = tempfile.mkdtemp()
        history.append(folder, "Marked lost", body="")
        with open(history.path_for(folder), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Marked lost", text)


class ReadingItBack(unittest.TestCase):

    def test_reads_back_what_was_appended(self):
        folder = tempfile.mkdtemp()
        history.append(folder, "Enquiry received", body="hello there")
        self.assertIn("hello there", history.read(folder))
        self.assertIn("Enquiry received", history.read(folder))

    def test_a_folder_with_nothing_recorded_reads_as_empty(self):
        self.assertEqual(history.read(tempfile.mkdtemp()), "")

    def test_no_folder_reads_as_empty_and_never_raises(self):
        self.assertEqual(history.read(""), "")


class ParsingItBackIntoEntries(unittest.TestCase):
    """entries() is a view onto append()'s own format — the screen draws
    each event as a card from this, but the text file stays the record
    even if this parser were wrong or never called."""

    def test_one_full_entry_round_trips(self):
        folder = tempfile.mkdtemp()
        history.append(folder, "Enquiry received",
                       who="Rajesh <rajesh@acme.in>",
                       subject="Need 5000 compression springs",
                       body="Please quote your\nbest rate.",
                       when=datetime(2026, 8, 30, 23, 27))
        entries = history.entries(folder)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["when"], "30-08-2026 23:27")
        self.assertEqual(e["event"], "Enquiry received")
        self.assertEqual(e["who"], "Rajesh <rajesh@acme.in>")
        self.assertEqual(e["subject"], "Need 5000 compression springs")
        self.assertEqual(e["body"], "Please quote your\nbest rate.")

    def test_an_entry_with_no_who_or_subject_still_parses(self):
        """The correction entry, and any event with only a body —
        _mark_lost()'s reason, for one — has neither."""
        folder = tempfile.mkdtemp()
        history.append(folder, "Marked lost", body="Rate too high")
        entries = history.entries(folder)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["who"], "")
        self.assertEqual(entries[0]["subject"], "")
        self.assertEqual(entries[0]["body"], "Rate too high")

    def test_several_entries_come_back_oldest_first(self):
        folder = tempfile.mkdtemp()
        history.append(folder, "Enquiry received", body="first")
        history.append(folder, "Quotation sent", body="second")
        history.append(folder, "Order accepted — converted", body="third")
        entries = history.entries(folder)
        self.assertEqual([e["body"] for e in entries],
                         ["first", "second", "third"])
        self.assertEqual([e["event"] for e in entries],
                         ["Enquiry received", "Quotation sent",
                          "Order accepted — converted"])

    def test_a_body_containing_the_separator_look_alike_does_not_split(self):
        """The rule line is 70 "=" characters with nothing else on the
        line — a customer's own "====" flourish in a reply must not be
        mistaken for it."""
        folder = tempfile.mkdtemp()
        history.append(folder, "Reply received", body="==== important ====")
        entries = history.entries(folder)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["body"], "==== important ====")

    def test_an_empty_folder_has_no_entries(self):
        self.assertEqual(history.entries(tempfile.mkdtemp()), [])


if __name__ == "__main__":
    unittest.main()
