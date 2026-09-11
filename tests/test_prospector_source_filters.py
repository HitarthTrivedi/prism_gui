"""Filters are rules, not hints — the sourcing half.

Leads & Outreach builds a list from Apollo / Sales Nav style filters ("Location:
anywhere, except India"). Exa has no exclusion parameter, so source() checks
every person who comes back. What is pinned here:

  · someone outside the filters uses no company or industry slot, is not
    counted as already pulled, and is counted once however often Exa returns
    them;
  · filters that turn people away earn top-up rounds even with no skip list,
    and a top-up never re-sends a question already asked;
  · a company-level filter looks each employer up once per run, within its
    cap, and a company that can't be looked up passes and is counted — except
    under a Company HQ filter, where unproven is not a pass;
  · annual revenue bands drop a company whose revenue on record is outside
    them; one with no revenue on record passes and is counted unverified, and
    the figure Exa gives is read as whole US dollars or not at all;
  · two top-up rounds of nothing but failed calls end the top-up;
  · a spec may arrive as its plain dict;
  · end to end with the real filters: "anywhere except India" keeps Dubai and
    London, drops Pune and Bengaluru, and never says "India" to Exa.

No network: source._exa_people and source._exa_company are recorders. The
filter functions are stubbed where a test is about source() itself.
"""
from __future__ import annotations

import itertools
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import filters, identity, source  # noqa: E402
from prospector.filters import SearchSpec          # noqa: E402
from prospector.identity import SeenIndex          # noqa: E402
from prospector.models import Lead                 # noqa: E402

_FRESH = object()


def _person(name: str, company: str, location: str = "Dubai, United Arab Emirates",
            title: str = "Plant Head", slug: str = "") -> dict:
    """One Exa people-search row, shaped like the live API's."""
    slug = slug or name.lower().replace(" ", "-")
    return {"url": f"https://www.linkedin.com/in/{slug}",
            "entities": [{"type": "person", "properties": {
                "name": name, "location": location,
                "workHistory": [
                    {"title": title, "company": {"name": company},
                     "dates": {"from": "2021-04-01", "to": None}},
                ]}}]}


class _Exa:
    """Stands in for source._exa_people: records every query and answers with
    reply(query, call_number), under one lock (source() calls from threads)."""

    def __init__(self, reply):
        self._reply, self._lock, self.queries = reply, threading.Lock(), []

    def __call__(self, query, api_key, n=50, timeout=60):
        with self._lock:
            self.queries.append(query)
            return self._reply(query, len(self.queries) - 1)


class _Companies:
    """Stands in for source._exa_company: records every name looked up."""

    def __init__(self, answers=None):
        self._answers, self._lock, self.names = answers or {}, threading.Lock(), []

    def __call__(self, name, api_key, timeout=30):
        with self._lock:
            self.names.append(name)
            return self._answers.get(name)


def _india_out(spec, lead, props=None, today=None):
    """A person filter stub: anyone whose location says India fails."""
    return "location" if "india" in (lead.extra.get("location") or "").lower() else ""


def _spec(**facets) -> SearchSpec:
    """A spec that enforces a filter (Location except India) unless told otherwise."""
    raw = {"job_titles": {"include": ["Plant Head"]},
           "locations": {"exclude": ["India"]}}
    raw.update(facets)
    return SearchSpec.from_dict(raw)


