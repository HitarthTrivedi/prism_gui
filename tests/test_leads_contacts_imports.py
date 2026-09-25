"""The stores Apollo's Find People needs (23-Sep-2026).

addons/leads/contacts.py — Apollo's "Saved": the people imported, saved,
exported or sequenced; one record per person however they came back, with
their stage, lists, notes and tasks.
addons/leads/accounts.py — the companies kept beside them: one per web
domain, with a stage of their own.
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
from addons.leads import accounts as AC                         # noqa: E402
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

    def test_what_is_not_a_web_address_is_not_a_domain(self):
        """24-Sep-2026: "Not Found" read as the domain "not found", so a sheet
        with 115 of them imported as one company."""
        for text in ("Not Found", "not available", "N/A", "-", "acme", "localhost",
                     "192.168.0.1", "a b.com", "https://", "none"):
            self.assertEqual(IM.domain_of(text), "", text)
        self.assertEqual(IM.domain_of("idmc.company"), "idmc.company")
        self.assertEqual(IM.domain_of("https://x.co.in/a?b=1"), "x.co.in")
        self.assertEqual(IM.domain_of("http://www.se.com/in"), "se.com")

    def _research_sheet(self):
        """AE _ Leads.xlsx in miniature: company research where the websites
        nobody found say "Not Found" or "Not available"."""
        from prospector import importing as IMP
        header = ["Company Name", "Industry Category", "City", "Website", "Approx Employee Size"]
        rows = [["Acme Pumps", "Process Equipment", "Vadodara", "Not Found", "Not Found"],
                ["Beta Valves Pvt Ltd", "Process Equipment", "Halol", "Not Found", "100-250"],
                ["Gamma Drives", "Electrical Equipment", "Savli", "Not Found", "Not Found"],
                ["Delta Controls", "Industrial Automation", "Vadodara", "not available", "500+"],
                ["Epsilon Tools", "OEM Machine Builders", "Bharuch", "Not available", "50-150"],
                ["Kirloskar Pumps", "Process Equipment", "Vadodara", "https://www.kirloskarpumps.com", "1000+"],
                ["Kirloskar Pumps Ltd", "Process Equipment", "Halol", "kirloskarpumps.com", "1000+"],
                ["Acme Pumps", "Packaging Machinery", "Not Found", "Not Found", "Not Found"],
                ["Zeta Works", "OEM Machine Builders", "Ankleshwar", "zetaworks.example", "Large"]]
        companies, skipped = IMP.accounts_from_rows(
            header, rows, IMP.guess_mapping(header, "accounts"))
        self.assertEqual((len(companies), skipped), (9, 0))
        return companies

    def test_a_sheet_full_of_not_found_keeps_every_different_company(self):
        rec = IM.create(self.dir, name="AE _ Leads.xlsx", kind="accounts",
                        companies=self._research_sheet())
        kept = IM.get(self.dir, rec["id"])["companies"]
        # 9 rows: one company named twice, one on the same website twice — and
        # the five with no website at all are five companies, not one.
        self.assertEqual([c["name"] for c in kept],
                         ["Acme Pumps", "Beta Valves Pvt Ltd", "Gamma Drives", "Delta Controls",
                          "Epsilon Tools", "Kirloskar Pumps", "Zeta Works"])
        self.assertEqual([c["domain"] for c in kept if c["domain"]],
                         ["kirloskarpumps.com", "zetaworks.example"])
        self.assertEqual(rec["n_companies"], 7)

    def test_saved_accounts_are_not_merged_into_one_by_a_placeholder_website(self):
        got = AC.save(self.dir, self._research_sheet(), via="import")
        self.assertEqual(got["added"], 7)
        self.assertEqual(len(AC.list_accounts(self.dir)), 7)

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


class ContactStagesListsNotesTasks(unittest.TestCase):
    """What a saved contact carries beyond the person: Apollo's stage (its
    nine defaults, "Cold" to start), the lists they were added to, notes and
    tasks — and Apollo's stage trigger: a message sent moves Cold on to
    Approaching, never a stage the owner set by hand."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_apollos_nine_contact_stages_cold_first(self):
        self.assertEqual(CT.STAGES, ("Cold", "Approaching", "Replied", "Interested",
                                     "Not Interested", "Unresponsive", "Do Not Contact",
                                     "Bad Data", "Changed Job"))
        self.assertEqual(CT.stage_named("  not   interested "), "Not Interested")
        self.assertEqual(CT.stage_named("Waiting on PO"), "Waiting on PO")   # kept
        self.assertEqual(CT.stage_named(""), "")

    def test_a_new_contact_is_cold_unless_the_import_says_otherwise(self):
        CT.save(self.dir, [_lead(email="a@x.example")], via="save")
        CT.save(self.dir, [_lead("Bo", email="b@x.example")], via="import",
                stage_of=lambda lead: "interested")
        stages = {c.lead.email: c.stage for c in CT.list_contacts(self.dir)}
        self.assertEqual(stages, {"a@x.example": "Cold", "b@x.example": "Interested"})

    def test_a_saved_contacts_stage_changes_on_import_only_with_update(self):
        CT.save(self.dir, [_lead(email="a@x.example")], via="save")
        CT.save(self.dir, [_lead(email="a@x.example")], via="import",
                stage_of=lambda lead: "Replied", update=False)
        self.assertEqual(CT.list_contacts(self.dir)[0].stage, "Cold")
        CT.save(self.dir, [_lead(email="a@x.example")], via="import",
                stage_of=lambda lead: "Replied", update=True)
        self.assertEqual(CT.list_contacts(self.dir)[0].stage, "Replied")

    def test_the_imports_stage_column_is_not_kept_on_the_person(self):
        lead = _lead(email="a@x.example")
        lead.extra["stage"] = "Interested"
        CT.save(self.dir, [lead], via="import", stage_of=lambda l: l.extra["stage"])
        CT.save(self.dir, [lead], via="import", update=True)
        [c] = CT.list_contacts(self.dir)
        self.assertNotIn("stage", c.lead.extra)
        self.assertEqual(c.stage, "Interested")

    def test_lists_notes_and_tasks_are_kept_with_the_contact(self):
        lead = _lead(email="a@x.example")
        CT.save(self.dir, [lead], via="list", list_name="  Vadodara   owners ")
        CT.save(self.dir, [lead], via="list", list_name="Vadodara owners")
        note = CT.add_note(self.dir, lead, "Met at the Pune expo")
        task = CT.add_task(self.dir, lead, "Call back about the retrofit", "2026-09-30")
        self.assertTrue(CT.set_task_done(self.dir, lead, task["id"]))
        self.assertFalse(CT.set_task_done(self.dir, lead, task["id"]))   # already done
        [c] = CT.list_contacts(self.dir)
        self.assertEqual(c.lists, ["Vadodara owners"])
        self.assertEqual([n["text"] for n in c.notes], ["Met at the Pune expo"])
        self.assertEqual(note["text"], "Met at the Pune expo")
        self.assertEqual([(t["text"], t["due"], t["done"]) for t in c.tasks],
                         [("Call back about the retrofit", "2026-09-30", True)])

    def test_a_note_or_task_needs_a_saved_contact_and_some_text(self):
        self.assertIsNone(CT.add_note(self.dir, _lead(email="nobody@x.example"), "hi"))
        CT.save(self.dir, [_lead(email="a@x.example")], via="save")
        self.assertIsNone(CT.add_note(self.dir, _lead(email="a@x.example"), "   "))
        self.assertIsNone(CT.add_task(self.dir, _lead(email="a@x.example"), ""))

    def test_set_stage_one_and_many(self):
        a, b = _lead(email="a@x.example"), _lead("Bo", email="b@x.example")
        CT.save(self.dir, [a, b], via="save")
        self.assertTrue(CT.set_stage(self.dir, a, "interested"))
        self.assertFalse(CT.set_stage(self.dir, a, "Interested"))       # already
        self.assertEqual(CT.set_stage_many(self.dir, [a, b], "Do Not Contact"), 2)
        self.assertEqual({c.stage for c in CT.list_contacts(self.dir)}, {"Do Not Contact"})

    def test_a_message_sent_moves_cold_to_approaching_and_nothing_else(self):
        cold, picked = _lead(email="a@x.example"), _lead("Bo", email="b@x.example")
        CT.save(self.dir, [cold, picked], via="save")
        CT.set_stage(self.dir, picked, "Interested")
        self.assertEqual(CT.advance_stage(self.dir, [cold, picked]), 1)
        stages = {c.lead.email: c.stage for c in CT.list_contacts(self.dir)}
        self.assertEqual(stages, {"a@x.example": "Approaching",
                                  "b@x.example": "Interested"})

    def test_edit_contact_info_writes_the_record_and_the_live_lead(self):
        lead = _lead(email="a@x.example", title="Owner")
        CT.save(self.dir, [lead], via="save")
        live = CT.list_contacts(self.dir)[0].lead
        self.assertTrue(CT.edit(self.dir, live, {"title": "Managing Director",
                                                 "location": "Vapi, India",
                                                 "salary": "ignored"}))
        self.assertEqual(live.title, "Managing Director")
        [c] = CT.list_contacts(self.dir)
        self.assertEqual((c.lead.title, c.lead.extra["location"]),
                         ("Managing Director", "Vapi, India"))
        self.assertTrue(CT.edit(self.dir, live, {"location": ""}))     # cleared
        self.assertNotIn("location", CT.list_contacts(self.dir)[0].lead.extra)

    def test_a_hand_edited_file_is_read_safely(self):
        with open(os.path.join(self.dir, CT.FILE), "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "contacts": [{
                "lead": {"name": "Jane", "email": "jane@x.example"},
                "stage": 7, "lists": "not a list", "notes": [{"text": 3}, "x"],
                "tasks": [{"text": "a"}, {"text": "b", "id": "t1"}, {"text": "c", "id": "t1"}]}]}, f)
        [c] = CT.list_contacts(self.dir)
        self.assertEqual((c.stage, c.lists, c.notes), ("7", [], []))
        self.assertEqual(len({t["id"] for t in c.tasks}), 3)          # ids made unique


