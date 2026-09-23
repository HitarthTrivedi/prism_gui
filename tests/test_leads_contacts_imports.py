"""The two stores Apollo's Find People needs (23-Sep-2026).

addons/leads/contacts.py — Apollo's "Saved": the people imported, saved,
exported or sequenced; one record per person however they came back.
addons/leads/imports.py — every Contact / Account CSV import, kept by file
name, which is what the two CSV-import filters pick from.

Both keep the disk rules sessions.py and saved_searches.py keep (store.py):
atomic writes, a damaged file set aside rather than written over, a newer
one left alone, readers that never raise.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.models import Lead                              # noqa: E402
from addons.leads import contacts as CT                         # noqa: E402
from addons.leads import imports as IM                          # noqa: E402
from addons.leads import store                                  # noqa: E402


def _lead(name="Jane Doe", company="Acme", email="", linkedin="", title="Owner"):
    lead = Lead(name=name, company=company, email=email, title=title)
    if linkedin:
        lead.extra["linkedin"] = linkedin
    return lead


class SavedContacts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_an_empty_folder_has_no_contacts(self):
        self.assertEqual(CT.list_contacts(self.dir), [])
        self.assertEqual(CT.saved_keys(self.dir), frozenset())

    def test_saving_people_makes_them_contacts(self):
        got = CT.save(self.dir, [_lead(email="jane@acme.example"),
                                 _lead("Raj Patel", email="raj@beta.example")],
                      via="save")
        self.assertEqual(got, {"added": 2, "updated": 0, "tagged": 0})
        names = {c.lead.name for c in CT.list_contacts(self.dir)}
        self.assertEqual(names, {"Jane Doe", "Raj Patel"})
        self.assertIn("e:jane@acme.example", CT.saved_keys(self.dir))

    def test_the_same_person_twice_is_one_contact_tagged_again(self):
        CT.save(self.dir, [_lead(email="jane@acme.example")], via="save")
        # Same person, found again by LinkedIn + e-mail, exported this time.
        again = _lead(email="jane@acme.example", linkedin="linkedin.com/in/jane")
        got = CT.save(self.dir, [again], via="export")
        self.assertEqual(got["added"], 0)
        [c] = CT.list_contacts(self.dir)
        self.assertEqual(c.via, ["save", "export"])

    def test_update_writes_new_fields_over_the_saved_record(self):
        CT.save(self.dir, [_lead(email="jane@acme.example", title="Owner")], via="save")
        newer = _lead(email="jane@acme.example", title="Managing Director")
        CT.save(self.dir, [newer], via="import", import_id="imp-x", update=True)
        [c] = CT.list_contacts(self.dir)
        self.assertEqual(c.lead.title, "Managing Director")

    def test_without_update_the_record_is_left_as_it_was(self):
        # Apollo's other "If contacts already exist" choice.
        CT.save(self.dir, [_lead(email="jane@acme.example", title="Owner")], via="save")
        CT.save(self.dir, [_lead(email="jane@acme.example", title="Intern")],
                via="import", import_id="imp-20260923-101010-abcdef", update=False)
        [c] = CT.list_contacts(self.dir)
        self.assertEqual(c.lead.title, "Owner")
        self.assertEqual(c.imports, ["imp-20260923-101010-abcdef"])  # but tagged

    def test_a_lead_nobody_can_be_told_apart_by_is_not_saved(self):
        got = CT.save(self.dir, [Lead(name="Only A Name")], via="save")
        self.assertEqual(got["added"], 0)
        self.assertEqual(CT.list_contacts(self.dir), [])

    def test_the_saved_record_is_a_copy_not_the_live_lead(self):
        lead = _lead(email="jane@acme.example", title="Owner")
        CT.save(self.dir, [lead], via="save")
        lead.title = "changed later by a verify pass"
        self.assertEqual(CT.list_contacts(self.dir)[0].lead.title, "Owner")

    def test_remove(self):
        CT.save(self.dir, [_lead(email="jane@acme.example"),
                           _lead("Raj Patel", email="raj@beta.example")], via="save")
        self.assertEqual(CT.remove(self.dir, [_lead(email="jane@acme.example")]), 1)
        self.assertEqual([c.lead.name for c in CT.list_contacts(self.dir)], ["Raj Patel"])

    def test_deleting_an_import_takes_only_the_people_it_alone_brought(self):
        imp = "imp-20260923-101010-abcdef"
        CT.save(self.dir, [_lead(email="only@x.example"),
                           _lead("Kept", email="kept@x.example")],
                via="import", import_id=imp)
        CT.save(self.dir, [_lead("Kept", email="kept@x.example")], via="export")
        self.assertEqual(CT.untag_import(self.dir, imp), 1)
        [c] = CT.list_contacts(self.dir)
        self.assertEqual(c.lead.email, "kept@x.example")
        self.assertEqual(c.imports, [])

    def test_a_damaged_file_lists_nothing_and_is_set_aside_by_the_next_save(self):
        with open(os.path.join(self.dir, CT.FILE), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(CT.list_contacts(self.dir), [])
        CT.save(self.dir, [_lead(email="jane@acme.example")], via="save")
        self.assertEqual(len(CT.list_contacts(self.dir)), 1)
        aside = [n for n in os.listdir(self.dir) if ".damaged-" in n]
        self.assertEqual(len(aside), 1)

    def test_a_newer_file_is_never_written_over(self):
        with open(os.path.join(self.dir, CT.FILE), "w", encoding="utf-8") as f:
            json.dump({"schema": CT.SCHEMA + 1, "contacts": []}, f)
        with self.assertRaises(store.StoreError) as ctx:
            CT.save(self.dir, [_lead(email="jane@acme.example")], via="save")
        self.assertIn("newer version of Prism", str(ctx.exception))


class CsvImports(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_an_accounts_import_keeps_its_companies_once_each(self):
        header = IM.create(self.dir, name="AE _ Leads.xlsx", kind="accounts",
                           companies=[
                               {"name": "Acme Tooling Pvt. Ltd.", "website": "https://www.acme.example"},
                               {"name": "Acme Tooling Ltd"},            # same company
                               {"name": "", "website": "beta.example"},
                               {"name": "", "website": ""},             # names nothing
                           ])
        self.assertTrue(IM.valid_id(header["id"]))
        self.assertEqual(header["n_companies"], 2)
        record = IM.get(self.dir, header["id"])
        self.assertEqual(record["companies"][0]["domain"], "acme.example")

    def test_the_research_columns_of_an_account_are_kept(self):
        header = IM.create(self.dir, name="AE.xlsx", kind="accounts", companies=[
            {"name": "Acme", "custom": {"Why they Outsource?": "no in-house team",
                                        "Lead Quality": "A"}}])
        [c] = IM.get(self.dir, header["id"])["companies"]
        self.assertEqual(c["custom"]["Lead Quality"], "A")

    def test_imports_list_newest_first_and_by_kind(self):
        a = IM.create(self.dir, name="people.csv", kind="contacts",
                      counts={"rows": 3, "added": 3})
        b = IM.create(self.dir, name="companies.csv", kind="accounts",
                      companies=[{"name": "Acme"}])
        self.assertEqual({h["id"] for h in IM.list_imports(self.dir)}, {a["id"], b["id"]})
        self.assertEqual([h["id"] for h in IM.list_imports(self.dir, "accounts")], [b["id"]])
        self.assertEqual(IM.label(a).split(" · ")[0], "3 contacts")

    def test_companies_of_resolves_only_accounts_imports(self):
        a = IM.create(self.dir, name="companies.csv", kind="accounts",
                      companies=[{"name": "Acme"}])
        c = IM.create(self.dir, name="people.csv", kind="contacts")
        got = IM.companies_of(self.dir, [a["id"], c["id"], "not-an-id"])
        self.assertEqual(list(got), [a["id"]])

    def test_delete(self):
        a = IM.create(self.dir, name="people.csv", kind="contacts")
        self.assertTrue(IM.delete(self.dir, a["id"]))
        self.assertEqual(IM.list_imports(self.dir), [])
        self.assertFalse(IM.delete(self.dir, a["id"]))

    def test_a_hand_mangled_entry_is_kept_through_a_write(self):
        with open(os.path.join(self.dir, IM.FILE), "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "imports": [{"id": "typo", "name": "x"}]}, f)
        IM.create(self.dir, name="people.csv", kind="contacts")
        with open(os.path.join(self.dir, IM.FILE), encoding="utf-8") as f:
            raw = json.load(f)["imports"]
        self.assertIn({"id": "typo", "name": "x"}, raw)

    def test_domain_of(self):
        self.assertEqual(IM.domain_of("https://www.Acme.example/about"), "acme.example")
        self.assertEqual(IM.domain_of("jane@acme.example"), "acme.example")
        self.assertEqual(IM.domain_of(""), "")

    def test_how_far_an_accounts_import_was_searched_is_kept_on_disk(self):
        """A paid search walks an accounts import fifty companies at a time;
        how far it got lives on the record, so a restart does not pay for the
        same companies again."""
        a = IM.create(self.dir, name="companies.csv", kind="accounts",
                      companies=[{"name": f"Co {i}"} for i in range(5)])
        self.assertEqual(a["searched"], 0)
        self.assertTrue(IM.mark_searched(self.dir, a["id"], 3))
        self.assertEqual(IM.get(self.dir, a["id"])["searched"], 3)
        self.assertEqual(IM.label(IM.list_imports(self.dir)[0]).split(" · ")[:2],
                         ["5 companies", "3 searched"])
        IM.mark_searched(self.dir, a["id"], 99)             # clamped to the list
        self.assertEqual(IM.get(self.dir, a["id"])["searched"], 5)
        self.assertIn("all searched", IM.label(IM.list_imports(self.dir)[0]))
        IM.mark_searched(self.dir, a["id"], 0)              # starting over
        self.assertEqual(IM.get(self.dir, a["id"])["searched"], 0)
        self.assertEqual(IM.label(IM.list_imports(self.dir)[0]).split(" · ")[0],
                         "5 companies")

    def test_only_an_accounts_import_has_a_search_position(self):
        c = IM.create(self.dir, name="people.csv", kind="contacts")
        self.assertNotIn("searched", c)
        self.assertFalse(IM.mark_searched(self.dir, c["id"], 1))
        self.assertFalse(IM.mark_searched(self.dir, "not-an-id", 1))
        a = IM.create(self.dir, name="companies.csv", kind="accounts",
                      companies=[{"name": "Acme"}])
        self.assertFalse(IM.mark_searched(self.dir, a["id"], "1"))   # not a count

    def test_a_hand_edited_search_position_is_read_safely(self):
        a = IM.create(self.dir, name="companies.csv", kind="accounts",
                      companies=[{"name": "Acme"}, {"name": "Beta"}])
        path = os.path.join(self.dir, IM.FILE)
        for bad, want in ((-4, 0), ("7", 0), (True, 0), (40, 2)):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["imports"][0]["searched"] = bad
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            self.assertEqual(IM.get(self.dir, a["id"])["searched"], want, bad)


if __name__ == "__main__":
    unittest.main()