class _Stubbed(unittest.TestCase):
    """source() with the five filter functions stubbed (create=True: top_up and
    friends may still be stubs in filters.py while it is being built)."""

    def _source(self, reply, *, plan, top_up=None, match_person=_india_out,
                needs_facts=False, match_company=None, companies=None,
                spec=_FRESH, stats=_FRESH, **kw):
        exa = _Exa(reply)
        comp = companies if companies is not None else _Companies()
        stats = {} if stats is _FRESH else stats
        spec = _spec() if spec is _FRESH else spec
        top_up = top_up or (lambda s, n: [])
        match_company = match_company or (lambda s, lead, facts: "")
        self.plan_arg = self.person_arg = None

        def _plan(s):
            self.plan_arg = s
            return list(plan)

        def _person_check(s, lead, props=None, today=None):
            self.person_arg = s
            return match_person(s, lead, props, today)

        with mock.patch.object(source, "_exa_people", exa), \
                mock.patch.object(source, "_exa_company", comp), \
                mock.patch.object(filters, "plan", _plan, create=True), \
                mock.patch.object(filters, "top_up", top_up, create=True), \
                mock.patch.object(filters, "match_person", _person_check, create=True), \
                mock.patch.object(filters, "needs_company_facts",
                                  lambda s: needs_facts, create=True), \
                mock.patch.object(filters, "match_company", match_company, create=True):
            leads = source.source(["ignored industry"], ["ignored role"], "exa-test-key",
                                  location="ignored place", spec=spec, stats=stats, **kw)
        return leads, stats, exa, comp


# ── person filters ───────────────────────────────────────────────────────────

class OutsideTheFiltersTakesNoSlot(_Stubbed):

    def test_excluded_people_use_no_company_or_industry_slot_and_are_not_skipped_seen(self):
        auto = [_person("Jane Doe", "Acme", "Pune, Maharashtra, India"),
                _person("Raj Iyer", "Gamma Auto", "Chennai, India"),
                _person("John Roe", "Acme", "Dubai, United Arab Emirates"),
                _person("Ann Lee", "Beta Motors", "London, United Kingdom")]
        plan = [("automobile", "Plant Head at automobile companies in Europe"),
                ("pharma", "Plant Head at pharma companies in Europe")]
        # Jane was pulled in an earlier session too — but she is outside the
        # filters, and that is what she counts as.
        skip = SeenIndex(identity.keys_of(Lead(name="Jane Doe", company="Acme")))
        # per_company 1 and target 4 over two industries: each industry's share
        # is 2 and Acme has one slot. If Jane or Raj took a slot, John or Ann
        # would be lost.
        leads, stats, exa, _ = self._source(
            lambda q, i: auto if "automobile" in q else [], plan=plan,
            per_company=1, target=4, skip=skip, max_extra_queries=0)
        self.assertEqual([l.name for l in leads], ["John Roe", "Ann Lee"])
        self.assertEqual(stats["skipped_seen"], 0)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(stats["filtered"], {"location": 2})
        # The plan made the searches; industries, roles and location were ignored.
        self.assertEqual(exa.queries, [q for _, q in plan])
        self.assertIsInstance(self.plan_arg, SearchSpec)

    def test_filtered_counts_each_person_once(self):
        rows = [_person("Jane Doe", "Acme", "Pune, India"),
                _person("Raj Iyer", "Gamma Auto", "Chennai, India"),
                _person("Ann Lee", "Beta Motors", "London, United Kingdom")]
        plan = [("automobile", f"query {k}") for k in range(3)]
        leads, stats, exa, _ = self._source(lambda q, i: rows, plan=plan, target=10,
                                            max_extra_queries=0)
        self.assertEqual(len(exa.queries), 3)
        self.assertEqual([l.name for l in leads], ["Ann Lee"])
        self.assertEqual(stats["filtered"], {"location": 2})
        self.assertEqual(stats["duplicates"], 2)        # Ann again from queries 1 and 2

    def test_spec_stats_carry_every_key(self):
        _, stats, _, _ = self._source(lambda q, i: [_person("Ann Lee", "Beta Motors")],
                                      plan=[("automobile", "q")], target=1)
        self.assertEqual(stats, {"skipped_seen": 0, "duplicates": 0, "queries_used": 1,
                                 "query_errors": 0, "extra_queries": 0, "short_by": 0,
                                 "filtered": {}, "company_lookups": 0,
                                 "company_unverified": 0})

    def test_spec_as_a_dict(self):
        raw = {"job_titles": {"include": ["Plant Head"]},
               "locations": {"exclude": ["India"]}}
        leads, _, _, _ = self._source(
            lambda q, i: [_person("Ann Lee", "Beta Motors"),
                          _person("Jane Doe", "Acme", "Pune, India")],
            plan=[("automobile", "q")], spec=raw, target=5, max_extra_queries=0)
        self.assertEqual([l.name for l in leads], ["Ann Lee"])
        self.assertIsInstance(self.plan_arg, SearchSpec)
        self.assertIsInstance(self.person_arg, SearchSpec)
        self.assertEqual(self.person_arg.locations.exclude, ["India"])


