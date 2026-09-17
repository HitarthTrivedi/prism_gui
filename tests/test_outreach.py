"""The bridge between cold outreach and the inquiry register.

One book: a lead the Leads screen mails becomes a row in `inquiries.csv`,
the sales team edits that same file in Excel all day, and the moment
somebody answers the ordinary inquiry machinery takes over.

The tests that matter most here are not the happy path -- they are the two
ways this design can silently destroy data:

  · **the clobber.** `register.save()` writes the whole file from whatever
    list it is handed. A screen holding a snapshot, and a push writing to
    the same file, lose each other's rows with no error at all.
  · **the resurrection.** The fix for the clobber is to merge from disk on
    every save -- which is exactly wrong for a delete, because the row is
    still on the disk and comes straight back.

Both are pinned below. Neither raises when it goes wrong, so a test is the
only thing that would ever notice.
"""
from __future__ import annotations

import datetime
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                  # noqa: E402

import core_bridge as CB                                    # noqa: E402
import outreach                                             # noqa: E402

# One application for the module, made on import -- the same shape as
# tests/test_inquiry_ui.py:47. Built here rather than in setUpClass so
# a shuffled run order cannot construct it inside another test's session.
_app = QApplication.instance() or QApplication([])


def _cfg(folder: str) -> dict:
    return {"inquiry": {"folder": folder}}


def _lead(email: str, company: str = "Acme Steel", name: str = "Ravi",
          product: str = "gears") -> dict:
    return {"company": company, "name": name, "email": email,
            "product": product}


class OutreachTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = _cfg(self.folder)
        self.register = CB.get_register()
        self.path = outreach.register_path(self.cfg)

    def rows(self):
        return self.register.load(self.path)

    def save(self, rows):
        self.register.save(rows, self.path)


class TheBookIsNeverClobbered(OutreachTest):
    """The whole reason `save_merging` and `drop_row` exist."""

    def test_a_push_survives_a_save_from_an_older_snapshot(self):
        outreach.push_leads(self.cfg, [_lead("first@acme.in")])
        snapshot = self.rows()                  # what a screen would hold
        outreach.push_leads(self.cfg, [_lead("second@tata.in")])
        # The screen now saves the list it has been holding all along.
        merged, rescued = outreach.save_merging(snapshot, self.path)
        emails = {r["Email"] for r in self.rows()}
        self.assertIn("second@tata.in", emails,
                      "a row pushed while the screen was open was erased")
        self.assertEqual(rescued, 1)
        self.assertEqual(len(merged), 2)

    def test_an_edit_and_a_push_both_survive(self):
        outreach.push_leads(self.cfg, [_lead("first@acme.in")])
        snapshot = self.rows()
        snapshot[0]["Notes"] = "rang them"
        outreach.push_leads(self.cfg, [_lead("second@tata.in")])
        outreach.save_merging(snapshot, self.path)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        first = [r for r in rows if r["Email"] == "first@acme.in"][0]
        self.assertEqual(first["Notes"], "rang them")

    def test_a_deleted_row_does_not_come_back(self):
        """The one case where merging from disk is the wrong answer."""
        outreach.push_leads(self.cfg, [_lead("gone@acme.in"),
                                       _lead("stays@tata.in")])
        rows = self.rows()
        doomed = [r for r in rows if r["Email"] == "gone@acme.in"][0]
        self.assertTrue(outreach.drop_row(self.path, doomed["Inquiry no"]))
        # A screen that still holds the deleted row now saves.
        outreach.save_merging(rows, self.path)
        self.assertNotIn("gone@acme.in", {r["Email"] for r in self.rows()})
        self.assertIn("stays@tata.in", {r["Email"] for r in self.rows()})

    def test_two_threads_pushing_lose_nobody(self):
        def push(n):
            outreach.push_leads(self.cfg, [_lead("p%d@acme.in" % n)])
        threads = [threading.Thread(target=push, args=(n,)) for n in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = self.rows()
        self.assertEqual(len(rows), 20)
        self.assertEqual(len({r["Inquiry no"] for r in rows}), 20,
                         "two rows were handed the same inquiry number")

    def test_a_push_stands_aside_while_the_mail_is_being_checked(self):
        """mailflow.check holds the register across an IMAP fetch."""
        outreach.begin_check()
        try:
            added, _ = outreach.push_leads(self.cfg, [_lead("x@acme.in")])
        finally:
            outreach.end_check()
        self.assertEqual(added, 0)
        self.assertEqual(self.rows(), [])
        added, _ = outreach.push_leads(self.cfg, [_lead("x@acme.in")])
        self.assertEqual(added, 1)


class TheMergeKeyBlindSpot(OutreachTest):
    """Why every outreach row is given a number, and not for decoration."""

    def test_unnumbered_rows_from_one_address_collapse(self):
        """The engine behaviour this design has to work around."""
        blank = self.register.blank_row()
        blank["Email"] = "same@acme.in"
        other = dict(blank)
        merged, added, skipped = self.register.merge_in([], [blank, other])
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)

    def test_pushed_leads_are_numbered_so_they_never_collapse(self):
        outreach.push_leads(self.cfg, [_lead("a@acme.in", product=""),
                                       _lead("b@acme.in", product="")])
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r["Inquiry no"] for r in rows}), 2)

    def test_pushing_the_same_person_twice_adds_one_row(self):
        outreach.push_leads(self.cfg, [_lead("once@acme.in")])
        added, skipped = outreach.push_leads(self.cfg, [_lead("once@acme.in")])
        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(len(self.rows()), 1)


