"""prospector.importing — the Import wizard's mapping step (23-Sep-2026).

Apollo's importer maps every CSV column to a field ("When possible, Apollo
automatically detects and maps fields for you"). The guess has to know
Apollo's OWN export: the file the owner imported ("Apollo_leads (1).csv")
has "First Name" / "Last Name" / "Person Linkedin Url", and sheet.py's
aliases dropped every one of them — names and profile links lost.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import importing as IMP                         # noqa: E402

# A real Apollo people export's header, in Apollo's own column order.
APOLLO_HEADER = ["First Name", "Last Name", "Title", "Company",
                 "Company Name for Emails", "Email", "Email Status",
                 "Seniority", "Departments", "Work Direct Phone", "Mobile Phone",
                 "# Employees", "Industry", "Person Linkedin Url", "Website",
                 "Company Linkedin Url", "City", "State", "Country"]


class GuessingTheMapping(unittest.TestCase):
    def test_apollos_own_export_maps_names_and_profiles(self):
        m = dict(zip(APOLLO_HEADER, IMP.guess_mapping(APOLLO_HEADER, "contacts")))
        self.assertEqual(m["First Name"], "first_name")
        self.assertEqual(m["Last Name"], "last_name")
        self.assertEqual(m["Title"], "title")
        self.assertEqual(m["Company"], "company")          # not "for Emails"
        self.assertEqual(m["Email"], "email")              # not "Email Status"
        self.assertEqual(m["Person Linkedin Url"], "linkedin")
        self.assertEqual(m["Website"], "website")
        self.assertEqual((m["City"], m["State"], m["Country"]),
                         ("city", "state", "country"))
        self.assertEqual(m["# Employees"], "headcount")
        # Every field is used once — except phone, which Apollo spreads over
        # several columns, any one filled; the rest are kept, not dropped.
        self.assertEqual((m["Work Direct Phone"], m["Mobile Phone"]), ("phone", "phone"))
        self.assertEqual(m["Email Status"], IMP.CUSTOM)
        self.assertEqual(m["Company Name for Emails"], IMP.CUSTOM)

    def test_the_company_research_sheet_maps_as_accounts(self):
        header = ["Company Name", "Industry Category", "City", "Website",
                  "Approx Employee Size", "Brief Description",
                  "Why they Outsource?", "Lead Quality"]
        m = dict(zip(header, IMP.guess_mapping(header, "accounts")))
        self.assertEqual(m["Company Name"], "name")
        self.assertEqual(m["Website"], "website")
        self.assertEqual(m["Industry Category"], "industry")
        self.assertEqual(m["Approx Employee Size"], "headcount")
        self.assertEqual(m["Lead Quality"], IMP.CUSTOM)
        self.assertEqual(IMP.looks_like(header), "accounts")
        self.assertEqual(IMP.looks_like(APOLLO_HEADER), "contacts")

    def test_a_blank_header_is_skipped_not_kept_under_no_name(self):
        self.assertEqual(IMP.guess_mapping(["Name", ""], "contacts"),
                         ["name", IMP.SKIP])


class ReadingRows(unittest.TestCase):
    def test_first_and_last_name_make_the_name_and_location_joins(self):
        mapping = IMP.guess_mapping(APOLLO_HEADER, "contacts")
        row = ["Pratik", "Mungra", "Company Owner", "Gurukrupa Aluminium", "",
               "pratik.mungra@gurukrupaaluminium.com", "Verified", "Owner", "",
               "", "+91 90000 00000", "11-50", "Aluminium",
               "https://www.linkedin.com/in/pratik", "gurukrupaaluminium.com", "",
               "Rajkot", "Gujarat", "India"]
        leads, skipped = IMP.contacts_from_rows(APOLLO_HEADER, [row], mapping)
        self.assertEqual(skipped, 0)
        [lead] = leads
        self.assertEqual(lead.name, "Pratik Mungra")
        self.assertEqual(lead.email, "pratik.mungra@gurukrupaaluminium.com")
        self.assertEqual(lead.extra["linkedin"], "https://www.linkedin.com/in/pratik")
        self.assertEqual(lead.extra["location"], "Rajkot, Gujarat, India")
        self.assertEqual(lead.phone, "+91 90000 00000")    # the one filled column
        self.assertEqual(lead.extra["custom"]["Email Status"], "Verified")

    def test_a_company_only_row_is_skipped_in_a_contacts_import(self):
        header = ["Name", "Company"]
        leads, skipped = IMP.contacts_from_rows(
            header, [["", "Acme"], ["", ""]], IMP.guess_mapping(header, "contacts"))
        self.assertEqual((leads, skipped), ([], 1))       # the blank row isn't counted

    def test_accounts_rows(self):
        header = ["Company Name", "Website", "Lead Quality"]
        companies, skipped = IMP.accounts_from_rows(
            header, [["Acme", "acme.example", "A"], ["", "", "B"]],
            IMP.guess_mapping(header, "accounts"))
        self.assertEqual(skipped, 1)
        self.assertEqual(companies[0]["name"], "Acme")
        self.assertEqual(companies[0]["custom"], {"Lead Quality": "A"})

    def test_a_placeholder_in_a_field_is_a_blank_one(self):
        """The owner's AE _ Leads.xlsx wrote "Not Found" wherever research found
        nothing: 115 websites, 105 sizes, 2 cities. In a mapped field that is a
        blank, never a value."""
        header = ["Company Name", "City", "Website", "Approx Employee Size"]
        companies, skipped = IMP.accounts_from_rows(
            header, [["Acme Pumps", "Not Found", "Not Found", "N/A"],
                     ["Beta Valves", "Vadodara", "not available", "100-250"]],
            IMP.guess_mapping(header, "accounts"))
        self.assertEqual(skipped, 0)
        self.assertEqual((companies[0]["website"], companies[0]["location"],
                          companies[0]["headcount"]), ("", "", ""))
        self.assertEqual((companies[1]["website"], companies[1]["location"],
                          companies[1]["headcount"]), ("", "Vadodara", "100-250"))

    def test_which_cells_count_as_saying_nothing(self):
        for text in ("Not Found", "  not   available ", "N/A", "n.a.", "None", "-", "—", "TBD",
                     "Unknown", "", None):
            self.assertTrue(IMP.is_placeholder(text) or not text, text)
        for text in ("Nagpur", "Nova Works", "Acme", "http://acme.example", "0"):
            self.assertFalse(IMP.is_placeholder(text), text)

    def test_a_custom_column_keeps_what_the_owner_typed_even_if_it_says_nothing(self):
        header = ["Company Name", "Lead Quality"]
        companies, _ = IMP.accounts_from_rows(header, [["Acme", "Not Found"]],
                                              IMP.guess_mapping(header, "accounts"))
        self.assertEqual(companies[0]["custom"], {"Lead Quality": "Not Found"})

    def test_a_person_with_a_placeholder_email_has_no_email(self):
        header = ["Name", "Email"]
        leads, _ = IMP.contacts_from_rows(header, [["Asha Rao", "Not Found"]],
                                          IMP.guess_mapping(header, "contacts"))
        self.assertEqual((leads[0].name, leads[0].email), ("Asha Rao", ""))
        self.assertNotIn("email_source", leads[0].extra)

    def test_a_row_whose_only_company_is_a_placeholder_names_no_company(self):
        header = ["Company Name", "Website"]
        companies, skipped = IMP.accounts_from_rows(
            header, [["Not Found", "Not Found"]], IMP.guess_mapping(header, "accounts"))
        self.assertEqual((companies, skipped), ([], 0))

    def test_read_table_and_tabs_on_a_csv(self):
        path = os.path.join(tempfile.mkdtemp(), "people.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["First Name", "Last Name"])
            w.writerow(["Jane", "Doe"])
        name, header, rows = IMP.read_table(path)
        self.assertEqual((name, header, rows), ("people", ["First Name", "Last Name"],
                                                [["Jane", "Doe"]]))
        self.assertEqual(IMP.tabs(path), [("people", 1)])


if __name__ == "__main__":
    unittest.main()