# ── top-up with filters ──────────────────────────────────────────────────────

class FiltersEarnATopUp(_Stubbed):

    @staticmethod
    def _fresh_people():
        fresh = itertools.count()

        def reply(q, i):
            n = next(fresh)
            return [_person(f"Person {n}", f"Company {n}", slug=f"person-{n}")]
        return reply

    def test_top_up_runs_with_filters_and_no_skip(self):
        rounds = {1: [("automobile", "Plant Head at automobile firms in Europe")],
                  2: [("automobile", "Plant Head at automobile makers in the Middle East")]}
        leads, stats, exa, _ = self._source(
            self._fresh_people(), plan=[("automobile", "Plant Head in Europe")],
            top_up=lambda s, n: rounds.get(n, []), target=10)
        self.assertEqual(exa.queries, ["Plant Head in Europe",
                                       rounds[1][0][1], rounds[2][0][1]])
        self.assertEqual(len(leads), 3)
        self.assertEqual(stats["extra_queries"], 2)
        self.assertEqual(stats["short_by"], 7)

    def test_a_spec_that_enforces_nothing_does_not_top_up(self):
        """Titles with "similar titles" on and an industry include only steer the
        search — nobody is turned away, so there is nothing to make up."""
        spec = SearchSpec.from_dict({"job_titles": {"include": ["Plant Head"]},
                                     "industries": {"include": ["automobile"]}})
        top_up = mock.Mock(return_value=[("automobile", "another question")])
        _, stats, exa, _ = self._source(
            self._fresh_people(), plan=[("automobile", "q")], top_up=top_up,
            spec=spec, target=10)
        self.assertEqual(len(exa.queries), 1)
        top_up.assert_not_called()
        self.assertEqual(stats["extra_queries"], 0)

    def test_no_identical_query_is_sent_twice(self):
        plan = [("automobile", "Plant Head in Europe"), ("pharma", "Plant Head in Asia")]
        rounds = {1: [("pharma", "PLANT HEAD  in asia"),          # the cut plan entry again
                      ("automobile", "Plant Head in Africa"),
                      ("automobile", "plant head in europe")],    # the first pass again
                  2: [("automobile", "Plant Head in Africa"),     # round 1 again
                      ("automobile", "Plant Head in Oceania")]}
        _, stats, exa, _ = self._source(self._fresh_people(), plan=plan, max_queries=1,
                                        top_up=lambda s, n: rounds.get(n, []), target=50)
        asked = [" ".join(q.casefold().split()) for q in exa.queries]
        self.assertEqual(len(asked), len(set(asked)), "an Exa query was sent twice")
        self.assertEqual(exa.queries, ["Plant Head in Europe", "Plant Head in Asia",
                                       "Plant Head in Africa", "Plant Head in Oceania"])
        self.assertEqual(stats["extra_queries"], 3)

    def test_top_up_stays_inside_its_budget(self):
        top_up = lambda s, n: [("automobile", f"round {n} query {k}") for k in range(4)]
        _, stats, exa, _ = self._source(self._fresh_people(), plan=[("automobile", "q")],
                                        top_up=top_up, target=500, max_extra_queries=6)
        self.assertEqual(len(exa.queries), 7)
        self.assertEqual(stats["extra_queries"], 6)

    def test_two_rounds_of_nothing_but_failed_calls_end_the_top_up(self):
        top_up = lambda s, n: [("automobile", f"round {n} query {k}") for k in range(2)]
        _, stats, exa, _ = self._source(lambda q, i: None, plan=[("automobile", "q")],
                                        top_up=top_up, target=10, max_extra_queries=30)
        self.assertEqual(len(exa.queries), 1 + 2 + 2)   # first pass, two dead rounds
        self.assertEqual(stats["query_errors"], 5)
        self.assertEqual(stats["extra_queries"], 4)

    def test_one_dead_round_between_good_ones_does_not_end_it(self):
        fresh = itertools.count()

        def reply(q, i):
            if "round 1" in q or "round 3" in q:
                return None
            n = next(fresh)
            return [_person(f"Person {n}", f"Company {n}", slug=f"person-{n}")]
        top_up = lambda s, n: [("automobile", f"round {n}")] if n <= 5 else []
        leads, stats, exa, _ = self._source(reply, plan=[("automobile", "q")],
                                            top_up=top_up, target=10)
        self.assertEqual(len(exa.queries), 6)           # all five rounds ran
        self.assertEqual(stats["query_errors"], 2)
        self.assertEqual(len(leads), 4)

    def test_the_dead_round_stop_holds_for_a_skip_run_too(self):
        """The old ICP path (no spec) shares the top-up loop: a spent key does
        not burn the whole budget there either."""
        exa = _Exa(lambda q, i: None)
        stats = {}
        with mock.patch.object(source, "_exa_people", exa):
            source.source(["automobile"], ["Plant Head"], "exa-test-key", target=10,
                          skip=SeenIndex(), stats=stats)
        self.assertEqual(len(exa.queries), 1 + 2)       # first pass, two dead rounds
        self.assertNotIn("filtered", stats)