class TheRowsTheSalesTeamTypes(OutreachTest):

    def _typed(self, email="typed@newco.in"):
        rows = self.rows()
        blank = self.register.blank_row()
        blank["Email"] = email
        rows.append(blank)
        self.save(rows)
        return rows

    def test_a_row_with_only_an_address_is_numbered_and_stamped(self):
        rows = self._typed()
        self.assertEqual(outreach.adopt_hand_rows(rows), 1)
        typed = [r for r in rows if r["Email"] == "typed@newco.in"][0]
        self.assertTrue(typed["Inquiry no"])
        self.assertEqual(typed[outreach.SOURCE], outreach.SALES)
        self.assertEqual(typed[outreach.STAGE], outreach.TO_EMAIL)

    def test_adopting_twice_changes_nothing(self):
        rows = self._typed()
        outreach.adopt_hand_rows(rows)
        number = rows[-1]["Inquiry no"]
        self.assertEqual(outreach.adopt_hand_rows(rows), 0)
        self.assertEqual(rows[-1]["Inquiry no"], number)

    def test_a_row_prism_wrote_is_not_mistaken_for_a_typed_one(self):
        outreach.push_leads(self.cfg, [_lead("ours@acme.in")])
        rows = self.rows()
        self.assertEqual(outreach.adopt_hand_rows(rows), 0)

    def test_a_typed_row_is_queued_not_sent(self):
        rows = self._typed()
        outreach.adopt_hand_rows(rows)
        self.assertEqual([r["Email"] for r in outreach.queued(rows)],
                         ["typed@newco.in"])

    def test_do_not_email_keeps_a_row_out_of_the_queue(self):
        rows = self._typed()
        outreach.adopt_hand_rows(rows)
        rows[-1][outreach.DO_NOT_EMAIL] = "x"
        self.assertEqual(outreach.queued(rows), [])


