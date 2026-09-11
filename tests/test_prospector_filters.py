"""
Leads & Outreach — filter enforcement and query planning
────────────────────────────────────────────────────────
The filters are the rule, Exa's answer only a suggestion: a person outside an
excluded place never takes a slot, and an excluded word is never sent. These
tests pin the title classifiers on real Indian corporate titles, the person and
company checks, and the searches `plan` / `top_up` write — including the
owner's own ICP with India excluded, against the real places reader.

Pure: no network, no Qt, nothing under ~/.prism.
"""
from __future__ import annotations

import ast
import datetime
from pathlib import Path

import pytest

from prospector import filters as F
from prospector.filters import SearchSpec
from prospector.models import Lead

TODAY = datetime.date(2026, 9, 11)


def spec(**facets) -> SearchSpec:
    return SearchSpec.from_dict(facets)


def lead(title="Plant Head", company="Acme Motors", location="", since="", **extra) -> Lead:
    person = Lead(name="Asha Rao", title=title, company=company)
    person.extra.update({"location": location, "since": since, **extra})
    return person


# ── seniority ─────────────────────────────────────────────────────────────────

SENIORITY_TABLE = [
    ("Founder & CEO", {"founder", "c_suite"}),
    ("Co-Founder", {"founder"}),
    ("Owner", {"owner"}),
    ("Proprietor", {"owner"}),
    ("Partner", {"partner"}),
    ("Managing Partner", {"partner"}),
    ("Chief Executive Officer", {"c_suite"}),
    ("Chief Operating Officer", {"c_suite"}),
    ("CXO", {"c_suite"}),
    ("CTO", {"c_suite"}),
    ("Managing Director", {"c_suite"}),
    ("Chairman & Managing Director", {"c_suite"}),
    ("Executive Director", {"c_suite"}),
    ("Whole-time Director", {"c_suite"}),
    ("President - Operations", {"c_suite"}),
    ("Vice President Sales", {"vp"}),
    ("Vice-President, Manufacturing", {"vp"}),
    ("Senior Vice President", {"vp"}),
    ("AVP - IT", {"vp"}),
    ("VP & Head", {"vp", "head"}),
    ("Plant Head", {"head"}),
    ("Head of Manufacturing", {"head"}),
    ("Head of Digital Transformation / Industry 4.0 / IIoT", {"head"}),
    ("Automation Head / Smart Manufacturing", {"head"}),
    ("Manufacturing Excellence / Operations / Production Head", {"head"}),
    ("Plant Head / Head of Manufacturing", {"head"}),
    ("Supply Chain / Warehouse / Materials Head", {"head"}),
    ("Business Excellence & Continuous Improvement", set()),
    ("Director of Engineering", {"director"}),
    ("General Manager", {"director"}),
    ("GM - Operations", {"director"}),
    ("Sr. GM", {"director"}),
    ("AGM", {"manager"}),
    ("DGM (Production)", {"manager"}),
    ("Assistant General Manager - Purchase", {"manager"}),
    ("Manager", {"manager"}),
    ("Sr. Manager", {"manager"}),
    ("Chief Manager", {"manager"}),
    ("Deputy Manager", {"manager"}),
    ("Assistant Manager", {"manager"}),
    ("Senior Engineer", {"senior"}),
    ("Lead Engineer", {"senior"}),
    ("Principal Consultant", {"senior"}),
    ("Team Lead", {"senior"}),
    ("Engineer", {"entry"}),
    ("Analyst", {"entry"}),
    ("Executive", {"entry"}),
    ("Associate", {"entry"}),
    ("Intern", {"intern"}),
    ("Management Trainee", {"intern"}),
    ("Apprentice", {"intern"}),
    ("Graduate Engineer Trainee", {"intern"}),
    ("Product Owner", set()),
    ("", set()),
]


@pytest.mark.parametrize("title,expected", SENIORITY_TABLE)
def test_seniority_of(title, expected):
    assert F.seniority_of(title) == frozenset(expected)


def test_seniority_table_is_wide_and_keys_are_real():
    assert len(SENIORITY_TABLE) >= 40
    known = {k for k, _ in F.SENIORITY}
    for _, expected in SENIORITY_TABLE:
        assert expected <= known