# ── company facts ────────────────────────────────────────────────────────────

class CompanyFactsAreLookedUpOnce(_Stubbed):

    def test_one_lookup_per_company_across_batches(self):
        # 10 queries = two parallel batches of 8 and 2; every one returns
        # another person at Acme.
        plan = [("automobile", f"query {k}") for k in range(10)]
        rows = lambda q, i: [_person(f"Acme Person {i}", "Acme Pvt Ltd", slug=f"acme-{i}"),
                             _person(f"Beta Person {i}", "Beta Motors Limited",
                                     slug=f"beta-{i}")]
        comp = _Companies({"Acme Pvt Ltd": {"headcount": 800, "hq": "Dubai, UAE",
                                            "description": "", "domain": "acme.ae"}})
        leads, stats, _, _ = self._source(rows, plan=plan, needs_facts=True, companies=comp,
                                          per_company=50, target=100, max_extra_queries=0)
        self.assertEqual(sorted(comp.names), ["Acme Pvt Ltd", "Beta Motors Limited"])
        self.assertEqual(stats["company_lookups"], 2)
        self.assertEqual(stats["company_unverified"], 1)        # Beta: nothing found
        acme = [l for l in leads if l.company == "Acme Pvt Ltd"]
        self.assertEqual(len(acme), 10)
        self.assertTrue(all(l.extra["headcount"] == 800 for l in acme))
        self.assertTrue(all(l.extra["company_hq"] == "Dubai, UAE" for l in acme))
        self.assertTrue(all("headcount" not in l.extra for l in leads
                            if l.company.startswith("Beta")))

    def test_the_lookup_cap_is_respected_and_the_rest_pass_unverified(self):
        rows = [_person(f"Person {k}", f"Company {k}", slug=f"p-{k}") for k in range(6)]
        facts = {"headcount": 5000, "hq": "London, United Kingdom", "description": "",
                 "domain": "x.com"}
        comp = _Companies({f"Company {k}": facts for k in range(6)})
        leads, stats, _, _ = self._source(lambda q, i: rows, plan=[("automobile", "q")],
                                          needs_facts=True, companies=comp,
                                          max_company_lookups=2, target=10,
                                          max_extra_queries=0)
        # The first two in row order (sorted: the lookups run in a thread pool).
        self.assertEqual(sorted(comp.names), ["Company 0", "Company 1"])
        self.assertEqual(stats["company_lookups"], 2)
        self.assertEqual(stats["company_unverified"], 4)
        self.assertEqual(len(leads), 6)

    def test_people_who_cannot_be_taken_buy_no_lookup(self):
        rows = [_person("Jane Doe", "India Only Co", "Pune, India"),
                _person("Old Friend", "Pulled Before Co"),
                _person("Ann Lee", "Beta Motors")]
        skip = SeenIndex(identity.keys_of(Lead(name="Old Friend", company="Pulled Before Co")))
        comp = _Companies()
        self._source(lambda q, i: rows, plan=[("automobile", "q")], needs_facts=True,
                     companies=comp, skip=skip, target=10, max_extra_queries=0)
        self.assertEqual(comp.names, ["Beta Motors"])

    def test_none_facts_pass_and_are_counted(self):
        rows = [_person("Ann Lee", "Beta Motors"), _person("Raj Iyer", "Gamma Auto"),
                _person("Meera Rao", "Gamma Auto", slug="meera")]
        seen_facts = []

        def match_company(s, lead, facts):
            seen_facts.append(facts)
            return "headcount"          # would turn everyone away — if it were asked

        leads, stats, _, _ = self._source(lambda q, i: rows, plan=[("automobile", "q")],
                                          needs_facts=True, match_company=match_company,
                                          target=10, max_extra_queries=0)
        self.assertEqual(len(leads), 3)
        self.assertEqual(seen_facts, [])
        self.assertEqual(stats["company_unverified"], 2)
        self.assertEqual(stats["filtered"], {})

    def test_a_company_that_fails_turns_its_people_away_once_each(self):
        small = {"headcount": 8, "hq": "Dubai, United Arab Emirates", "description": "",
                 "domain": "tiny.ae"}
        big = {"headcount": 900, "hq": "Dubai, United Arab Emirates", "description": "",
               "domain": "big.ae"}
        comp = _Companies({"Tiny Works": small, "Big Works": big})
        rows = [_person("Ann Lee", "Tiny Works"), _person("Raj Iyer", "Tiny Works"),
                _person("Meera Rao", "Big Works")]

        def match_company(s, lead, facts):
            return "headcount" if facts["headcount"] < 50 else ""

        leads, stats, _, _ = self._source(lambda q, i: rows,
                                          plan=[("automobile", "q1"), ("automobile", "q2")],
                                          needs_facts=True, companies=comp,
                                          match_company=match_company, per_company=1,
                                          target=10, max_extra_queries=0)
        self.assertEqual([l.name for l in leads], ["Meera Rao"])
        self.assertEqual(stats["filtered"], {"headcount": 2})
        self.assertEqual(stats["company_lookups"], 2)


