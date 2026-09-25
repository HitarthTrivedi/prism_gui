"""Import — Apollo's People / Companies > Import > CSV (addons/leads/import_wizard.py).

Two screens, as Apollo has them (knowledge.apollo.io "Import a CSV of
Contacts" / "… of Accounts", and the owner's screenshots of 23-Sep-2026): the
two cards — each saying which columns a file needs, with Select CSV File and
Download sample template — then ONE page with the column mappings (a card
per column, recognised or needing mapping) over the settings, and Import.
Nothing is searched. The window only collects; these tests drive it the way a
person would, minus the clicks and the file dialogs.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                     # noqa: E402

from prospector import importing as IMP                         # noqa: E402
from addons.leads import import_wizard as W                     # noqa: E402
from addons.leads.import_wizard import ImportWizard             # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _csv(rows, name="Apollo_leads (1).csv"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


APOLLO = [["First Name", "Last Name", "Title", "Company", "Email", "Person Linkedin Url",
           "City", "Country", "Stage", "Lead Quality"],
          ["Pratik", "Mungra", "Company Owner", "Gurukrupa Aluminium",
           "pratik.mungra@gurukrupaaluminium.com", "linkedin.com/in/pratik", "Rajkot",
           "India", "Interested", "A"],
          ["Johan", "Gidstedt", "Owner, President", "Global Steel Fabricator", "", "", "",
           "", "", ""],
          ["", "", "", "Only A Company Ltd", "", "", "", "", "", ""]]
ACCOUNTS = [["Account Name", "Account Stage", "Account Website"],
            ["Google", "Cold", "www.google.com"],
            ["SPI Technologies Inc", "Current Client", ""]]


class TheTwoCards(unittest.TestCase):
    """Import opens on Apollo's two cards; the kind the owner picked from the
    menu leads, and either can be used."""

    def test_both_kinds_are_offered_and_the_picked_one_leads(self):
        w = ImportWizard("accounts")
        self.assertEqual(w._step, 0)
        self.assertEqual(set(w._kind_cards), {"contacts", "accounts"})
        self.assertEqual(w._kind_cards["accounts"].select_btn.objectName(), "primaryBtn")
        self.assertNotEqual(w._kind_cards["contacts"].select_btn.objectName(), "primaryBtn")
        self.assertTrue(w._import.isHidden())               # nothing to import yet
        self.assertTrue(w._file_chip.isHidden())

    def test_select_csv_file_on_a_card_imports_that_kind(self):
        w = ImportWizard("contacts")
        path = _csv(ACCOUNTS, "companies.csv")
        w.choose_file = lambda: path
        w._kind_cards["accounts"].select_btn.click()
        self.assertEqual((w.kind, w._step), ("accounts", 1))
        self.assertEqual(w.header.title.text(), "Import accounts")

    def test_the_sample_template_is_a_real_csv_with_the_recommended_columns(self):
        w = ImportWizard("contacts")
        out = os.path.join(tempfile.mkdtemp(), "template.csv")
        w.save_template_to = lambda kind: out
        w._kind_cards["contacts"].template_btn.click()
        with open(out, encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        # Everything Apollo recommends, and each one maps without help.
        for column in ("First Name", "Last Name", "Company Name", "Company Website",
                       "Email", "Person LinkedIn URL"):
            self.assertIn(column, header)
        self.assertNotIn(IMP.CUSTOM, IMP.guess_mapping(header, "contacts"))
        self.assertIn("Saved the sample template", w._file_error.text())

    def test_an_unreadable_file_says_why_and_stays_on_the_cards(self):
        w = ImportWizard("contacts")
        path = os.path.join(tempfile.mkdtemp(), "broken.xlsx")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not a workbook")
        self.assertFalse(w.load(path))
        self.assertIn("Couldn't read this file", w._file_error.text())
        self.assertEqual(w._step, 0)

    def test_a_file_over_the_row_limit_is_refused_with_the_way_out(self):
        w = ImportWizard("contacts")
        with mock.patch.object(W, "MAX_ROWS", 2):
            self.assertFalse(w.load(_csv(APOLLO)))
        self.assertIn("split it into files", w._file_error.text())
        self.assertEqual(w._step, 0)


class ContactsImport(unittest.TestCase):
    def setUp(self):
        self.w = ImportWizard("contacts", lists=["Vadodara buyers"])
        self.assertTrue(self.w.load(_csv(APOLLO)))

    def test_one_page_mappings_over_settings(self):
        w = self.w
        self.assertEqual(w._step, 1)
        self.assertEqual(w.header.title.text(), "Import contacts")
        self.assertIn("3 rows included", w.header.subtitle.text())
        self.assertEqual(w.mapping()[:3], ["first_name", "last_name", "title"])
        self.assertEqual(w.mapping()[-2:], ["stage", IMP.CUSTOM])
        self.assertIn("9 recognized", w._recognized_chip.text())
        self.assertIn("1 need mapping", w._unmapped_chip.text())
        self.assertFalse(w._file_chip.isHidden())
        self.assertEqual(w._file_name.text(), "Apollo_leads (1).csv")
        self.assertTrue(w._import.isEnabled())
        # Settings and Data enrichment, as Apollo's contacts import has them.
        self.assertEqual([b.text() for b in w._tab_btns], ["Settings", "Data enrichment"])

    def test_the_result_is_the_people_with_their_stage_and_custom_columns(self):
        result = self.w.result()
        self.assertEqual([l.name for l in result["leads"]], ["Pratik Mungra", "Johan Gidstedt"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["leads"][0].extra["stage"], "Interested")
        self.assertEqual(result["leads"][0].extra["custom"], {"Lead Quality": "A"})
        self.assertEqual(result["mapping"]["Person Linkedin Url"], "linkedin")

    def test_settings_default_to_apollos(self):
        s = self.w.settings()
        self.assertEqual(s["stage"], "csv")                 # a stage column is mapped
        self.assertTrue(s["update_existing"])
        self.assertEqual(s["assign_accounts"], "domain")
        self.assertEqual((s["add_to_list"], s["list_name"]), (False, ""))
        self.assertFalse(s["find_emails"])
        self.assertFalse(s["find_phones"])

    def test_without_a_stage_column_use_stage_from_csv_is_not_offered(self):
        w = self.w
        stage_card = w._cards[w.mapping().index("stage")]
        stage_card.combo.setCurrentIndex(stage_card.combo.findData(IMP.SKIP))
        self.assertEqual(w.settings()["stage"], "Cold")
        self.assertFalse(w._stage.model().item(0).isEnabled())

    def test_a_stage_the_owner_picked_is_kept(self):
        w = self.w
        w._stage.setCurrentIndex(w._stage.findData("Approaching"))
        w._touch_stage(0)
        w._hide_known.setChecked(True)                      # anything that re-syncs
        self.assertEqual(w.settings()["stage"], "Approaching")

    def test_add_to_a_list_takes_a_new_or_an_existing_name(self):
        w = self.w
        self.assertEqual(w._list_box.findText("Vadodara buyers"), 1)
        w._list_box.setEditText("  Gujarat   owners ")
        self.assertEqual((w.settings()["add_to_list"], w.settings()["list_name"]),
                         (True, "Gujarat owners"))

    def test_data_enrichment_says_how_many_it_would_look_up(self):
        w = self.w
        self.assertIn("1 of the 2 contacts have no e-mail", w._email_meta.text())
        w._find_emails.setChecked(True)
        self.assertTrue(w.settings()["find_emails"])

    def test_hide_recognised_columns_leaves_only_the_ones_to_look_at(self):
        w = self.w
        w._hide_known.setChecked(True)
        shown = [c for c in w._cards if not c.isHidden()]
        self.assertEqual([c.title.text() for c in shown], ["Lead Quality"])

    def test_a_mapping_that_identifies_nobody_cannot_be_imported(self):
        w = self.w
        for card in w._cards:
            if card.value() in ("first_name", "last_name", "email", "linkedin"):
                card.combo.setCurrentIndex(card.combo.findData(IMP.SKIP))
        self.assertFalse(w._import.isEnabled())
        self.assertTrue(w._map_error.text())

    def test_the_bin_on_the_file_starts_over(self):
        w = self.w
        w._drop_file.click()
        self.assertEqual(w._step, 0)
        self.assertEqual(w.path, "")
        self.assertTrue(w._import.isHidden())


class AccountsImport(unittest.TestCase):
    def setUp(self):
        self.w = ImportWizard("accounts")
        self.assertTrue(self.w.load(_csv(ACCOUNTS, "companies.csv")))

    def test_a_company_list_maps_name_stage_and_website(self):
        w = self.w
        self.assertEqual(w.mapping(), ["name", "stage", "website"])
        self.assertEqual([b.text() for b in w._tab_btns], ["Settings"])
        result = w.result()
        self.assertEqual([(c["name"], c["stage"]) for c in result["companies"]],
                         [("Google", "Cold"), ("SPI Technologies Inc", "Current Client")])

    def test_enrichment_is_offered_with_what_it_costs(self):
        w = self.w
        self.assertEqual(w._estimate.text(), "")
        w._find_websites.setChecked(True)                    # only SPI has no website
        self.assertIn("About 1 Exa search", w._estimate.text())
        w._enrich_all.setChecked(True)
        self.assertIn("About 2 Exa searches", w._estimate.text())
        s = w.settings()
        self.assertEqual((s["find_websites"], s["enrich_all"]), (True, True))
        self.assertNotIn("assign_accounts", s)

    def test_a_research_sheet_keeps_its_own_columns(self):
        w = ImportWizard("accounts")
        w.load(_csv([["Company Name", "Industry Category", "Website", "Lead Quality"],
                     ["Acme Tooling", "Packaging Machinery", "acme.example", "A"],
                     ["", "", "", "B"]], "AE _ Leads.csv"))
        result = w.result()
        self.assertEqual([c["name"] for c in result["companies"]], ["Acme Tooling"])
        self.assertEqual(result["companies"][0]["custom"], {"Lead Quality": "A"})
        self.assertEqual(result["skipped"], 1)

    def test_every_tab_of_a_workbook_is_imported_unless_one_is_picked(self):
        """24-Sep-2026: the owner's AE _ Leads.xlsx held 100 companies on a
        "ChatGPT" tab and 127 on "Perplexity"; the import read the first tab
        only, and the Sheet picker that could have said so sat quietly on it."""
        import openpyxl
        path = os.path.join(tempfile.mkdtemp(), "AE _ Leads.xlsx")
        wb = openpyxl.Workbook()
        wb.active.title = "ChatGPT"
        wb.active.append(["Company Name", "Website"])
        wb.active.append(["Parle Elizabeth Tools", "parleelizabeth.com"])
        other = wb.create_sheet("Perplexity")
        other.append(["Company Name", "Source URL"])
        other.append(["IDMC Limited", "https://example.com/idmc"])
        other.append(["Romaco Innojet India", ""])
        wb.save(path)
        w = ImportWizard("accounts")
        self.assertTrue(w.load(path))
        self.assertEqual((w.sheet, len(w.rows)), (IMP.ALL_SHEETS_NAME, 3))
        self.assertEqual([w._tab.itemText(i) for i in range(w._tab.count())],
                         ["All sheets (3)", "ChatGPT (1)", "Perplexity (2)"])
        self.assertEqual(w._tab.currentIndex(), 0)
        result = w.result()
        self.assertEqual([c["name"] for c in result["companies"]],
                         ["Parle Elizabeth Tools", "IDMC Limited", "Romaco Innojet India"])
        self.assertEqual(result["companies"][1]["custom"]["Sheet"], "Perplexity")
        # Picking one tab still reads just that tab.
        w._tab.setCurrentIndex(2)
        w._tab.activated.emit(2)
        self.assertEqual((w.sheet, len(w.rows)), ("Perplexity", 2))


if __name__ == "__main__":
    unittest.main()
