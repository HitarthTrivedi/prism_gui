"""addons.leads.pool — Find People's instant filtering (23-Sep-2026).

The owner's choice: filters answer at once over the people Prism already
holds (saved contacts + every past run), and fetching NEW people from Exa is
a separate button. So this pool must filter the way Apollo does — AND across
filters, OR within one — with the same checks a search enforces, plus the two
CSV-import facets and Total / Net New / Saved.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.filters import SearchSpec                       # noqa: E402
from prospector.models import Dossier, Lead                     # noqa: E402
from addons.leads import pool as P                              # noqa: E402
from addons.leads.contacts import Contact                       # noqa: E402

IMP_C = "imp-20260923-101010-aaaaaa"      # a contacts import
IMP_A = "imp-20260923-101011-bbbbbb"      # an accounts import


def _lead(name, title="", company="", email="", location="", industry=""):
    lead = Lead(name=name, title=title, company=company, email=email, industry=industry)
    if location:
        lead.extra["location"] = location
    return lead


def _pool():
    saved = [
        Contact(lead=_lead("Pratik Mungra", "Company Owner", "Gurukrupa Aluminium",
                           "pratik@gurukrupa.example", "Rajkot, Gujarat, India"),
                saved_at="2026-09-22T10:00:00+05:30", via=["import"], imports=[IMP_C]),
        Contact(lead=_lead("Thomas Hargreaves", "Director Owner", "Glaze Aluminium Facade",
                           "thomas@glaze.example", "Leeds, England, United Kingdom"),
                saved_at="2026-09-22T10:00:00+05:30", via=["import"], imports=[IMP_C]),
    ]
    run = [_lead("Ketan Patel", "Director", "Maco Corporation (India) Pvt. Ltd.",
                 "", "Mumbai, Maharashtra, India"),
           _lead("Amit Patel", "Quality Engineer", "Maco Corporation India Pvt Ltd",
                 "", "Vadodara, Gujarat, India"),
           # Pratik again, found by a search — one person, not two.
           _lead("Pratik Mungra", "Owner", "Gurukrupa Aluminium",
                 "pratik@gurukrupa.example")]
    qualified = [Dossier(lead=run[0], score=81)]
    return P.build(saved, [("s1", "2026-09-22T18:00:00+05:30", run, qualified)])


class BuildingThePool(unittest.TestCase):
    def test_one_row_per_person_however_they_came(self):
        people = _pool()
        self.assertEqual(len(people), 4)
        pratik = next(p for p in people if p.lead.name == "Pratik Mungra")
        self.assertTrue(pratik.saved)
        self.assertEqual(pratik.lead.title, "Company Owner")   # the saved record wins
        self.assertEqual(pratik.sessions, ("s1",))

    def test_a_qualified_run_carries_its_dossier_and_score(self):
        ketan = next(p for p in _pool() if p.lead.name == "Ketan Patel")
        self.assertTrue(ketan.qualified)
        self.assertEqual(ketan.score, 81.0)
        self.assertEqual(ketan.fit, 0.0)          # the FIT column's triage number


class FilteringLikeApollo(unittest.TestCase):
    def names(self, spec, **kw):
        return {p.lead.name for p in P.filter_people(_pool(), spec, **kw)}

    def test_no_filter_is_everyone(self):
        self.assertEqual(len(self.names(SearchSpec())), 4)

    def test_contact_csv_import(self):
        spec = SearchSpec(contact_imports=[IMP_C])
        self.assertEqual(self.names(spec), {"Pratik Mungra", "Thomas Hargreaves"})

    def test_account_csv_import_matches_by_company_name_after_legal_words(self):
        accounts = P.resolve_accounts({IMP_A: [{"name": "Maco Corporation India",
                                                "industry": "Packaging Machinery"}]})
        spec = SearchSpec(account_imports=[IMP_A])
        self.assertEqual(self.names(spec, accounts=accounts),
                         {"Ketan Patel", "Amit Patel"})

    def test_account_csv_import_matches_by_email_domain_too(self):
        accounts = P.resolve_accounts({IMP_A: [{"name": "Somebody Else Entirely",
                                                "website": "https://gurukrupa.example"}]})
        spec = SearchSpec(account_imports=[IMP_A])
        self.assertEqual(self.names(spec, accounts=accounts), {"Pratik Mungra"})

    def test_filters_and_together(self):
        # Director-level AND in Gujarat: Ketan is a Director but in Mumbai
        # (Maharashtra); Pratik is an Owner in Rajkot, Gujarat.
        spec = SearchSpec.from_dict({"seniority": {"include": ["owner", "director"]},
                                     "locations": {"include": ["Gujarat"]}})
        self.assertEqual(self.names(spec), {"Pratik Mungra"})

    def test_values_within_a_filter_or_together(self):
        spec = SearchSpec.from_dict({"locations": {"include": ["Maharashtra",
                                                               "United Kingdom"]}})
        self.assertEqual(self.names(spec), {"Ketan Patel", "Thomas Hargreaves"})

    def test_similar_titles_is_a_real_filter_locally(self):
        # With "similar titles" on, a search only lets an include STEER Exa;
        # over people Prism already holds it must actually filter.
        spec = SearchSpec.from_dict({"job_titles": {"include": ["Director"]}})
        self.assertTrue(spec.similar_titles)
        self.assertEqual(self.names(spec), {"Ketan Patel", "Thomas Hargreaves"})

    def test_an_industry_include_is_enforced_from_the_account_record(self):
        accounts = P.resolve_accounts({IMP_A: [{"name": "Maco Corporation India",
                                                "industry": "Packaging Machinery"}]})
        spec = SearchSpec.from_dict({"account_imports": [IMP_A],
                                     "industries": {"include": ["Packaging"]}})
        self.assertEqual(self.names(spec, accounts=accounts),
                         {"Ketan Patel", "Amit Patel"})
        spec = SearchSpec.from_dict({"industries": {"include": ["Pharmaceuticals"]}})
        self.assertEqual(self.names(spec), set())      # unknown is not a match

    def test_the_search_people_box(self):
        self.assertEqual(self.names(SearchSpec(), query="patel"),
                         {"Ketan Patel", "Amit Patel"})

    def test_email_status_is_a_real_filter(self):
        spec = SearchSpec.from_dict({"email_status": ["no_email"]})
        self.assertEqual(self.names(spec), {"Ketan Patel", "Amit Patel"})
        spec = SearchSpec.from_dict({"email_status": ["guessed"]})
        self.assertEqual(self.names(spec), {"Pratik Mungra", "Thomas Hargreaves"})

    def test_mailed_reads_the_persons_draft(self):
        people = _pool()
        ketan = next(p for p in people if p.lead.name == "Ketan Patel")
        ketan.draft = type("Draft", (), {"status": "sent"})()
        spec = SearchSpec.from_dict({"email_status": ["mailed"]})
        self.assertEqual([p.lead.name for p in P.filter_people(people, spec)],
                         ["Ketan Patel"])

    def test_qualified_only_and_the_fit_floor(self):
        self.assertEqual(self.names(SearchSpec(qualified_only=True)), {"Ketan Patel"})
        people = _pool()
        for p in people:
            p.lead.fit_score = 70 if p.lead.name == "Amit Patel" else 40
        spec = SearchSpec(min_fit=60)
        self.assertEqual([p.lead.name for p in P.filter_people(people, spec)],
                         ["Amit Patel"])


class ASearchKeepsWhoItFound(unittest.TestCase):
    """Industry, keywords and job titles with "similar titles" on only STEER
    a search — it takes whoever comes back. So the people a search found pass
    those same includes on the page, whatever their row happens to carry;
    without that, Find new people "found 300" and the page showed twelve."""

    SPEC = {"job_titles": {"include": ["Plant Head"]},
            "industries": {"include": ["Steel Manufacturing"]},
            "keywords": {"include": ["rolling mill"]}}

    def _people(self, params):
        found = [_lead("Asha Rao", "Works Manager", "Jindal Co", industry="mining & metals"),
                 _lead("Vikram Das", "GM Operations", "Tata Co")]
        held = [Contact(lead=_lead("Held Person", "Accountant", "Other Co"),
                        saved_at="2026-09-21T10:00:00+05:30")]
        return P.build(held, [("s1", "2026-09-22T10:00:00+05:30", found, [], [], params)])

    def names(self, people, spec):
        return sorted(p.lead.name for p in P.filter_people(people, SearchSpec.from_dict(spec)))

    def test_the_searchs_own_people_pass_the_filters_that_found_them(self):
        people = self._people({"mode": "icp_leads_only", "filters": self.SPEC})
        self.assertEqual(self.names(people, self.SPEC), ["Asha Rao", "Vikram Das"])
        asha = next(p for p in people if p.lead.name == "Asha Rao")
        self.assertEqual(asha.steered["industries"], frozenset({"steel manufacturing"}))

    def test_one_value_in_common_is_enough_and_case_does_not_matter(self):
        people = self._people({"filters": self.SPEC})
        spec = {"industries": {"include": ["STEEL manufacturing", "Tyre"]}}
        self.assertEqual(self.names(people, spec), ["Asha Rao", "Vikram Das"])

    def test_a_different_question_is_answered_from_what_they_carry(self):
        people = self._people({"filters": self.SPEC})
        self.assertEqual(self.names(people, {"industries": {"include": ["Pharma"]}}), [])
        self.assertEqual(self.names(people, {"industries": {"include": ["mining"]}}),
                         ["Asha Rao"])                 # her row says so

    def test_what_a_search_enforced_itself_is_still_checked(self):
        # Titles with similar titles OFF are enforced by the search
        # (match_person), so they steer nothing: the page checks them too.
        strict = dict(self.SPEC, similar_titles=False)
        people = self._people({"filters": strict})
        self.assertNotIn("job_titles", people[1].steered)
        self.assertEqual(self.names(people, strict), [])
        # And an exclusion is always enforced, steered or not.
        spec = dict(self.SPEC, industries={"include": ["Steel Manufacturing"],
                                           "exclude": ["Jindal"]})
        self.assertEqual(self.names(self._people({"filters": spec}), spec),
                         ["Vikram Das"])

    def test_a_legacy_run_steers_by_its_industries_and_roles(self):
        people = self._people({"mode": "icp", "industries": ["Steel Manufacturing"],
                               "roles": ["Plant Head"]})
        spec = {"job_titles": {"include": ["Plant Head"]},
                "industries": {"include": ["Steel Manufacturing"]}}
        self.assertEqual(self.names(people, spec), ["Asha Rao", "Vikram Das"])

    def test_a_sheet_run_or_unreadable_params_steer_nothing(self):
        for params in ({"mode": "sheet", "sheet_path": "x.xlsx"}, None, "junk"):
            people = self._people(params)
            self.assertEqual(people[1].steered, {}, params)
            self.assertEqual(self.names(people, {"industries": {"include": ["Steel"]}}),
                             [], params)


class TotalNetNewSaved(unittest.TestCase):
    def test_the_three_tabs(self):
        tabs = P.split(_pool())
        self.assertEqual(len(tabs["total"]), 4)
        self.assertEqual({p.lead.name for p in tabs["saved"]},
                         {"Pratik Mungra", "Thomas Hargreaves"})
        self.assertEqual({p.lead.name for p in tabs["net_new"]},
                         {"Ketan Patel", "Amit Patel"})


class SortingAndPaging(unittest.TestCase):
    def test_relevance_is_best_fit_first(self):
        self.assertEqual(P.sort_people(_pool())[0].lead.name, "Ketan Patel")

    def test_name_sort(self):
        self.assertEqual([p.lead.name for p in P.sort_people(_pool(), "name")],
                         ["Amit Patel", "Ketan Patel", "Pratik Mungra", "Thomas Hargreaves"])

    def test_pages_of_25_like_apollo(self):
        people = [P.Person(lead=_lead(f"P{i}", email=f"p{i}@x.example")) for i in range(60)]
        first = P.page(people, 0)
        self.assertEqual((first["start"], first["end"], first["total"], first["pages"]),
                         (1, 25, 60, 3))
        last = P.page(people, 99)                      # clamped to the last page
        self.assertEqual((last["page"], last["start"], last["end"]), (2, 51, 60))
        empty = P.page([], 0)
        self.assertEqual((empty["start"], empty["end"], empty["pages"]), (0, 0, 1))


if __name__ == "__main__":
    unittest.main()