class CompanyHqExclusionIsARule(unittest.TestCase):
    """Company HQ: exclude India, with the REAL filters. A company past the
    lookup cap, or one the lookup could not find, used to pass unverified — so
    once the budget was spent the exclusion was quietly off."""

    def test_unverified_companies_take_no_slot_under_an_hq_filter(self):
        rows = [_person(f"Person {k}", f"Company {k}", "London, United Kingdom",
                        slug=f"p-{k}") for k in range(6)]
        # Company 0 is found in Germany; Company 1 is found in India; the rest
        # are past the cap (2 lookups) or not found.
        comp = _Companies({"Company 0": {"headcount": 900, "hq": "Stuttgart, Germany",
                                         "description": "", "domain": "c0.de"},
                           "Company 1": {"headcount": 900, "hq": "Mumbai, India",
                                         "description": "", "domain": "c1.in"}})
        spec = {"job_titles": {"include": ["Plant Head"]},
                "company_hq": {"exclude": ["India"]}}
        exa, stats = _Exa(lambda q, i: rows), {}
        with mock.patch.object(source, "_exa_people", exa), \
                mock.patch.object(source, "_exa_company", comp):
            leads = source.source([], [], "exa-test-key", spec=spec, target=10,
                                  max_company_lookups=2, max_extra_queries=0,
                                  stats=stats)
        self.assertEqual([l.company for l in leads], ["Company 0"])
        self.assertEqual(stats["filtered"], {"company_hq": 1, "company_hq_unknown": 4})
        self.assertEqual(stats["company_lookups"], 2)
        self.assertEqual(stats["company_unverified"], 4)

    def test_without_an_hq_filter_unverified_still_passes(self):
        rows = [_person("Ann Lee", "Beta Motors")]
        spec = {"job_titles": {"include": ["Plant Head"]}, "headcount": ["51-200"]}
        exa, stats = _Exa(lambda q, i: rows), {}
        with mock.patch.object(source, "_exa_people", exa), \
                mock.patch.object(source, "_exa_company", _Companies()):
            leads = source.source([], [], "exa-test-key", spec=spec, target=10,
                                  max_extra_queries=0, stats=stats)
        self.assertEqual(len(leads), 1)
        self.assertEqual(stats["company_unverified"], 1)


