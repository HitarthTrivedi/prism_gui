"""The people taken off the list (addons/leads/removed.py).

The owner, 23-Sep-2026: ticking people and pressing Clear should take them
away. Asked what that means, he chose "Remove from list": they leave People
(Total, Net New and Saved), new searches never bring them back, and they can
be restored — nothing is deleted. These tests hold the store to that, the
pool and a search to leaving them out, and the Removed window to putting
them back. The workbench end to end is in test_leads_cockpit.py
(RemoveTakesThemOffTheList).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt                      # noqa: E402
from PySide6.QtGui import QMouseEvent                               # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from prospector.models import Lead                                  # noqa: E402
from addons.leads import pool as P                                  # noqa: E402
from addons.leads import removed as RM                              # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _lead(name, company="Firm", email="", **extra):
    lead = Lead(name=name, title="Owner", company=company, email=email)
    lead.extra.update(extra)
    return lead


class _Folder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, payload) -> None:
        with open(os.path.join(self.dir, RM.FILE), "w", encoding="utf-8") as f:
            f.write(payload if isinstance(payload, str) else json.dumps(payload))


class TheStore(_Folder):

    def test_nobody_removed_reads_as_nobody(self):
        self.assertEqual(RM.list_removed(self.dir), [])
        self.assertEqual(RM.keys([]), frozenset())

    def test_remove_keeps_who_they_are_and_every_key(self):
        asha = _lead("Asha Rao", "Rao Works", "asha@rao.example",
                     location="Pune, India", linkedin="linkedin.com/in/asha-rao")
        ids = RM.remove(self.dir, [asha])
        [record] = RM.list_removed(self.dir)
        self.assertEqual(ids, [record.id])
        self.assertEqual((record.name, record.company, record.email, record.location),
                         ("Asha Rao", "Rao Works", "asha@rao.example", "Pune, India"))
        # Every way the pool could know her: her address, her profile, her
        # name at her firm.
        self.assertEqual({k.split(":")[0] for k in record.keys}, {"e", "u", "n"})
        self.assertTrue(record.removed_at)

    def test_a_person_carries_the_keys_of_all_their_records(self):
        # A pool.Person joins a saved contact and a run's row: removing them
        # must reach both, not only the row that was ticked.
        row = _lead("Asha Rao", "Rao Works", "asha@rao.example")
        other = _lead("Asha R.", "Rao Precision", "asha@rao.example",
                      linkedin="linkedin.com/in/asha-rao")
        [person] = P.build(runs=[("s1", "2026-09-23T10:00:00", [row, other], [])])
        RM.remove(self.dir, [person])
        keys = RM.keys(RM.list_removed(self.dir))
        self.assertIn("u:linkedin.com/in/asha-rao", keys)
        self.assertIn("n:asha r|rao precision", keys)

    def test_someone_sharing_a_key_joins_the_earlier_record(self):
        RM.remove(self.dir, [_lead("Asha Rao", "Rao Works", "asha@rao.example")])
        RM.remove(self.dir, [_lead("A. Rao", "Rao Works Pvt Ltd", "asha@rao.example")])
        [record] = RM.list_removed(self.dir)
        self.assertIn("n:a rao|rao works", record.keys)

    def test_restore_puts_them_back_by_id(self):
        ids = RM.remove(self.dir, [_lead("Asha Rao", email="a@x.example"),
                                   _lead("Bo Lund", email="b@x.example")])
        self.assertEqual(RM.restore(self.dir, ids[:1]), 1)
        self.assertEqual([r.name for r in RM.list_removed(self.dir)], ["Bo Lund"])
        self.assertEqual(RM.restore(self.dir, ["no-such-id"]), 0)

    def test_an_import_naming_them_puts_them_back(self):
        RM.remove(self.dir, [_lead("Asha Rao", email="a@x.example"),
                             _lead("Bo Lund", email="b@x.example")])
        again = _lead("Asha Rao", company="Somewhere Else", email="A@X.example")
        self.assertEqual(RM.restore_leads(self.dir, [again]), 1)
        self.assertEqual([r.name for r in RM.list_removed(self.dir)], ["Bo Lund"])
        self.assertEqual(RM.restore_leads(self.dir, [_lead("Nobody")]), 0)

    def test_a_damaged_file_is_set_aside_not_lost(self):
        self._write("{ not json")
        RM.remove(self.dir, [_lead("Asha Rao", email="a@x.example")])
        self.assertEqual(len(RM.list_removed(self.dir)), 1)
        kept = [n for n in os.listdir(self.dir) if ".damaged-" in n]
        self.assertEqual(len(kept), 1)

    def test_a_newer_file_is_never_written_over(self):
        self._write({"schema": RM.SCHEMA + 1, "removed": []})
        with self.assertRaises(RM.StoreError):
            RM.remove(self.dir, [_lead("Asha Rao", email="a@x.example")])
        with open(os.path.join(self.dir, RM.FILE), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["schema"], RM.SCHEMA + 1)
        self.assertEqual(RM.list_removed(self.dir), [])

    def test_a_record_with_no_key_is_dropped_on_read(self):
        self._write({"schema": 1, "removed": [
            {"id": "x1", "keys": [], "name": "Ghost"},
            {"id": "x2", "keys": ["e:bo@x.example"], "name": "Bo Lund"}]})
        self.assertEqual([r.id for r in RM.list_removed(self.dir)], ["x2"])


class ThePoolLeavesThemOut(_Folder):

    def test_anyone_sharing_a_key_is_left_out_of_every_tab(self):
        people = [_lead(f"Person {i}", f"Firm {i}", f"p{i}@firm{i}.example") for i in range(3)]
        saved = _lead("Person 1", "Firm 1", "p1@firm1.example")
        from addons.leads.contacts import Contact
        pool = P.build([Contact(lead=saved, saved_at="2026-09-20")],
                       [("s1", "2026-09-23", people, [])])
        RM.remove(self.dir, [_lead("P. One", "Elsewhere", "P1@firm1.example")])
        left = P.without(pool, RM.keys(RM.list_removed(self.dir)))
        self.assertEqual(sorted(p.lead.name for p in left), ["Person 0", "Person 2"])
        tabs = P.split(left)
        self.assertEqual((len(tabs["total"]), len(tabs["saved"])), (2, 0))

    def test_nobody_removed_leaves_the_pool_as_it_was(self):
        pool = P.build(runs=[("s1", "", [_lead("Asha", email="a@x.example")], [])])
        self.assertEqual(P.without(pool, frozenset()), pool)


class ASearchSkipsThem(_Folder):

    def test_removed_people_are_skipped_even_with_earlier_people_let_in(self):
        from addons.leads.workers import _seen_index
        RM.remove(self.dir, [_lead("Asha Rao", "Rao Works", "a@rao.example")])
        skip = _seen_index("", True, self.dir)      # "include earlier people" on
        self.assertIn(_lead("Asha Rao", "Rao Works"), skip)
        self.assertNotIn(_lead("Bo Lund", "Lund Steel"), skip)

    def test_nothing_to_skip_is_no_index(self):
        from addons.leads.workers import _seen_index
        self.assertIsNone(_seen_index("", True, self.dir))
        self.assertIsNone(_seen_index("", True, ""))


def _click(widget) -> None:
    """A left click in the middle of `widget`, press then release."""
    at = QPointF(widget.rect().center())
    glob = QPointF(widget.mapToGlobal(widget.rect().center()))
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(widget, QMouseEvent(kind, at, glob, Qt.LeftButton,
                                                   Qt.LeftButton, Qt.NoModifier))


class TheRemovedWindow(_Folder):

    def _records(self):
        RM.remove(self.dir, [_lead("Asha Rao", "Rao Works", "a@rao.example"),
                             _lead("Bo Lund", "Lund Steel", "b@lund.example")])
        return RM.list_removed(self.dir)

    def test_a_click_on_a_row_ticks_it(self):
        from addons.leads.removed_dialog import RemovedDialog
        records = self._records()
        dlg = RemovedDialog(records)
        self.assertFalse(dlg.restore_btn.isEnabled())       # nothing ticked yet
        _click(dlg.rows[0])
        self.assertEqual(dlg.chosen_ids(), [records[0].id])
        self.assertTrue(dlg.restore_btn.isEnabled())
        self.assertEqual(dlg.restore_btn.text(), "Restore 1")
        _click(dlg.rows[0])                                 # and again: unticked
        self.assertEqual(dlg.chosen_ids(), [])

    def test_select_all_ticks_everyone(self):
        from addons.leads.removed_dialog import RemovedDialog
        records = self._records()
        dlg = RemovedDialog(records)
        dlg.select_all.click()
        self.assertEqual(sorted(dlg.chosen_ids()), sorted(r.id for r in records))
        self.assertEqual(dlg.restore_btn.text(), "Restore 2")

    def test_nobody_removed_says_so(self):
        from addons.leads.removed_dialog import RemovedDialog
        dlg = RemovedDialog([])
        self.assertFalse(dlg.restore_btn.isEnabled())
        self.assertTrue(dlg.select_all.isHidden())


if __name__ == "__main__":
    unittest.main()