def test_vice_president_is_never_c_suite_and_md_is_never_director():
    for title in ("Vice President", "Vice President - Operations", "Executive Vice President"):
        assert "c_suite" not in F.seniority_of(title)
    assert "director" not in F.seniority_of("Managing Director")


# ── function ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("Head - Manufacturing Excellence", {"manufacturing", "operations"}),
    ("Head of Digital Transformation / Industry 4.0 / IIoT", {"automation"}),
    ("Automation Head / Smart Manufacturing", {"automation", "manufacturing"}),
    ("Manufacturing Excellence / Operations / Production Head", {"manufacturing", "operations"}),
    ("Business Excellence & Continuous Improvement", {"operations"}),
    ("Plant Head / Head of Manufacturing", {"manufacturing"}),
    ("Supply Chain / Warehouse / Materials Head", {"supply_chain"}),
    ("Head - IT", {"it"}),
    ("Business Development Manager", {"business_development"}),
    ("Digital Marketing Manager", {"marketing"}),
    ("Key Accounts Manager", {"sales"}),
    ("R&D Head", {"research"}),
    ("Quality Assurance Manager", {"quality"}),
    ("Maintenance Engineer", {"maintenance", "engineering"}),
    ("HR Business Partner", {"hr"}),
    ("Company Secretary & Compliance Officer", {"legal"}),
    ("Chief Financial Officer", {"finance"}),
    ("Purchase Head", {"supply_chain"}),
    ("Projects Head", {"projects"}),
    ("Customer Service Executive", {"customer"}),
    ("Admin Executive", {"admin"}),
    ("", set()),
])
def test_function_of(title, expected):
    assert F.function_of(title) == frozenset(expected)


def test_the_english_word_it_is_not_information_technology():
    assert "it" not in F.function_of("Make it happen")


# ── dates ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("started,band", [
    ("2026-03-01", "lt1"), ("2025-09-11", "1-2"), ("2024-10", "1-2"),
    ("2021-04-01", "3-5"), ("2016-01", "6-10"), ("2015-09-12", "6-10"),
    ("2010-01-01", "gt10"), ("2027-01", ""), ("", ""), ("soon", ""),
    ("2021-13", ""), (None, ""),
])
def test_tenure_band(started, band):
    assert F.tenure_band(started, TODAY) == band


def test_tenure_band_accepts_a_datetime_today():
    assert F.tenure_band("2021-04-01", datetime.datetime(2026, 9, 11, 10, 0)) == "3-5"


# ── the person: place-free facets ─────────────────────────────────────────────

def test_no_filters_passes_everyone():
    assert F.match_person(SearchSpec(), lead(location="")) == ""


def test_job_title_exclude_and_strict_include():
    s = spec(job_titles={"include": ["Plant Head / Head of Manufacturing"],
                         "exclude": ["Intern"]})
    assert F.match_person(s, lead(title="Summer Intern")) == "job_title"
    assert F.match_person(s, lead(title="Quality Engineer")) == ""   # similar titles on
    s.similar_titles = False
    assert F.match_person(s, lead(title="Quality Engineer")) == "job_title"
    assert F.match_person(s, lead(title="Head - Manufacturing")) == ""
    assert F.match_person(s, lead(title="Plant Head, Pune")) == ""
    strict = spec(job_titles={"include": ["VP Operations"]}, similar_titles=False)
    assert F.match_person(strict, lead(title="Vice President - Operations")) == ""


def test_seniority_and_function_facets():
    s = spec(seniority={"include": ["head", "vp"], "exclude": ["c_suite"]})
    assert F.match_person(s, lead(title="Plant Head")) == ""
    assert F.match_person(s, lead(title="Deputy Manager")) == "seniority"
    assert F.match_person(s, lead(title="VP & CEO")) == "seniority"
    f = spec(functions={"include": ["manufacturing"], "exclude": ["sales"]})
    assert F.match_person(f, lead(title="Production Head")) == ""
    assert F.match_person(f, lead(title="Plant Sales Head")) == "function"
    assert F.match_person(f, lead(title="Finance Head")) == "function"