class RevenueBandsAreChecked(unittest.TestCase):
    """Annual revenue, with the REAL filters: each employer is looked up once, a
    company whose revenue on record is outside the bands takes no slot, and one
    with no revenue on record — or not found at all — passes, counted
    unverified, the same rule as headcount."""

    @staticmethod
    def _facts(revenue):
        return {"headcount": 900, "revenue": revenue, "hq": "Dubai, United Arab Emirates",
                "description": "", "domain": "motors.ae"}

    def test_out_of_band_companies_are_dropped_and_unknown_revenue_passes(self):
        rows = [_person("Ann Lee", "Mid Motors"), _person("Raj Iyer", "Giant Motors"),
                _person("Meera Rao", "Quiet Motors"), _person("Omar Haddad", "Ghost Motors"),
                _person("Emma Clark", "Mid Motors"), _person("Li Wei", "Giant Motors")]
        comp = _Companies({"Mid Motors": self._facts(25_000_000),
                           "Giant Motors": self._facts(3_000_000_000),
                           "Quiet Motors": self._facts(None)})
        spec = {"job_titles": {"include": ["Plant Head"]},
                "revenue": ["10m-50m", "50m-100m"]}
        exa, stats = _Exa(lambda q, i: rows), {}
        with mock.patch.object(source, "_exa_people", exa), \
                mock.patch.object(source, "_exa_company", comp):
            leads = source.source([], [], "exa-test-key", spec=spec, target=10,
                                  max_extra_queries=0, stats=stats)
        self.assertEqual([l.name for l in leads],
                         ["Ann Lee", "Meera Rao", "Omar Haddad", "Emma Clark"])
        self.assertEqual(sorted(comp.names),
                         ["Ghost Motors", "Giant Motors", "Mid Motors", "Quiet Motors"])
        self.assertEqual(stats["company_lookups"], 4)
        self.assertEqual(stats["filtered"], {"revenue": 2})         # Raj and Li, once each
        # Quiet Motors (found, no revenue on record) and Ghost Motors (not found).
        self.assertEqual(stats["company_unverified"], 2)
        by_name = {l.name: l for l in leads}
        self.assertEqual(by_name["Ann Lee"].extra["revenue"], 25_000_000)
        self.assertEqual(by_name["Ann Lee"].extra["headcount"], 900)
        self.assertNotIn("revenue", by_name["Meera Rao"].extra)
        self.assertNotIn("revenue", by_name["Omar Haddad"].extra)

    def test_revenue_bands_need_the_lookup_and_earn_a_top_up(self):
        spec = SearchSpec.from_dict({"job_titles": {"include": ["Plant Head"]},
                                     "revenue": ["gt1b"]})
        self.assertTrue(filters.needs_company_facts(spec))
        self.assertTrue(source._enforces(spec))
        self.assertFalse(source._enforces(SearchSpec.from_dict(
            {"job_titles": {"include": ["Plant Head"]}, "revenue": ["a lot"]})))

    def test_a_company_found_without_its_size_is_unverified_under_a_band_only(self):
        rows = [_person("Ann Lee", "Quiet Motors")]
        titles = {"job_titles": {"include": ["Plant Head"]}}
        for spec, unverified in ((dict(titles, company_hq={"exclude": ["India"]}), 0),
                                 (dict(titles, headcount=["51-200"]), 1),
                                 (dict(titles, revenue=["lt1m"]), 1)):
            quiet = dict(self._facts(None), headcount=None)
            exa, stats = _Exa(lambda q, i: rows), {}
            with self.subTest(spec=spec), \
                    mock.patch.object(source, "_exa_people", exa), \
                    mock.patch.object(source, "_exa_company",
                                      _Companies({"Quiet Motors": quiet})):
                leads = source.source([], [], "exa-test-key", spec=spec, target=10,
                                      max_extra_queries=0, stats=stats)
                self.assertEqual(len(leads), 1)
                self.assertEqual(stats["company_unverified"], unverified)