class TheOutreachScheduleIsNotTheQuotationSchedule(OutreachTest):
    """A cold lead must never be chased with quotation copy."""

    def _emailed(self, days_ago: int, touches: int = 1):
        when = datetime.date.today() - datetime.timedelta(days=days_ago)
        row = self.register.blank_row()
        row.update({"Inquiry no": "INQ/25-26/0001", "Email": "x@acme.in",
                    "Status": self.register.NEW,
                    "Last contact": when.strftime("%d-%m-%Y"),
                    outreach.SOURCE: outreach.OUTREACH,
                    outreach.STAGE: outreach.EMAILED,
                    outreach.TOUCHES: str(touches)})
        return row

    def test_a_cold_lead_is_never_due_a_quotation_reminder(self):
        row = self._emailed(days_ago=30)
        self.assertEqual(self.register.awaiting_followup([row]), [])

    def test_a_nudge_does_not_pretend_a_quotation_exists(self):
        row = self._emailed(days_ago=5)
        outreach.note_touch(row)
        self.assertEqual(row["Status"], self.register.NEW,
                         "note_reminder's side-effect leaked into outreach")
        self.assertEqual(row.get("Reminders sent", ""), "")
        self.assertEqual(outreach.touches_of(row), 2)

    def test_a_row_is_due_once_the_gap_has_passed(self):
        self.assertEqual(
            len(outreach.due_touches([self._emailed(days_ago=5)],
                                     after_days=3, max_touches=2)), 1)
        self.assertEqual(
            outreach.due_touches([self._emailed(days_ago=1)],
                                 after_days=3, max_touches=2), [])

    def test_nudging_stops_at_the_maximum(self):
        self.assertEqual(
            outreach.due_touches([self._emailed(days_ago=30, touches=2)],
                                 after_days=3, max_touches=2), [])

    def test_a_reply_stops_the_nudges(self):
        row = self._emailed(days_ago=30)
        outreach.mark_replied(row)
        self.assertEqual(outreach.due_touches([row], after_days=3,
                                              max_touches=2), [])

    def test_do_not_email_stops_the_nudges(self):
        row = self._emailed(days_ago=30)
        row[outreach.DO_NOT_EMAIL] = "no"
        self.assertEqual(outreach.due_touches([row], after_days=3,
                                              max_touches=2), [])

    def test_junk_in_the_touches_cell_does_not_stop_the_schedule(self):
        row = self._emailed(days_ago=30)
        row[outreach.TOUCHES] = "two"
        self.assertEqual(len(outreach.due_touches([row], after_days=3,
                                                  max_touches=2)), 1)


class TheHandoffBackToTheOrdinaryFlow(OutreachTest):

    def test_a_cold_lead_is_matchable_by_address_when_it_replies(self):
        """There is no Message-ID to store, so this fallback carries it."""
        outreach.push_leads(self.cfg, [_lead("ravi@acme.in")])
        rows = self.rows()

        class _Msg:
            message_id = ""
            references = []
            in_reply_to = ""
            from_addr = "ravi@acme.in"

        found = self.register.find_by_thread(rows, _Msg())
        self.assertIsNotNone(found, "a reply could not find its outreach row")
        self.assertEqual(found["Email"], "ravi@acme.in")

    def test_a_replied_row_stops_being_pending(self):
        outreach.push_leads(self.cfg, [_lead("ravi@acme.in")])
        row = self.rows()[0]
        self.assertTrue(outreach.is_pending(row))
        outreach.mark_replied(row)
        self.assertFalse(outreach.is_pending(row))
        self.assertEqual(row["Status"], self.register.NEW,
                         "a replied lead must read as an unquoted inquiry")


class TheSheetSurvivesTheSalesTeam(OutreachTest):

    def test_a_column_somebody_added_by_hand_survives_a_push(self):
        rows = self.rows()
        blank = self.register.blank_row()
        blank["Email"] = "old@acme.in"
        blank["Party Name"] = "Acme Steel Pvt Ltd"
        rows.append(blank)
        self.save(rows)
        outreach.push_leads(self.cfg, [_lead("new@tata.in")])
        kept = [r for r in self.rows() if r["Email"] == "old@acme.in"][0]
        self.assertEqual(kept["Party Name"], "Acme Steel Pvt Ltd")

    def test_the_outreach_columns_round_trip(self):
        outreach.push_leads(self.cfg, [_lead("ravi@acme.in")])
        row = self.rows()[0]
        for column in outreach.COLUMNS:
            self.assertIn(column, row)

    def test_the_guide_is_written_once_and_never_rewritten(self):
        first = outreach.write_sheet_guide(self.cfg)
        self.assertTrue(os.path.exists(first))
        with open(first, "a", encoding="utf-8") as f:
            f.write("\nsomebody added a note\n")
        outreach.write_sheet_guide(self.cfg)
        with open(first, encoding="utf-8") as f:
            self.assertIn("somebody added a note", f.read())

    def test_there_is_no_book_when_inquiry_is_not_set_up(self):
        self.assertEqual(outreach.register_path({}), "")
        self.assertEqual(outreach.push_leads({}, [_lead("x@acme.in")]), (0, 0))
        self.assertEqual(outreach.write_sheet_guide({}), "")