def test_company_include_and_exclude_after_legal_suffixes():
    s = spec(companies={"include": ["Tata Motors"]})
    assert F.match_person(s, lead(company="Tata Motors Limited")) == ""
    assert F.match_person(s, lead(company="Ashok Leyland")) == "company"
    x = spec(companies={"exclude": ["Mahindra & Mahindra Ltd."]})
    assert F.match_person(x, lead(company="Mahindra and Mahindra")) == "company"
    assert F.match_person(x, lead(company="Mahindra Logistics")) == ""


def test_industry_and_keyword_excludes_read_title_and_company():
    s = spec(industries={"include": ["Automobile"], "exclude": ["Pharmaceuticals"]},
             keywords={"exclude": ["Software"]})
    assert F.match_person(s, lead(company="Sun Pharmaceutical Industries")) == "industry"
    assert F.match_person(s, lead(title="Software Head")) == "keyword"
    assert F.match_person(s, lead(company="Maruti Suzuki")) == ""    # includes only guide


def test_years_in_role_reads_the_live_job_then_since():
    props = {"workHistory": [
        {"title": "Plant Head", "dates": {"from": "2019-02-01", "to": None}},
        {"title": "Manager", "dates": {"from": "2010-01", "to": "2019-01"}}]}
    s = spec(years_in_role=["3-5"])            # 7 years in, not the 16 of the whole career
    assert F.match_person(s, lead(), props, today=TODAY) == "years_in_role"
    assert F.match_person(spec(years_in_role=["6-10"]), lead(), props, today=TODAY) == ""
    s = spec(years_in_role=["6-10", "3-5"])
    assert F.match_person(s, lead(since="2020-05"), None, today=TODAY) == ""
    assert F.match_person(s, lead(since=""), None, today=TODAY) == "years_in_role"


def test_changed_jobs_within_90_days_counts_the_whole_month():
    s = spec(changed_jobs_90d=True)
    assert F.match_person(s, lead(since="2026-07-20"), today=TODAY) == ""
    assert F.match_person(s, lead(since="2026-06"), today=TODAY) == ""      # to 30 Jun: 73 days
    assert F.match_person(s, lead(since="2026-05"), today=TODAY) == "changed_jobs"
    assert F.match_person(s, lead(since="2026-05-01"), today=TODAY) == "changed_jobs"
    assert F.match_person(s, lead(since=""), today=TODAY) == "changed_jobs"


# ── the company ───────────────────────────────────────────────────────────────

def test_needs_company_facts():
    assert not F.needs_company_facts(SearchSpec())
    assert not F.needs_company_facts(spec(industries={"include": ["Tyre"]}))
    assert not F.needs_company_facts(spec(revenue=["nonsense"]))
    assert F.needs_company_facts(spec(headcount=["51-200"]))
    assert F.needs_company_facts(spec(revenue=["10m-50m"]))
    assert F.needs_company_facts(spec(company_hq={"exclude": ["India"]}))
    assert F.needs_company_facts(spec(industries={"exclude": ["Pharma"]}))
    assert F.needs_company_facts(spec(keywords={"exclude": ["SaaS"]}))


def test_match_company_headcount_and_description():
    s = spec(headcount=["51-200", "10001+"], industries={"exclude": ["Pharmaceuticals"]})
    assert F.match_company(s, lead(), None) == ""
    assert F.match_company(s, lead(), {"headcount": 120, "hq": "", "description": ""}) == ""
    assert F.match_company(s, lead(), {"headcount": 40000}) == ""
    assert F.match_company(s, lead(), {"headcount": 700}) == "headcount"
    assert F.match_company(s, lead(), {"headcount": None}) == ""
    assert F.match_company(s, lead(), {"headcount": 150,
                                       "description": "A pharmaceutical maker"}) == "industry"


# ── annual revenue ────────────────────────────────────────────────────────────