class TheRevenueFigure(unittest.TestCase):
    """source._revenue: what Exa's financials.revenueAnnual holds, as whole US
    dollars — or None, which never fails a filter."""

    TABLE = [
        (12_500_000, 12_500_000), (12_500_000.4, 12_500_000), (4.2e9, 4_200_000_000),
        ("12500000", 12_500_000), ("12500000.0", 12_500_000), (" 300000 ", 300_000),
        ("12,500,000", 12_500_000), ("12,50,00,000", 125_000_000),
        ("1,234", 1_234), ("1,25,000", 125_000),
        ("$12.5M", 12_500_000), ("1.2B", 1_200_000_000), ("$1.2 billion", 1_200_000_000),
        ("USD 850K", 850_000), ("US$ 3 million", 3_000_000), ("45mn", 45_000_000),
        ("$7MM", 7_000_000), ("2.5 bn USD", 2_500_000_000), ("$1T", 10 ** 12),
        (0, None), (-5, None), (0.4, None), ("0", None), ("-$5M", None),
        (True, None), (False, None), (None, None), (float("nan"), None),
        (float("inf"), None), ("", None), ("n/a", None), ("unknown", None),
        ("₹500 crore", None), ("€12M", None), ("INR 40 lakh", None), ("1,2M", None),
        ("1,25M", None), ("1,50M", None), ("3,75B", None), ("100,00", None),
        ("12.5.3M", None), ("1e6", None), ("$", None), ({"value": 5}, None), ([12], None),
        (10 ** 400, None), ("9" * 400, None),
    ]

    def test_the_table(self):
        for given, expected in self.TABLE:
            with self.subTest(given=given):
                got = source._revenue(given)
                self.assertEqual(got, expected)
                if got is not None:
                    self.assertIs(type(got), int)


class AnywhereExceptIndiaEndToEnd(unittest.TestCase):
    """The owner's case, with the REAL filters and places: "Global except india"
    used to be pasted into the Exa query and pulled Indian people in."""

    def test_only_people_outside_india_are_kept_and_india_is_never_asked_for(self):
        rows = [_person("Asha Mehta", "Pune Forgings", "Pune, Maharashtra, India"),
                _person("Ravi Kumar", "Blr Castings", "Bengaluru, Karnataka"),
                _person("Omar Haddad", "Gulf Motors", "Dubai, United Arab Emirates"),
                _person("Emma Clark", "Thames Auto", "London, England, United Kingdom")]
        spec = {"job_titles": {"include": ["Plant Head"]},
                "industries": {"include": ["automobile", "pharma"]},
                "locations": {"exclude": ["India"]}}
        exa, comp, stats = _Exa(lambda q, i: rows), _Companies(), {}
        with mock.patch.object(source, "_exa_people", exa), \
                mock.patch.object(source, "_exa_company", comp):
            leads = source.source([], [], "exa-test-key", spec=spec, target=10,
                                  stats=stats)
        self.assertEqual([l.name for l in leads], ["Omar Haddad", "Emma Clark"])
        self.assertEqual(stats["filtered"], {"location": 2})
        self.assertEqual(stats["skipped_seen"], 0)
        self.assertTrue(exa.queries)
        for q in exa.queries:
            self.assertNotIn("india", q.casefold(), q)
            self.assertNotIn("mumbai", q.casefold(), q)
        # Filters that turn people away earned a top-up, which ended when a
        # round found nobody new; a location filter needs no company lookup.
        self.assertGreater(stats["extra_queries"], 0)
        self.assertEqual(comp.names, [])
        self.assertEqual(stats["company_lookups"], 0)


