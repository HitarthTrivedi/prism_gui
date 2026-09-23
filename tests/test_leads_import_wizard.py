"""Import ▾ — the wizard (addons/leads/import_wizard.py), 23-Sep-2026.

Apollo's "Import a CSV": choose a file, map every column to a field (auto-
detected where it can), settings, Import — and nothing searched. The wizard
only collects; these tests drive it the way a person would, minus the clicks.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                     # noqa: E402

from prospector import importing as IMP                         # noqa: E402
from addons.leads.import_wizard import ImportWizard             # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _csv(rows, name="Apollo_leads (1).csv"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


APOLLO = [["First Name", "Last Name", "Title", "Company", "Email", "Person Linkedin Url",
           "City", "Country"],
          ["Pratik", "Mungra", "Company Owner", "Gurukrupa Aluminium",
           "pratik.mungra@gurukrupaaluminium.com", "linkedin.com/in/pratik", "Rajkot", "India"],
          ["Johan", "Gidstedt", "Owner, President", "Global Steel Fabricator", "", "", "", ""],
          ["", "", "", "Only A Company Ltd", "", "", "", ""]]


class ContactsImport(unittest.TestCase):
    def setUp(self):
        self.w = ImportWizard("contacts")

    def test_the_three_steps(self):
        self.assertFalse(self.w._next.isEnabled())             # no file yet
        self.assertTrue(self.w.load(_csv(APOLLO)))
        self.assertTrue(self.w._next.isEnabled())
        self.w._next.click()                                   # → Map columns
        self.assertEqual(self.w._step, 1)
        self.assertEqual(self.w.mapping()[:2], ["first_name", "last_name"])
        self.w._next.click()                                   # → Settings
        self.assertEqual(self.w._step, 2)
        self.assertEqual(self.w._next.text(), "Import")
        self.assertIn("Ready to import 2 contacts", self.w._summary.text())
        self.assertIn("1 rows will be skipped", self.w._summary.text())
        result = self.w.result()
        self.assertEqual([l.name for l in result["leads"]], ["Pratik Mungra", "Johan Gidstedt"])
        self.assertEqual(result["name"], "Apollo_leads (1).csv")
        self.assertTrue(result["settings"]["update_existing"])
        self.assertEqual(result["mapping"]["Person Linkedin Url"], "linkedin")

    def test_a_mapping_that_identifies_nobody_cannot_go_on(self):
        self.w.load(_csv(APOLLO))
        self.w._next.click()
        for i, key in enumerate(self.w.mapping()):
            if key in ("first_name", "last_name", "email", "linkedin"):
                combo = self.w._combos[i]
                combo.setCurrentIndex(combo.findData(IMP.SKIP))
        self.assertFalse(self.w._next.isEnabled())
        self.assertTrue(self.w._map_error.text())

    def test_back_goes_back(self):
        self.w.load(_csv(APOLLO))
        self.w._next.click()
        self.w._back.click()
        self.assertEqual(self.w._step, 0)
        self.assertTrue(self.w._back.isHidden())

    def test_an_unreadable_file_says_why(self):
        path = os.path.join(tempfile.mkdtemp(), "broken.xlsx")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not a workbook")
        self.assertFalse(self.w.load(path))
        self.assertIn("Couldn't read this file", self.w._file_error.text())
        self.assertFalse(self.w._next.isEnabled())


class AccountsImport(unittest.TestCase):
    def test_a_company_research_sheet(self):
        w = ImportWizard("accounts")
        w.load(_csv([["Company Name", "Industry Category", "Website", "Lead Quality"],
                     ["Acme Tooling", "Packaging Machinery", "acme.example", "A"],
                     ["", "", "", "B"]], "AE _ Leads.csv"))
        w._next.click()
        w._next.click()
        result = w.result()
        self.assertEqual(result["kind"], "accounts")
        self.assertEqual([c["name"] for c in result["companies"]], ["Acme Tooling"])
        self.assertEqual(result["companies"][0]["custom"], {"Lead Quality": "A"})
        self.assertEqual(result["skipped"], 1)
        self.assertIn("Ready to import 1 companies", w._summary.text())
        self.assertEqual(result["settings"], {})


if __name__ == "__main__":
    unittest.main()