def test_revenue_bands_are_sales_navs_and_cover_every_dollar_once():
    assert [k for k, _ in F.REVENUE] == ["lt1m", "1m-10m", "10m-50m", "50m-100m",
                                         "100m-500m", "500m-1b", "gt1b"]
    assert F.label_of(F.REVENUE, "gt1b") == "$1B+"
    assert set(F.REVENUE_RANGES) == {k for k, _ in F.REVENUE}
    assert "revenue" in F.BAND_FACETS
    assert F.FACET_LABELS["revenue"] == "Annual revenue"
    assert F.REASONS["revenue"] == "annual revenue"
    ranges = [F.REVENUE_RANGES[k] for k, _ in F.REVENUE]
    for (_, hi), (lo, _) in zip(ranges, ranges[1:]):
        assert hi == lo                     # no gap, no overlap
    assert ranges[0][0] == 0 and ranges[-1][1] is None


def test_revenue_bands_to_and_from_dict():
    s = spec(revenue=["gt1b", "$1M-10M", "HUGE", "10M-50M", "gt1b"])
    # By key or label, any case; unknown keys dropped; canonical order, no repeats.
    assert s.revenue == ["1m-10m", "10m-50m", "gt1b"]
    assert s.to_dict()["revenue"] == ["1m-10m", "10m-50m", "gt1b"]
    assert SearchSpec.from_dict(s.to_dict()).to_dict() == s.to_dict()
    assert s.copy().revenue == s.revenue
    for odd in ("nonsense", 42, None, {"include": ["gt1b"]}):
        assert spec(revenue=odd).revenue == []
    # A file saved before the facet existed loads with no revenue filter.
    legacy = {"v": 1, "job_titles": {"include": ["Plant Head"]}, "headcount": ["51-200"]}
    old = SearchSpec.from_dict(legacy)
    assert old.revenue == [] and old.to_dict()["revenue"] == []
    assert SearchSpec().to_dict()["revenue"] == []


def test_revenue_counts_in_the_badge_and_the_summary():
    s = spec(job_titles={"include": ["Plant Head"]}, revenue=["50m-100m", "100m-500m"])
    assert s.count("revenue") == 2
    assert s.active_count() == 3
    assert s.summary() == "1 title · Anywhere · +2 more"


@pytest.mark.parametrize("usd,reason", [
    (12_500_000, ""),                   # inside 10m-50m
    (10_000_000, ""),                   # a lower bound is in
    (50_000_000, "revenue"),            # an upper bound is out ...
    (2_000_000_000, ""),                # ... gt1b has none
    (999_999_999, "revenue"),
    (400_000, "revenue"),
    (None, ""),                         # not on record: unverified, not wrong
    (0, ""),
    (-5, ""),
    ("n/a", ""),
    (True, ""),
])
def test_match_company_revenue(usd, reason):
    s = spec(revenue=["10m-50m", "gt1b"])
    assert F.match_company(s, lead(), {"headcount": 300, "revenue": usd, "hq": "",
                                       "description": ""}) == reason


def test_revenue_unknown_passes_and_headcount_still_rules():
    s = spec(revenue=["lt1m"], headcount=["1-10"])
    assert F.match_company(s, lead(), None) == ""
    assert F.match_company(s, lead(), {}) == ""
    assert F.match_company(s, lead(), {"headcount": 5}) == ""
    assert F.match_company(s, lead(), {"headcount": 900, "revenue": 500_000}) == "headcount"
    assert F.match_company(s, lead(), {"headcount": None, "revenue": 5_000_000}) == "revenue"
    assert F.match_company(spec(headcount=["1-10"]), lead(), {"revenue": 9e12}) == ""


def test_revenue_bands_leave_the_queries_alone():
    base = spec(job_titles={"include": ["Plant Head"]}, industries={"include": ["Tyre"]})
    with_revenue = spec(job_titles={"include": ["Plant Head"]},
                        industries={"include": ["Tyre"]}, revenue=["gt1b"])
    assert F.plan(with_revenue) == F.plan(base)
    assert F.top_up(with_revenue, 1) == F.top_up(base, 1)


# ── planning ──────────────────────────────────────────────────────────────────