class TheCompanyLookupCall(unittest.TestCase):
    """_exa_company: picks the entity that is the company, or says None."""

    def _call(self, **post):
        with mock.patch("requests.post", **post) as p:
            return source._exa_company("Acme Motors Pvt Ltd", "exa-test-key"), p

    def test_the_best_matching_entity_is_read(self):
        body = {"results": [
            {"url": "https://www.acme-foods.com/", "entities": [{"type": "company",
             "properties": {"name": "Acme Foods", "workforce": {"total": 12}}}]},
            {"url": "https://www.acmemotors.com/about", "entities": [{"type": "company",
             "properties": {"name": "Acme Motors Limited", "workforce": {"total": 1450},
                            "description": "Makes gearboxes.",
                            "financials": {"revenueAnnual": 412000000,
                                           "fundingTotal": None},
                            "headquarters": {"address": "1 Road", "city": "Pune",
                                             "country": "India"}}}]}]}
        reply = mock.Mock(status_code=200, json=lambda: body)
        got, post = self._call(return_value=reply)
        self.assertEqual(got, {"headcount": 1450, "revenue": 412_000_000,
                               "hq": "Pune, India", "description": "Makes gearboxes.",
                               "domain": "acmemotors.com"})
        sent = post.call_args.kwargs["json"]
        self.assertEqual((sent["category"], sent["numResults"]), ("company", 3))
        self.assertEqual(sent["query"], "Acme Motors Pvt Ltd company")

    def test_revenue_not_on_record_is_none(self):
        for financials in (None, "big", {}, {"revenueAnnual": None},
                           {"revenueAnnual": "₹3,400 crore"}, {"revenueAnnual": 0}):
            body = {"results": [{"url": "https://www.acmemotors.com/", "entities": [
                {"type": "company", "properties": {"name": "Acme Motors",
                                                   "financials": financials}}]}]}
            with self.subTest(financials=financials):
                got, _ = self._call(return_value=mock.Mock(status_code=200,
                                                           json=lambda: body))
                self.assertIsNone(got["revenue"])
                self.assertIsNone(got["headcount"])
        body = {"results": [{"url": "https://www.acmemotors.com/", "entities": [
            {"type": "company", "properties": {"name": "Acme Motors",
                                               "financials": {"revenueAnnual": "$1.2B"}}}]}]}
        got, _ = self._call(return_value=mock.Mock(status_code=200, json=lambda: body))
        self.assertEqual(got["revenue"], 1_200_000_000)

    def test_no_recognisable_match_is_none(self):
        body = {"results": [{"url": "https://zeta.com", "entities": [
            {"type": "company", "properties": {"name": "Zeta Pharma"}}]}]}
        got, _ = self._call(return_value=mock.Mock(status_code=200, json=lambda: body))
        self.assertIsNone(got)

    def test_a_failed_call_is_none(self):
        self.assertIsNone(self._call(side_effect=OSError("down"))[0])
        self.assertIsNone(self._call(return_value=mock.Mock(status_code=429,
                                                            json=lambda: {}))[0])


if __name__ == "__main__":
    unittest.main()