class TheModuleStaysNeutral(unittest.TestCase):
    """It is shared by two add-ons, so it may depend on neither."""

    def test_it_imports_no_add_on_and_no_ui(self):
        import ast
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(here, "outreach.py"), encoding="utf-8").read()
        names = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for banned in ("PySide6", "addons", "prospector"):
            self.assertFalse([n for n in names if n.split(".")[0] == banned],
                             "outreach.py imported %s" % banned)

    def test_it_reaches_the_engine_only_through_the_bridge(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(here, "outreach.py"), encoding="utf-8").read()
        self.assertNotIn("from core import", source)
        self.assertIn("import core_bridge", source)


class TheScreenKeepsColdLeadsOutOfTheWay(unittest.TestCase):
    """The day's work must not be buried under a few hundred strangers.

    Built against the real InquiryDialog rather than a stub: the filtering
    is three lines spread over two render methods, and the thing worth
    pinning is what a person actually sees on each tab.
    """

    def setUp(self):
        from addons.inquiry.dialog import InquiryDialog
        self.folder = tempfile.mkdtemp()
        self.cfg = {"inquiry": {"folder": self.folder, "accounts": [],
                                "auto_minutes": 0}}
        reg = CB.get_register()
        path = outreach.register_path(self.cfg)
        outreach.push_leads(self.cfg, [_lead("cold@tata.in", "Tata Steel")])
        rows = reg.load(path)
        for number, customer, status in (
                ("INQ/26-27/0098", "Real Customer", reg.NEW),
                ("INQ/26-27/0099", "Won Customer", reg.CONVERTED)):
            row = reg.blank_row()
            row.update({"Inquiry no": number, "Customer": customer,
                        "Email": customer.split()[0].lower() + "@x.in",
                        "Status": status, "Product asked": "springs"})
            rows.append(row)
        reg.save(rows, path)
        self.dialog = InquiryDialog(self.cfg)
        self.dialog._refresh_register()

    def tearDown(self):
        # Shut it down properly: closeEvent stops the auto timer and joins
        # any worker. A dialog left alive past its test is how a stray
        # thread ends up writing somewhere a test has no business writing.
        self.dialog._closed = True
        self.dialog.close()
        self.dialog.deleteLater()

    def _chip(self, value):
        self.dialog.register_chips.set_current(value)
        self.dialog._render_register()
        return [r.get("Customer") for r in self.dialog._visible_rows]

    def test_a_cold_lead_is_not_work_waiting_to_be_quoted(self):
        self.assertEqual([r.get("Customer") for r in self.dialog._to_quote_rows],
                         ["Real Customer"])

    def test_all_still_means_all(self):
        """A filter called All that hides rows is a book nobody trusts."""
        self.assertIn("Tata Steel", self._chip("all"))
        self.assertEqual(len(self._chip("all")), 3)

    def test_the_cold_leads_chip_shows_only_cold_leads(self):
        self.assertEqual(self._chip("outreach"), ["Tata Steel"])

    def test_the_other_chips_still_work(self):
        self.assertEqual(self._chip("won"), ["Won Customer"])
        self.assertIn("Real Customer", self._chip("open"))

    def test_a_lead_that_answers_joins_the_days_work(self):
        rows = self.dialog._register_rows
        cold = [r for r in rows if r.get("Customer") == "Tata Steel"][0]
        outreach.mark_replied(cold)
        self.dialog._render_to_quote()
        self.assertIn("Tata Steel",
                      [r.get("Customer") for r in self.dialog._to_quote_rows])


if __name__ == "__main__":
    unittest.main()