def test_plan_is_role_outer_and_breadth_first():
    s = spec(job_titles={"include": ["Plant Head", "CTO"]},
             industries={"include": ["Automobile", "Tyre", "Mining"]})
    got = F.plan(s)
    assert [ind for ind, _ in got] == ["Automobile", "Tyre", "Mining"] * 2
    assert got[0] == ("Automobile", "Plant Head at Automobile companies")
    assert got[3][1].startswith("CTO at Automobile")


def test_plan_phrasing_size_keywords_and_any_industry():
    s = spec(job_titles={"include": ["Plant Head"]},
             headcount=["1-10", "51-200"], keywords={"include": ["Industry 4.0", "SAP"]})
    assert F.plan(s) == [("", "Plant Head at small and mid-size companies "
                              "with Industry 4.0 and SAP experience")]
    assert F.plan(spec(job_titles={"include": ["Plant Head"]},
                       headcount=["1-10", "501-1000", "10001+"])) == [("", "Plant Head")]
    assert F.plan(SearchSpec()) == []


def test_plan_rotates_included_locations_and_hq():
    s = spec(job_titles={"include": ["Plant Head", "COO"]},
             industries={"include": ["Automobile", "Tyre"]},
             locations={"include": ["Germany", "France"]})
    qs = [q for _, q in F.plan(s)]
    # every pairing once (rotated), then every pairing in the other place
    assert qs == ["Plant Head at Automobile companies in Germany",
                  "Plant Head at Tyre companies in France",
                  "COO at Automobile companies in France",
                  "COO at Tyre companies in Germany",
                  "Plant Head at Automobile companies in France",
                  "Plant Head at Tyre companies in Germany",
                  "COO at Automobile companies in Germany",
                  "COO at Tyre companies in France"]
    hq = spec(job_titles={"include": ["Plant Head"]}, company_hq={"include": ["Japan"]})
    assert F.plan(hq) == [("", "Plant Head at a company headquartered in Japan")]


def test_plan_never_sends_an_excluded_word():
    s = spec(job_titles={"include": ["Plant Head", "Software Head", "Sales Head",
                                     "Trainee Head"]},
             industries={"include": ["Automobile", "IT Services"]},
             keywords={"exclude": ["software", "IT"]}, seniority={"exclude": ["intern"]},
             functions={"exclude": ["sales"]})
    queries = [q for _, q in F.plan(s)]
    assert queries == ["Plant Head at Automobile companies"]


def test_top_up_rounds_are_new_words_and_end():
    s = spec(job_titles={"include": ["Plant Head"]},
             industries={"include": ["Automobile", "Tyre"]},
             locations={"include": ["Germany", "France", "Japan"]})
    first = {q for _, q in F.plan(s)}
    seen = set(first)
    for n in range(1, 5):
        rnd = F.top_up(s, n)
        assert rnd, n
        for _, q in rnd:
            assert q not in seen
            seen.add(q)
    assert F.top_up(s, 5) == [] and F.top_up(s, 0) == []
    # the rotation moves on: round 1 sends Automobile somewhere plan did not
    assert "in Germany" in F.plan(s)[0][1] and "in Germany" not in F.top_up(s, 1)[0][1]
    assert F.top_up(s, 2)[0][1].startswith("Plant Director")


# ── places: the real reader ───────────────────────────────────────────────────

def test_place_case_keeps_joining_words_low():
    assert F.parse_location_text("global except trinidad and tobago") == \
        ([], ["Trinidad and Tobago"])
    assert F.parse_location_text("Global except india") == ([], ["India"])


EXCEPT_INDIA = [
    ("Pune, Maharashtra, India", "location"),
    ("Bengaluru", "location"),
    ("Greater Mumbai Area", "location"),
    ("Gurgaon, Haryana", "location"),
    ("Delhi NCR", "location"),
    ("Indianapolis, Indiana, United States", ""),
    ("Hyderabad, Sindh, Pakistan", ""),
    ("Dubai, United Arab Emirates", ""),
    ("Colombo, Sri Lanka", ""),
    ("", "location_unknown"),
]


@pytest.mark.parametrize("where,reason", EXCEPT_INDIA)
def test_location_except_india(where, reason):
    s = spec(locations={"exclude": ["India"]})
    assert F.match_person(s, lead(location=where)) == reason


