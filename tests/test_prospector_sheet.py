"""prospector.sheet.has_name_column — telling "no people in this file" apart
from "this file has no name column".

22-Sep-2026: a customer imported a company-research export (Company Name,
Industry, City, Website … no person anywhere in it) into Leads & Outreach.
sheet.load() correctly skipped every row — leads_from_sheet() only keeps a
row that has a person's NAME — and the run finished with zero leads. On
screen that looked identical to the button doing nothing at all: the
"0 ready to send" banner was already there before the click, and it was
still there after. has_name_column() is the header-only check that lets the
caller (addons/leads/workbench.py's _show_result) tell the two apart and
say which one actually happened.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import sheet as SH                             # noqa: E402


def _xlsx(tmp: str, name: str, header: list, rows: list = ()) -> str:
    import openpyxl
    path = os.path.join(tmp, name)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


class ACompanyOnlyExportHasNoNameColumn(unittest.TestCase):
    """The exact shape of the file that started this: research rows about
    companies, never about a person — Company Name, Industry, City, Website,
    "Why they outsource", a lead-quality grade. Every alias sheet.py knows
    for a person's name ("name", "full name", "contact", "person") is
    absent, and "Company Name" must not accidentally satisfy it."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_a_company_research_sheet_has_no_name_column(self):
        path = _xlsx(self._tmp, "companies.xlsx",
                    ["Company Name", "Industry Category", "City", "Website",
                     "Approx Employee Size", "Brief Description",
                     "Why they Outsource?", "Lead Quality"],
                    [["Acme Tooling Pvt. Ltd.", "Packaging Machinery",
                      "Vadodara", "https://acme.example", "500+", "…", "…", "A"]])
        self.assertFalse(SH.has_name_column(path))
        # The same file really does read back as zero leads — has_name_column
        # is not guessing, it is answering the question load() itself can't.
        self.assertEqual(SH.load(path), [])

    def test_company_name_does_not_alias_to_the_person_name_field(self):
        # "Company Name".startswith("name") is False, but this is the one
        # a looser alias rule would have gotten wrong, so it gets its own
        # test rather than trusting the case above to catch a regression.
        path = _xlsx(self._tmp, "just_company.xlsx", ["Company Name"])
        self.assertFalse(SH.has_name_column(path))


class ARealLeadsSheetHasOne(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_the_plain_header(self):
        path = _xlsx(self._tmp, "leads.xlsx",
                    ["Name", "Title", "Company", "Email"],
                    [["Jane Doe", "Owner", "Acme", "jane@acme.example"]])
        self.assertTrue(SH.has_name_column(path))
        self.assertEqual(len(SH.load(path)), 1)

    def test_every_alias_sheet_py_itself_documents(self):
        for alias in ("name", "full name", "contact", "person"):
            path = _xlsx(self._tmp, f"{alias.replace(' ', '_')}.xlsx",
                        [alias.title(), "Company"])
            self.assertTrue(SH.has_name_column(path), alias)

    def test_a_trailing_space_still_matches(self):
        # sheet.py's own docstring: "Headers carry trailing spaces
        # ('Company ', 'Name ') — matched loosely."
        path = _xlsx(self._tmp, "trailing_space.xlsx", ["Name ", "Company "])
        self.assertTrue(SH.has_name_column(path))

    def test_one_sheet_of_several_names_is_enough(self):
        import openpyxl
        path = os.path.join(self._tmp, "multi.xlsx")
        wb = openpyxl.Workbook()
        wb.active.title = "Companies"
        wb.active.append(["Company Name", "Industry"])
        people = wb.create_sheet("People")
        people.append(["Name", "Company"])
        people.append(["Jane Doe", "Acme"])
        wb.save(path)
        self.assertTrue(SH.has_name_column(path))

    def test_scoped_to_one_sheet_by_name(self):
        import openpyxl
        path = os.path.join(self._tmp, "multi2.xlsx")
        wb = openpyxl.Workbook()
        wb.active.title = "Companies"
        wb.active.append(["Company Name"])
        people = wb.create_sheet("People")
        people.append(["Name"])
        wb.save(path)
        self.assertFalse(SH.has_name_column(path, sheet="Companies"))
        self.assertTrue(SH.has_name_column(path, sheet="People"))


class AnEmptyOrMissingFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_a_header_only_sheet_with_no_rows_still_reports_its_columns(self):
        # has_name_column reads the HEADER, not the rows — a real leads
        # sheet that just has nobody in it yet still says yes here; the
        # "nobody in it" case is told apart by load() coming back empty
        # while this is True, not by this being False.
        path = _xlsx(self._tmp, "header_only.xlsx", ["Name", "Company"])
        self.assertTrue(SH.has_name_column(path))
        self.assertEqual(SH.load(path), [])

    def test_a_blank_workbook_has_no_name_column(self):
        import openpyxl
        path = os.path.join(self._tmp, "blank.xlsx")
        openpyxl.Workbook().save(path)
        self.assertFalse(SH.has_name_column(path))

    def test_a_csv_export(self):
        path = os.path.join(self._tmp, "companies.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Company Name", "Industry"])
            w.writerow(["Acme", "Tooling"])
        self.assertFalse(SH.has_name_column(path))

        path2 = os.path.join(self._tmp, "leads.csv")
        with open(path2, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Name", "Email"])
            w.writerow(["Jane Doe", "jane@acme.example"])
        self.assertTrue(SH.has_name_column(path2))


if __name__ == "__main__":
    unittest.main()