class SavedAccounts(unittest.TestCase):
    """addons/leads/accounts.py — one company, one account, the way Apollo
    matches them: the web domain, or the name where there is no domain."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_apollos_five_account_stages(self):
        self.assertEqual(AC.STAGES, ("Cold", "Current Client", "Active Opportunity",
                                     "Dead Opportunity", "Do Not Prospect"))

    def test_the_same_domain_is_one_account_and_the_name_joins_where_one_has_none(self):
        got = AC.save(self.dir, [{"name": "Acme Tooling Pvt. Ltd.", "website": "https://www.acme.example"},
                                 {"name": "Acme Tooling Ltd"},                # no domain
                                 {"name": "Other Name", "website": "acme.example/about"},
                                 {"name": "Beta", "website": ""}],
                      via="import", import_id="imp-20260923-101010-aaaaaa")
        self.assertEqual(got["added"], 2)
        names = sorted(a.name for a in AC.list_accounts(self.dir))
        self.assertEqual(names, ["Acme Tooling Pvt. Ltd.", "Beta"])

    def test_two_websites_are_two_companies_whatever_they_are_called(self):
        AC.save(self.dir, [{"name": "Acme", "website": "acme.example"},
                           {"name": "Acme", "website": "acme-india.example"}], via="import")
        self.assertEqual(len(AC.list_accounts(self.dir)), 2)

    def test_a_free_mail_domain_is_nobodys_company(self):
        self.assertEqual(AC.company_domain("someone@gmail.com"), "")
        lead = Lead(name="P", company="Solo Works", email="p@gmail.com")
        self.assertIsNone(AC.from_lead(lead, "domain"))
        self.assertEqual(AC.from_lead(lead, "name")["name"], "Solo Works")

    def test_a_person_is_matched_to_their_account(self):
        AC.save(self.dir, [{"name": "Rao Precision Works", "website": "raoprecision.example"},
                           {"name": "Gulf Works"}], via="import")
        accounts = AC.list_accounts(self.dir)
        by_mail = Lead(name="A", company="Something Else", email="a@raoprecision.example")
        by_name = Lead(name="B", company="Gulf Works LLC")
        self.assertEqual(AC.match(accounts, by_mail).name, "Rao Precision Works")
        self.assertEqual(AC.match(accounts, by_name).name, "Gulf Works")
        self.assertIsNone(AC.match(accounts, Lead(name="C", company="Nobody Inc")))

    def test_stages_update_and_stage_setting(self):
        AC.save(self.dir, [{"name": "Acme", "website": "acme.example", "stage": "current client"}],
                via="import", stage_of=lambda c: c.get("stage"))
        [a] = AC.list_accounts(self.dir)
        self.assertEqual(a.stage, "Current Client")
        AC.save(self.dir, [{"name": "Acme", "website": "acme.example", "industry": "Machinery"}],
                via="enrich", update=True)
        self.assertTrue(AC.set_stage(self.dir, AC.list_accounts(self.dir)[0], "Dead Opportunity"))
        [a] = AC.list_accounts(self.dir)
        self.assertEqual((a.industry, a.stage, a.via), ("Machinery", "Dead Opportunity",
                                                        ["import", "enrich"]))


class ContactActivities(unittest.TestCase):
    """A contact's history — the person panel's Activities (Apollo: "a log
    of all interactions between your organization and the contact"): only
    what Prism saw happen, each with when."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def kinds(self):
        [c] = CT.list_contacts(self.dir)
        return [(h["kind"], h["text"]) for h in c.history]

    def test_saving_listing_and_stage_moves_are_kept(self):
        lead = _lead(email="a@x.example")
        CT.save(self.dir, [lead], via="import", list_name="Expo leads")
        CT.save(self.dir, [lead], via="export")
        CT.save(self.dir, [lead], via="export")               # nothing new: no line
        CT.set_stage(self.dir, lead, "Interested")
        CT.advance_stage(self.dir, [lead])                     # not Cold: no move
        CT.set_stage_many(self.dir, [lead], "Do Not Contact")
        self.assertEqual(self.kinds(), [
            ("saved", "import"), ("list", "Expo leads"), ("saved", "export"),
            ("stage", "Cold → Interested"), ("stage", "Interested → Do Not Contact")])
        [c] = CT.list_contacts(self.dir)
        self.assertTrue(all(h["at"] for h in c.history))

    def test_edits_logged_activities_and_sends(self):
        lead = _lead(email="a@x.example", title="Owner")
        CT.save(self.dir, [lead], via="save")
        CT.edit(self.dir, lead, {"title": "Managing Director", "location": "Vapi"})
        self.assertEqual(CT.log(self.dir, lead, "call", " Asked for the brochure ")["text"],
                         "Asked for the brochure")
        self.assertIsNone(CT.log(self.dir, lead, "fax", "no"))      # not a kind
        CT.log(self.dir, lead, "flagged")
        self.assertEqual(CT.log_sent(self.dir, [(lead, "Your second plant")]), 1)
        self.assertEqual(self.kinds()[1:], [
            ("edited", "title, location"), ("call", "Asked for the brochure"),
            ("flagged", ""), ("sent", "Your second plant")])

    def test_nobody_saved_logs_nothing(self):
        self.assertIsNone(CT.log(self.dir, _lead(email="n@x.example"), "call", "hi"))
        self.assertEqual(CT.log_sent(self.dir, [(_lead(email="n@x.example"), "Hi")]), 0)

    def test_a_hand_edited_history_is_read_safely_and_capped(self):
        rows = [{"at": "2026-09-23", "kind": "call", "text": f"call {i}"} for i in range(600)]
        rows += [{"kind": "bogus"}, "x", {"kind": "stage", "text": 5}]
        with open(os.path.join(self.dir, CT.FILE), "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "contacts": [{
                "lead": {"name": "Jane", "email": "jane@x.example"}, "history": rows}]}, f)
        [c] = CT.list_contacts(self.dir)
        self.assertEqual(len(c.history), 500)
        self.assertEqual(c.history[-1]["text"], "call 599")

    def test_get_reads_one_contact_as_the_file_has_it(self):
        lead = _lead(email="a@x.example")
        CT.save(self.dir, [lead], via="save")
        CT.add_note(self.dir, lead, "Met at the expo")
        self.assertEqual([n["text"] for n in CT.get(self.dir, lead).notes], ["Met at the expo"])
        self.assertIsNone(CT.get(self.dir, _lead("No Body", "Elsewhere",
                                                 email="nobody@x.example")))

    def test_get_sees_every_write_at_once(self):
        # get() keeps the parsed file between asks; a write inside the file
        # clock's resolution must still show — every writer drops the copy.
        lead = _lead(email="a@x.example")
        CT.save(self.dir, [lead], via="save")
        self.assertEqual(CT.get(self.dir, lead).stage, "Cold")
        for stage in ("Replied", "Unresponsive", "Interested"):
            CT.set_stage(self.dir, lead, stage)
            self.assertEqual(CT.get(self.dir, lead).stage, stage)
        task = CT.add_task(self.dir, lead, "Call")
        for done in (True, False, True):
            CT.set_task_done(self.dir, lead, task["id"], done)
            self.assertIs(CT.get(self.dir, lead).tasks[0]["done"], done)


if __name__ == "__main__":
    unittest.main()