def test_location_include_and_live_job_fallback():
    s = spec(locations={"include": ["Europe"], "exclude": ["Germany"]})
    assert F.match_person(s, lead(location="Paris, France")) == ""
    assert F.match_person(s, lead(location="Munich, Bavaria, Germany")) == "location"
    assert F.match_person(s, lead(location="Toronto, Canada")) == "location"
    props = {"workHistory": [{"title": "Plant Head", "location": "Lyon, France",
                              "dates": {"from": "2022-01"}}]}
    assert F.match_person(s, lead(location=""), props) == ""
    assert F.match_person(s, lead(location=""), {}) == "location_unknown"


def test_match_company_hq():
    s = spec(company_hq={"exclude": ["India"]})
    assert F.match_company(s, lead(), {"headcount": 500, "hq": "Mumbai, Maharashtra, India"}) \
        == "company_hq"
    assert F.match_company(s, lead(), {"headcount": 500, "hq": "Stuttgart, Germany"}) == ""
    # An HQ nobody found can't be proven outside India: an exclusion is a rule,
    # so unknown fails (it used to pass — and the lookup cap then switched the
    # filter off for every company past it).
    assert F.match_company(s, lead(), {"headcount": 500, "hq": ""}) == "company_hq_unknown"
    assert F.match_company(s, lead(), {"headcount": 500, "hq": "Remote"}) == "company_hq_unknown"
    assert F.match_company(s, lead(), None) == "company_hq_unknown"
    assert "company_hq_unknown" in F.REASONS
    inc = spec(company_hq={"include": ["Japan"]})
    assert F.match_company(inc, lead(), {"hq": "Toyota City, Aichi, Japan"}) == ""
    assert F.match_company(inc, lead(), {"hq": "Detroit, Michigan, United States"}) == "company_hq"


LOCATION_SENTENCES = [
    ("Global except india", [], ["India"]),
    ("Anywhere but India", [], ["India"]),
    ("Anywhere but not India", [], ["India"]),
    ("Global (except India)", [], ["India"]),
    ("International (not India)", [], ["India"]),
    ("Global ex-India", [], ["India"]),
    ("Non-India", [], ["India"]),
    ("−India", [], ["India"]),
    ("Europe, UAE but not Germany", ["Europe", "UAE"], ["Germany"]),
    ("Worldwide", [], []),
    ("All countries except India", [], ["India"]),
    ("Pan India", ["India"], []),
    ("Across the world except Pan-India", [], ["India"]),
    ("Allahabad", ["Allahabad"], []),
    ("Nonthaburi", ["Nonthaburi"], []),         # "non" only as its own word
    ("Essex", ["Essex"], []),                   # "ex" likewise
]


@pytest.mark.parametrize("text,include,exclude", LOCATION_SENTENCES)
def test_parse_location_text_reads_the_ways_people_write_except(text, include, exclude):
    assert F.parse_location_text(text) == (include, exclude)


@pytest.mark.parametrize("text", ["Global except India", "Anywhere but India",
                                  "Global (except India)", "Non-India"])
def test_a_saved_sentence_reloads_as_filters_and_never_asks_for_india(text):
    # An old session's one-line location, or a chip typed before the panel
    # read places: an include that is a sentence becomes the chips it meant.
    for raw in ({"location": text, "roles": ["Plant Head"], "industries": ["Automobile"]},
                {"filters": {"job_titles": {"include": ["Plant Head"]},
                             "industries": {"include": ["Automobile"]},
                             "locations": {"include": [text]}}}):
        s = SearchSpec.from_params(raw)
        assert s.locations.to_dict() == {"include": [], "exclude": ["India"]}, raw
        queries = [q for _, q in F.plan(s)]
        assert queries and not [q for q in queries if "india" in q.casefold()]
        assert F.match_person(s, lead(location="Dubai, United Arab Emirates")) == ""
        assert F.match_person(s, lead(location="Pune, Maharashtra, India")) == "location"
    anywhere = SearchSpec.from_dict({"locations": {"include": ["Anywhere", "UAE"],
                                                   "exclude": ["Worldwide"]}})
    assert anywhere.locations.to_dict() == {"include": ["UAE"], "exclude": []}


def test_read_place_text_gives_gazetteer_labels_and_what_it_cannot_place():
    assert F.read_place_text("Global except india") == ([], ["India"], [])
    assert F.read_place_text("bombay") == (["Mumbai"], [], [])
    assert F.read_place_text("Hyderabad, Pakistan") == (["Hyderabad, Pakistan"], [], [])
    assert F.read_place_text("Delhi, Mumbai") == (["Delhi", "Mumbai"], [], [])
    assert F.read_place_text("-india") == ([], ["India"], [])
    assert F.read_place_text("Anywhere") == ([], [], [])
    assert F.read_place_text("ger")[2]                      # half-typed: not a place
    assert F.read_place_text("Global except Xqzzy") == ([], [], ["Xqzzy"])


def _workbench_defaults() -> tuple:
    """The owner's default ICP, read from the workbench source (not imported:
    this test stays Qt-free)."""
    path = Path(__file__).resolve().parents[1] / "addons" / "leads" / "workbench.py"
    found = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("_DEFAULT_ROLES", "_DEFAULT_INDUSTRIES"):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return found["_DEFAULT_ROLES"], found["_DEFAULT_INDUSTRIES"]


def _india_words() -> list:
    from prospector import places
    words = [a for a in places.aliases_of("India") if len(a) >= 3]
    assert "india" in words and len(words) > 20
    return words


def test_default_icp_except_india_never_names_india():
    roles, industries = _workbench_defaults()
    s = SearchSpec.from_legacy({"roles": roles, "industries": industries,
                                "location": "Global except india"})
    assert len(s.job_titles.include) == 6 and len(s.industries.include) == 10
    assert s.locations.exclude == ["India"]
    rounds = [F.plan(s)] + [F.top_up(s, n) for n in range(1, 5)]
    assert len(rounds[0]) == 60
    banned = [F._tokens(w) for w in _india_words()]
    for rnd in rounds:
        assert rnd
        for _, query in rnd:
            words = F._tokens(query)
            hit = [b for b in banned if F._contains(words, b)]
            assert not hit, (query, hit)
            assert " in " in query or "headquartered" in query        # a region is named
    regions = {q.rsplit(" in ", 1)[-1] for _, q in rounds[0]}
    assert len(regions) >= 3


def test_one_pairing_except_india_is_asked_across_the_world():
    s = spec(job_titles={"include": ["Plant Head"]}, industries={"include": ["Automobile"]},
             locations={"exclude": ["India"]})
    first = F.plan(s)
    places_first = {q.rsplit(" in ", 1)[-1] for _, q in first}
    assert len(first) == 12 and len(places_first) == 12
    assert first[0] == ("Automobile", "Plant Head at Automobile companies in the United States")
    later = F.top_up(s, 1)
    assert len(later) == 12
    assert not places_first & {q.rsplit(" in ", 1)[-1] for _, q in later}
    banned = [F._tokens(w) for w in _india_words()]
    for _, query in first + later:
        assert not any(F._contains(F._tokens(query), b) for b in banned), query


def test_an_include_less_its_exclusion_names_what_is_left():
    s = spec(job_titles={"include": ["Plant Head"]},
             locations={"include": ["Europe"], "exclude": ["Germany"]})
    queries = [q for _, q in F.plan(s)]
    assert queries and not any("Germany" in q or q.endswith("in Europe") for q in queries)
    # nothing left to name: no place at all rather than the excluded one
    gone = spec(job_titles={"include": ["Plant Head"]},
                locations={"include": ["Gujarat"], "exclude": ["India"]})
    assert F.plan(gone) == [("", "Plant Head")]


def test_plan_drops_a_query_that_names_an_excluded_place():
    s = spec(job_titles={"include": ["Plant Head"]},
             industries={"include": ["Automobile", "Mumbai Port Trust"]},
             locations={"include": ["Europe"]}, company_hq={"exclude": ["India"]})
    assert [q for _, q in F.plan(s)] == ["Plant Head at Automobile companies in Europe"]
