"""
Prism Sales Automation — filters: who a search is for, Apollo / Sales Nav style
───────────────────────────────────────────────────────────────────────────────
A list is built from FILTERS, the way Apollo and Sales Navigator build one. Each
facet holds values to INCLUDE and values to EXCLUDE — "Location: anywhere,
except India" — and a few facets are multi-select bands (company headcount,
annual revenue, years in the current role).

Exa's people search is one natural-language query. It has no exclusion and no
structured fields, so a filter does two jobs here:

  · it PLANS the searches (`plan`): includes shape the query text, an excluded
    word is never sent, and a location exclusion becomes searches across the
    regions that are left — asking for "except India" in words pulls India in;
  · it CHECKS every person who comes back (`match_person`, `match_company`)
    before they take a slot. Exa's answer is a suggestion; the filter is the
    rule.

Two includes can only steer the search, because a person row carries no
industry and no keywords: Industry and Keywords. Their EXCLUDES are enforced
(on the title, the company name and — when it was looked up — the company's
own description). Every other facet is enforced both ways.

Stdlib-only and Qt-free. The panel, the session store, saved searches and the
worker all pass the plain dict from `SearchSpec.to_dict()`, and every reader
goes through `SearchSpec.from_dict()`, which forgives anything a hand-edited
or older file holds.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

SCHEMA = 1

# Facets that hold typed / picked values with an include and an exclude side,
# in the order the panel shows them.
CHIP_FACETS = ("locations", "job_titles", "seniority", "functions",
               "industries", "companies", "company_hq", "keywords")
# Multi-select bands: include-only, stored as option keys in canonical order.
BAND_FACETS = ("headcount", "revenue", "years_in_role")

FACET_LABELS = {
    "locations": "Location", "job_titles": "Job title", "seniority": "Seniority",
    "functions": "Function", "industries": "Industry",
    "companies": "Current company", "company_hq": "Company HQ location",
    "keywords": "Keywords", "headcount": "Company headcount",
    "revenue": "Annual revenue", "years_in_role": "Years in current role",
}

# Management levels, Apollo's set. (key, label). A title can hold more than one
# ("Founder & CEO" is founder AND c_suite) — see seniority_of.
SENIORITY = (
    ("owner", "Owner"), ("founder", "Founder"), ("c_suite", "C-suite"),
    ("partner", "Partner"), ("vp", "Vice President"), ("head", "Head"),
    ("director", "Director"), ("manager", "Manager"), ("senior", "Senior"),
    ("entry", "Entry level"), ("intern", "Intern / Trainee"),
)

# Departments / job functions, read off the title. (key, label).
FUNCTIONS = (
    ("operations", "Operations"),
    ("manufacturing", "Manufacturing & Production"),
    ("engineering", "Engineering"),
    ("automation", "Automation & Digital"),
    ("it", "Information Technology"),
    ("supply_chain", "Supply Chain & Purchasing"),
    ("quality", "Quality"),
    ("maintenance", "Maintenance & Facilities"),
    ("projects", "Projects"),
    ("research", "Research & Development"),
    ("sales", "Sales"),
    ("business_development", "Business Development"),
    ("marketing", "Marketing"),
    ("product", "Product"),
    ("finance", "Finance & Accounts"),
    ("hr", "Human Resources"),
    ("legal", "Legal & Compliance"),
    ("customer", "Customer Success & Service"),
    ("strategy", "Strategy & General Management"),
    ("admin", "Administration"),
)

# Sales Navigator's headcount bands. (key, label); ranges are inclusive.
HEADCOUNT = (
    ("1-10", "1-10"), ("11-50", "11-50"), ("51-200", "51-200"),
    ("201-500", "201-500"), ("501-1000", "501-1,000"),
    ("1001-5000", "1,001-5,000"), ("5001-10000", "5,001-10,000"),
    ("10001+", "10,001+"),
)
HEADCOUNT_RANGES = {
    "1-10": (1, 10), "11-50": (11, 50), "51-200": (51, 200),
    "201-500": (201, 500), "501-1000": (501, 1000), "1001-5000": (1001, 5000),
    "5001-10000": (5001, 10000), "10001+": (10001, None),
}

# Sales Navigator's "Annual revenue", in US dollars. (key, label); a range's
# lower bound is inclusive and its upper bound exclusive, so exactly $10M is
# "10m-50m", never both.
REVENUE = (
    ("lt1m", "Under $1M"), ("1m-10m", "$1M-10M"), ("10m-50m", "$10M-50M"),
    ("50m-100m", "$50M-100M"), ("100m-500m", "$100M-500M"),
    ("500m-1b", "$500M-1B"), ("gt1b", "$1B+"),
)
REVENUE_RANGES = {
    "lt1m": (0, 1_000_000), "1m-10m": (1_000_000, 10_000_000),
    "10m-50m": (10_000_000, 50_000_000), "50m-100m": (50_000_000, 100_000_000),
    "100m-500m": (100_000_000, 500_000_000),
    "500m-1b": (500_000_000, 1_000_000_000), "gt1b": (1_000_000_000, None),
}

# Sales Navigator's "Years in current position". Whole years in the role:
# 0 → lt1, 1-2 → 1-2, 3-5 → 3-5, 6-10 → 6-10, 11 and up → gt10.
YEARS_IN_ROLE = (
    ("lt1", "Less than 1 year"), ("1-2", "1 to 2 years"),
    ("3-5", "3 to 5 years"), ("6-10", "6 to 10 years"),
    ("gt10", "More than 10 years"),
)

# Facets whose values must be one of a fixed option list (stored as keys).
CLOSED_FACETS = {"seniority": SENIORITY, "functions": FUNCTIONS}

# Facets whose INCLUDE side can only guide the search — shown as such.
GUIDES_ONLY = frozenset({"industries", "keywords"})

# Why a person was left out, as `match_person` / `match_company` name it, and
# how the run summary says it.
REASONS = {
    "location": "location",
    "location_unknown": "no location on the profile",
    "job_title": "job title",
    "seniority": "seniority",
    "function": "function",
    "company": "company",
    "industry": "industry",
    "keyword": "keyword",
    "years_in_role": "years in role",
    "changed_jobs": "no recent job change",
    "headcount": "company headcount",
    "revenue": "annual revenue",
    "company_hq": "company HQ",
    "company_hq_unknown": "company HQ unknown",
}

# Typeahead starters the panel offers before the richer lookups are wired in.
INDUSTRY_SUGGESTIONS = (
    "Automobile", "Auto Components", "Tyre", "Steel Manufacturing", "Die Casting",
    "Aerospace & MRO", "Defense", "Electrical & Electronics",
    "Warehousing & Logistics", "Mining", "Pharmaceuticals", "Chemicals", "FMCG",
    "Food Processing", "Textiles", "Cement", "Oil & Gas", "Power & Utilities",
    "Renewable Energy", "Construction", "Real Estate", "Packaging",
    "Plastics & Polymers", "Glass", "Paper & Pulp", "Machinery & Equipment",
    "Semiconductors", "Medical Devices", "Consumer Electronics", "Retail",
    "E-commerce", "SaaS", "IT Services", "Telecom", "Banking", "Insurance",
    "Healthcare", "Education", "Hospitality", "Shipping & Ports", "Railways",
    "Agriculture",
)
TITLE_SUGGESTIONS = (
    "Head of Digital Transformation", "Industry 4.0 Head", "IIoT Head",
    "Automation Head", "Smart Manufacturing Head",
    "Head of Manufacturing Excellence", "Operations Head", "Production Head",
    "Plant Head", "Head of Manufacturing", "Business Excellence Head",
    "Continuous Improvement Head", "Supply Chain Head", "Warehouse Head",
    "Materials Head", "Chief Executive Officer", "Chief Operating Officer",
    "Chief Technology Officer", "Chief Information Officer", "Managing Director",
    "General Manager", "Vice President Operations", "Director of Engineering",
    "Maintenance Head", "Quality Head", "Purchase Head", "Projects Head", "Founder",
)
LOCATION_SUGGESTIONS = (
    "North America", "Europe", "Middle East", "Asia Pacific", "Southeast Asia",
    "South Asia", "Africa", "Latin America", "Oceania",
    "United States", "Canada", "United Kingdom", "Germany", "France", "Italy",
    "Spain", "Netherlands", "Switzerland", "Sweden", "Poland", "Turkey",
    "United Arab Emirates", "Saudi Arabia", "Qatar", "Israel", "India",
    "Singapore", "Malaysia", "Indonesia", "Thailand", "Vietnam", "Philippines",
    "China", "Japan", "South Korea", "Australia", "New Zealand", "South Africa",
    "Nigeria", "Kenya", "Egypt", "Brazil", "Mexico", "Argentina", "Chile",
    "Bangladesh", "Sri Lanka", "Pakistan", "Nepal",
)

_MAX_VALUES = 50          # per side of a facet
_MAX_LEN = 120            # per value
_SPLIT = re.compile(r"[\n,;]")


# ── cleaning what a panel, a file or an old session hands over ────────────────

def _values(raw) -> list:
    """Free-text values: a list of strings (or one newline/comma-separated
    string, the old ICP textarea form), trimmed, inner spaces collapsed,
    de-duplicated case-insensitively (first spelling wins), capped."""
    if isinstance(raw, str):
        items = _SPLIT.split(raw)
    elif isinstance(raw, (list, tuple)):
        items = [x for x in raw if isinstance(x, str)]
    else:
        return []
    out, seen = [], set()
    for item in items:
        value = " ".join(item.split())[:_MAX_LEN].strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
            if len(out) >= _MAX_VALUES:
                break
    return out


def _keys(raw, options) -> list:
    """Option keys from values that name an option by key or by label (any
    case); anything else is dropped. Input order, no repeats."""
    by = {}
    for key, label in options:
        by[key.casefold()] = key
        by[label.casefold()] = key
    out = []
    for value in _values(raw):
        key = by.get(value.casefold())
        if key and key not in out:
            out.append(key)
    return out


def _bands(raw, options) -> list:
    """Band keys in the options' own order, so two equal specs are equal."""
    chosen = set(_keys(raw, options))
    return [key for key, _ in options if key in chosen]


def _bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def label_of(options, key: str) -> str:
    """The label for an option key ("c_suite" → "C-suite"); the key if unknown."""
    for k, label in options:
        if k == key:
            return label
    return key


# ── "Global except India": the old one-line location, read as filters ────────

_ANYWHERE = frozenset({
    "global", "globally", "worldwide", "world", "the world", "whole world",
    "anywhere", "everywhere", "all", "all locations", "all countries",
    "any", "any location", "any country", "international", "internationally",
    "rest of the world", "row", "all over the world", "all regions",
})
# "but", "ex-" and "non-" too: "Anywhere but India", "Global ex-India" and
# "Non-India" are how people write it, and missing one used to paste the whole
# sentence into the query — India included.
_EXCEPT = re.compile(
    r"\b(?:except(?:\s+for)?|excluding|exclude|but\s+not|other\s+than|"
    r"outside(?:\s+of)?|not\s+in|minus|without|apart\s+from|besides|not|but|"
    r"ex-?|non-?)\b",
    re.IGNORECASE)
# Brackets and quotes around a place are punctuation, not part of its name:
# "Global (except India)" is Global and India, never "Global (" and "India)".
_PLACE_PUNCT = " .-()[]{}\"'“”‘’"
_ALL_OF = re.compile(r"^(?:pan|all\s+over|all|across|entire|whole(?:\s+of)?)[\s-]+",
                     re.IGNORECASE)
_MINUS_SIGNS = ("-", "−")
_LIST_SEP = re.compile(r"\s*(?:,|;|/|\||&|\+|\band\b|\bor\b)\s*", re.IGNORECASE)
# Places whose own name holds a separator word — kept whole.
_COMPOUND = ("trinidad and tobago", "bosnia and herzegovina", "antigua and barbuda",
             "saint kitts and nevis", "st kitts and nevis", "sao tome and principe",
             "saint vincent and the grenadines", "turks and caicos islands",
             "jammu and kashmir", "dadra and nagar haveli", "daman and diu",
             "andaman and nicobar islands")


# Joining words a place name keeps lower-case: "Trinidad and Tobago", not
# "Trinidad And Tobago" — str.title() capitalises every word.
_PLACE_SMALL = frozenset({"and", "of", "the", "da", "de", "del", "la", "le"})


def _place_case(value: str) -> str:
    """"india" → "India", "uae" → "UAE", "trinidad and tobago" → "Trinidad
    and Tobago"; anything typed with capitals stays."""
    if not value.islower():
        return value
    if len(value) <= 3:
        return value.upper()
    words = value.split()
    return " ".join(w if i and w in _PLACE_SMALL else w.title()
                    for i, w in enumerate(words))


def _place_list(text: str) -> list:
    text = text.strip(_PLACE_PUNCT)
    if not text:
        return []
    shielded = text
    for i, name in enumerate(_COMPOUND):
        shielded = re.sub(rf"\b{re.escape(name)}\b", f"\x00{i}\x00", shielded,
                          flags=re.IGNORECASE)
    out = []
    for part in _LIST_SEP.split(shielded):
        part = re.sub(r"\x00(\d+)\x00", lambda m: _COMPOUND[int(m.group(1))], part)
        part = " ".join(part.split()).strip(_PLACE_PUNCT)
        if part.casefold() in _ANYWHERE:
            continue
        # "Pan India", "All India", "across Europe": the place, all of it.
        part = _ALL_OF.sub("", part).strip(_PLACE_PUNCT)
        if part and part.casefold() not in _ANYWHERE:
            out.append(_place_case(part))
    return _values(out)


def parse_location_text(text) -> tuple:
    """(include, exclude) from one line of location text, as the old ICP box
    took it: "India" → (["India"], []); "Global except india" → ([], ["India"]);
    "Europe, UAE but not Germany" → (["Europe", "UAE"], ["Germany"]);
    "not India" / "-India" / "Non-India" / "Global ex-India" / "Anywhere but
    India" / "Global (except India)" → ([], ["India"]). Words meaning anywhere
    ("global", "worldwide", …) add no include."""
    if not isinstance(text, str) or not text.strip():
        return [], []
    raw = " ".join(text.split())
    if raw.startswith(_MINUS_SIGNS):
        return [], _place_list(raw[1:])
    m = _EXCEPT.search(raw)
    if m is None:
        return _place_list(raw), []
    include = _place_list(raw[:m.start()])
    exclude = _place_list(raw[m.end():])
    gone = {v.casefold() for v in exclude}
    return [v for v in include if v.casefold() not in gone], exclude


def _is_sentence(value: str) -> bool:
    """A place value that is really a sentence — "Global except India",
    "-India", "Anywhere" — rather than the name of somewhere."""
    return (value.casefold() in _ANYWHERE or value.startswith(_MINUS_SIGNS)
            or _EXCEPT.search(value) is not None)


_KIND_RANK = {"region": 0, "country": 1, "state": 2, "city": 3}


def read_place_text(text) -> tuple:
    """(include, exclude, unknown) for text typed into a place facet, in the
    gazetteer's own labels: "Global except india" → ([], ["India"], []);
    "bombay" → (["Mumbai"], [], []); "Hyderabad, Pakistan" → one place;
    "India, UAE" → two; "Anywhere" → nothing at all. `unknown` holds the parts
    prospector.places can't place ("ger", "Global except Indai" → ["Indai"]) —
    the panel refuses those rather than make a chip that would be pasted into
    the Exa query and match nobody's location."""
    from . import places
    # A leading minus is meaning ("-India" is out), not punctuation.
    raw = " ".join(str(text or "").split()).strip(_PLACE_PUNCT.replace("-", ""))
    if not raw or raw.casefold() in _ANYWHERE:
        return [], [], []
    if not _is_sentence(raw):
        whole = places.resolve(raw)
        if whole is not None:
            # "Hyderabad, Pakistan" is one place narrowed by where it is;
            # "Delhi, Mumbai" is two cities, not Delhi narrowed by Mumbai.
            rest = _place_list(raw)[1:] if "," in raw else []
            wider = [places.resolve(p) for p in rest]
            if all(p is not None and _KIND_RANK.get(p.kind, 9) < _KIND_RANK.get(whole.kind, 9)
                   for p in wider):
                return [whole.label], [], []
    include, exclude = parse_location_text(raw)
    unknown: list = []

    def labels(values) -> list:
        out = []
        for value in values:
            place = places.resolve(value)
            if place is None:
                unknown.append(value)
            elif place.label.casefold() not in {v.casefold() for v in out}:
                out.append(place.label)
        return out
    inc, exc = labels(include), labels(exclude)
    gone = {v.casefold() for v in exc}
    return [v for v in inc if v.casefold() not in gone], exc, unknown


def _reread_places(facet: "Facet") -> "Facet":
    """A place facet as filters, not sentences. A value typed or saved before
    the panel read it — include "Global except India" — becomes the chips it
    meant (exclude India); "Anywhere" on either side is no filter. Left alone,
    such a value was sent to Exa word for word (India in the query) and matched
    no one's location, so the run kept nobody."""
    if not any(_is_sentence(v) for v in facet.include + facet.exclude):
        return facet
    from . import places
    include, exclude = [], list(facet.exclude)
    for value in facet.include:
        if _is_sentence(value) and places.resolve(value) is None:
            inc, exc = parse_location_text(value)
            include += inc
            exclude += exc
        else:
            include.append(value)
    exclude = [v for v in exclude if v.casefold() not in _ANYWHERE]
    return Facet.from_dict({"include": include, "exclude": exclude})


# ── the model ─────────────────────────────────────────────────────────────────

@dataclass
class Facet:
    """One filter: values to include and values to exclude. A value on both
    sides is an exclusion — excluding is the stronger statement."""
    include: list = field(default_factory=list)
    exclude: list = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.include or self.exclude)

    def count(self) -> int:
        return len(self.include) + len(self.exclude)

    def to_dict(self) -> dict:
        return {"include": list(self.include), "exclude": list(self.exclude)}

    @classmethod
    def from_dict(cls, raw, options=None) -> "Facet":
        raw = raw if isinstance(raw, dict) else {}
        pick = (lambda v: _keys(v, options)) if options else _values
        exclude = pick(raw.get("exclude"))
        gone = {v.casefold() for v in exclude}
        include = [v for v in pick(raw.get("include")) if v.casefold() not in gone]
        return cls(include=include, exclude=exclude)


# Seniority / function words used when a search has no job titles to send.
_SENIORITY_WORD = {
    "owner": "Owner", "founder": "Founder", "c_suite": "Chief", "partner": "Partner",
    "vp": "VP", "head": "Head", "director": "Director", "manager": "Manager",
    "senior": "Senior", "entry": "", "intern": "Intern",
}


def _function_word(key: str) -> str:
    return label_of(FUNCTIONS, key).split(" & ")[0]


@dataclass
class SearchSpec:
    """Everything a list-building search asks, as filters."""
    locations: Facet = field(default_factory=Facet)
    job_titles: Facet = field(default_factory=Facet)
    seniority: Facet = field(default_factory=Facet)
    functions: Facet = field(default_factory=Facet)
    industries: Facet = field(default_factory=Facet)
    companies: Facet = field(default_factory=Facet)
    company_hq: Facet = field(default_factory=Facet)
    keywords: Facet = field(default_factory=Facet)
    headcount: list = field(default_factory=list)
    revenue: list = field(default_factory=list)
    years_in_role: list = field(default_factory=list)
    # Apollo's "Include people with similar titles": on, a job-title include
    # only steers the search; off, the person's title must carry one of them.
    similar_titles: bool = True
    changed_jobs_90d: bool = False

    # -- the dict every other module passes ---------------------------------
    def to_dict(self) -> dict:
        out: dict = {"v": SCHEMA}
        for name in CHIP_FACETS:
            out[name] = getattr(self, name).to_dict()
        out["headcount"] = list(self.headcount)
        out["revenue"] = list(self.revenue)
        out["years_in_role"] = list(self.years_in_role)
        out["similar_titles"] = bool(self.similar_titles)
        out["changed_jobs_90d"] = bool(self.changed_jobs_90d)
        return out

    @classmethod
    def from_dict(cls, raw) -> "SearchSpec":
        raw = raw if isinstance(raw, dict) else {}
        facets = {name: Facet.from_dict(raw.get(name), CLOSED_FACETS.get(name))
                  for name in CHIP_FACETS}
        for name in ("locations", "company_hq"):
            facets[name] = _reread_places(facets[name])
        return cls(**facets,
                   headcount=_bands(raw.get("headcount"), HEADCOUNT),
                   revenue=_bands(raw.get("revenue"), REVENUE),
                   years_in_role=_bands(raw.get("years_in_role"), YEARS_IN_ROLE),
                   similar_titles=_bool(raw.get("similar_titles"), True),
                   changed_jobs_90d=_bool(raw.get("changed_jobs_90d"), False))

    @classmethod
    def from_legacy(cls, params) -> "SearchSpec":
        """A session saved before filters: industries, roles and one line of
        location text ("Global except india") become the facets they meant."""
        p = params if isinstance(params, dict) else {}
        location = p.get("location") if isinstance(p.get("location"), str) else ""
        include, exclude = parse_location_text(location)
        return cls.from_dict({
            "industries": {"include": _values(p.get("industries"))},
            "job_titles": {"include": _values(p.get("roles"))},
            "locations": {"include": include, "exclude": exclude},
        })

    @classmethod
    def from_params(cls, params) -> "SearchSpec":
        """A run's saved params: its `filters` when it has them, else the
        legacy fields read as filters."""
        p = params if isinstance(params, dict) else {}
        if isinstance(p.get("filters"), dict):
            return cls.from_dict(p["filters"])
        return cls.from_legacy(p)

    def copy(self) -> "SearchSpec":
        return SearchSpec.from_dict(self.to_dict())

    # -- reading it -----------------------------------------------------------
    def facet(self, name: str) -> Facet:
        return getattr(self, name)

    def count(self, name: str) -> int:
        """How many values one facet (chip or band) holds."""
        if name in BAND_FACETS:
            return len(getattr(self, name))
        return getattr(self, name).count()

    def active_count(self) -> int:
        """Every value set, across the panel — the badge on "Lead filters"."""
        return (sum(self.count(n) for n in CHIP_FACETS + BAND_FACETS)
                + int(self.changed_jobs_90d))

    def role_terms(self) -> list:
        """The roles a search asks Exa for: the job titles, or — with none —
        seniority × function made into titles ("Head Operations", "VP Sales"),
        a function alone ("Operations leader"), or a seniority alone."""
        if self.job_titles.include:
            return list(self.job_titles.include)
        sen = [w for w in (_SENIORITY_WORD.get(k, "") for k in self.seniority.include) if w]
        fun = [_function_word(k) for k in self.functions.include]
        if sen and fun:
            return [f"{s} {f}" for f in fun for s in sen][:12]
        if fun:
            return [f"{f} leader" for f in fun]
        return sen

    def is_searchable(self) -> bool:
        """A search needs someone to look for: a title, a function or a
        seniority. Industry, location and the rest are optional."""
        return bool(self.role_terms())

    def location_label(self, limit: int = 2) -> str:
        """"Anywhere", "India, UAE", "Anywhere except India"."""
        def names(values):
            head = ", ".join(values[:limit])
            return head + (f" +{len(values) - limit}" if len(values) > limit else "")
        base = names(self.locations.include) if self.locations.include else "Anywhere"
        return f"{base} except {names(self.locations.exclude)}" if self.locations.exclude else base

    def summary(self) -> str:
        """The spec in a few words: "6 titles · 10 industries · Anywhere except
        India · +3 more"."""
        parts = []
        n = len(self.job_titles.include)
        if n:
            parts.append(f"{n} title" if n == 1 else f"{n} titles")
        m = len(self.industries.include)
        if m:
            parts.append(f"{m} industry" if m == 1 else f"{m} industries")
        parts.append(self.location_label())
        shown = n + m + self.locations.count()
        others = self.active_count() - shown
        if others > 0:
            parts.append(f"+{others} more")
        return " · ".join(parts)

    def legacy_params(self) -> dict:
        """The pre-filter fields, kept beside `filters` in a session so a list
        label and an older build still read the run."""
        return {"industries": list(self.industries.include),
                "roles": self.role_terms(),
                "location": self.location_label(limit=99)}


# ── enforcement and planning (engine side) ────────────────────────────────────
# Pure functions of (spec, lead, props, facts): the source loop calls them for
# every row Exa returns, and a test pins every case without a network. Places
# (countries, regions, the cities inside them) come from places.py, imported
# where they are needed so the model above stays importable on its own.

# -- reading titles and phrases ----------------------------------------------

def _norm_title(text) -> str:
    """Title text as the matchers read it: case-folded, "R&D" kept as one word,
    "&" read as "and", punctuation and hyphens as spaces — but the dot inside
    "Industry 4.0" kept, so it stays one token."""
    t = (text if isinstance(text, str) else "").casefold()
    t = re.sub(r"\br\s*&\s*d\b", " rnd ", t)
    t = re.sub(r"\bl\s*&\s*d\b", " lnd ", t)
    t = t.replace("&", " and ")
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = re.sub(r"[^\w.]+", " ", t).replace("_", " ")
    return " ".join(t.split())


# Short forms written both ways, read as the long form, so "Sr. VP Ops" and
# "Senior Vice President Operations" are the same words to a phrase check.
_ABBREV = {
    "sr": "senior", "snr": "senior", "jr": "junior", "asst": "assistant",
    "dy": "deputy", "addl": "additional", "jt": "joint", "mgr": "manager",
    "vp": "vice president", "svp": "senior vice president",
    "evp": "executive vice president", "avp": "assistant vice president",
    "gm": "general manager", "agm": "assistant general manager",
    "dgm": "deputy general manager", "md": "managing director",
    "ceo": "chief executive officer", "coo": "chief operating officer",
    "cto": "chief technology officer", "cfo": "chief financial officer",
    "cio": "chief information officer", "hod": "head of department",
    "engg": "engineering", "mfg": "manufacturing", "ops": "operations",
    "rnd": "research and development", "hr": "human resources",
    "mgmt": "management",
}
_STOP = frozenset({"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"})


def _stem(word: str) -> str:
    # A plural is the same word: "Operations" / "Operation", "Automobiles".
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _tokens(text) -> list:
    out = []
    for word in _norm_title(text).split():
        out.extend(_stem(w) for w in _ABBREV.get(word, word).split())
    return out


def _contains(words: list, want: list) -> bool:
    n = len(want)
    return bool(n) and any(words[i:i + n] == want for i in range(len(words) - n + 1))


def _has_phrase(text, phrase) -> bool:
    """The phrase's words stand together, in order, in the text — word for
    word, so "India" is not inside "Indianapolis"."""
    return _contains(_tokens(text), _tokens(phrase))


def _alternatives(value) -> list:
    """"Plant Head / Head of Manufacturing" → both halves; no "/" → itself."""
    parts = [p.strip() for p in str(value).split("/") if p.strip()]
    return parts or [str(value)]


# -- seniority -----------------------------------------------------------------
# Ordered: a rule that matches takes its words out of the title, so a later
# rule can't read them again — "vice president" is gone before "president" is
# looked for, "managing director" before "director", "chief manager" (a bank /
# PSU middle grade) before "chief".
_SENIORITY_RULES = tuple((re.compile(p), key) for key, p in (
    ("", r"\b(?:product|process|service|data|platform|system|application|budget|risk|asset) owner\b"),
    ("", r"\b(?:business|channel|alliance|implementation|solutions?|strategic|technology"
         r"|learning|people|finance|hr|human resources?) partner\b"),
    ("", r"\bpartner\b(?= (?:manager|management|success|marketing|sales|development|relations"
         r"|alliances?|programs?|ecosystem|accounts?|enablement)\b)"),
    ("director", r"\bchief general manager\b|\bcgm\b"),
    ("manager", r"\bchief manager\b"),
    ("head", r"\bchief (?:engineer|architect|scientist|economist|designer|chemist|metallurgist|accountant)\b"),
    ("vp", r"\bvice president\b|\b[aesg]?vp\b"),
    ("c_suite", r"\b(?:joint |deputy |additional )?managing director\b|\b[jd]?md\b|\bcmd\b"
                r"|\b(?:executive|whole ?time) director\b"
                r"|\b(?:vice |executive )?chair(?:man|woman|person)?\b|\bpresident\b"
                r"|\bchief\b(?! of staff)(?: \w+){1,3}? officer\b|\bc[a-z]{1,2}o\b"
                r"|\bchief (?:executive|operating|technology|technical|information|financial|finance"
                r"|digital|marketing|people|revenue|product|strategy|commercial|business|data"
                r"|security|risk|compliance|legal|sustainability|transformation|procurement"
                r"|manufacturing|innovation|growth|customer|medical|investment|operations)\b"),
    ("owner", r"\b(?:co ?)?owner\b|\bproprietor\b|\bproprietress\b"),
    ("founder", r"\b(?:co ?)?founder\b|\bfounding (?:partner|member|director)\b"),
    ("partner", r"\bpartner\b"),
    ("manager", r"\b(?:assistant|deputy|additional|associate|joint) general manager\b|\b[adj]gm\b"),
    ("director", r"\b(?:senior |group |chief )?general manager\b|\b[sg]?gm\b"),
    ("senior", r"\b(?:team|group|shift|line|section|cell|module|tech|technical) lead(?:er)?\b"),
    ("head", r"\bhead\b|\bhod\b|\bleader\b"),
    ("director", r"\bdirector\b|\bdir\b"),
    ("manager", r"\bmanager\b|\bmgr\b|\bsuperintendent\b|\bsupervisor\b|\bin ?charge\b"),
    ("intern", r"\bintern(?:ship)?\b|\btrainee\b|\bapprentice(?:ship)?\b|\bget\b|\bstudent\b"),
    ("senior", r"\bsenior\b|\bsr\b|\bsnr\b|\blead\b|\bprincipal\b"
               r"|\bstaff (?:engineer|scientist|consultant|architect)\b"),
))
# A level from manager up outranks "Senior": a "Sr. Manager" is a manager, and
# "Senior" (Apollo's senior individual contributor) is left for titles with no
# management word at all.
_LEVELS = frozenset({"owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager"})
_ENTRY = re.compile(
    r"\b(?:engineer|analyst|executive|associate|officer|specialist|consultant|co ?ordinator"
    r"|assistant|technician|operator|developer|designer|representative|clerk|accountant"
    r"|administrator|planner|inspector|programmer|scientist|architect|advisor|adviser|agent"
    r"|buyer|chemist|draughtsman|draftsman|fitter|foreman|junior|jr|trainer|auditor|surveyor"
    r"|machinist|welder|electrician|tester|recruiter|researcher|merchandiser|storekeeper"
    r"|member|staff|worker)s?\b")


def seniority_of(title: str) -> frozenset:
    """Every SENIORITY key the title reads as, from word-boundary, case-
    insensitive title words. "Founder & CEO" → {founder, c_suite}; "Vice
    President Sales" → {vp} (never c_suite: the "president" inside "vice
    president" is not a president); "Managing Director" → {c_suite} (not
    director); "Plant Head" / "Head of X" → {head}; "General Manager" / "GM" →
    {director}; "AGM" / "DGM" / "Manager" → {manager}; "Senior X" / "Sr." /
    "Lead" / "Principal" → {senior}; "Intern" / "Trainee" / "Apprentice" →
    {intern}; a plain individual title ("Engineer", "Analyst", "Executive",
    "Associate") → {entry}. Empty title → empty set."""
    text = _norm_title(title)
    if not text:
        return frozenset()
    keys = set()
    for pattern, key in _SENIORITY_RULES:
        if pattern.search(text):
            if key:
                keys.add(key)
            text = pattern.sub(" ", text)
    if keys & _LEVELS:
        keys.discard("senior")
    if not keys and _ENTRY.search(text):
        keys.add("entry")
    return frozenset(keys)


# -- function ------------------------------------------------------------------
# (key, pattern, consume). The consuming phrases come first: each holds another
# function's word ("Business DEVELOPMENT" is not R&D, "DIGITAL Marketing" is not
# automation, "Key ACCOUNTS" is not finance) and is taken out once read.
_FUNCTION_RULES = tuple((key, re.compile(p), consume) for key, p, consume in (
    ("marketing", r"\b(?:digital|performance|growth|product|trade|industrial) marketing\b", True),
    ("business_development", r"\bbusiness development\b|\bbiz ?dev\b|\bbd[em]?\b|\bnew business\b", True),
    ("supply_chain", r"\b(?:vendor|supplier) development\b", True),
    ("it", r"\b(?:software|application) development\b", True),
    ("research", r"\b(?:new )?product development\b|\bnpd\b|\brnd\b|\bresearch and development\b", True),
    ("sales", r"\bkey accounts?\b|\baccount (?:manager|management|executive|director|head)\b"
              r"|\bexport sales\b", True),
    ("legal", r"\bcompany secretary\b|\bsecretarial\b", True),
    ("operations", r"\bchief operating officer\b|\bcoo\b|\boperations?\b|\bops\b|\boperational\b"
                   r"|\bexcellence\b|\bcontinuous improvement\b|\blean\b|\bsix sigma\b|\bkaizen\b"
                   r"|\bopex\b", False),
    ("manufacturing", r"\bmanufacturing\b|\bmfg\b|\bproduction\b|\bplants?\b|\bfactory\b"
                      r"|\bfactories\b|\bworks\b|\bassembly\b|\bshop ?floor\b|\bfabrication\b"
                      r"|\bfoundry\b|\bcasting\b|\bforging\b|\bmachining\b|\bmou?lding\b"
                      r"|\bpress shop\b|\bpaint shop\b|\btool ?room\b", False),
    ("automation", r"\bautomation\b|\bdigital\b|\bdigiti[sz]ation\b|\bdigitali[sz]ation\b"
                   r"|\btransformation\b|\bindustry 4\.0\b|\bi4\.0\b|\biiot\b|\biot\b"
                   r"|\bsmart (?:manufacturing|factory|factories|plants?|operations)\b"
                   r"|\brobotics?\b|\bplc\b|\bscada\b|\bdcs\b|\bmes\b|\binstrumentation\b"
                   r"|\bcontrol systems?\b|\bai\b|\bartificial intelligence\b"
                   r"|\bmachine learning\b|\bindustrial internet\b", False),
    ("engineering", r"\bengineer(?:ing|s)?\b|\bengg\b|\btechnical\b|\bcto\b|\bchief technology\b"
                    r"|\bdesign\b|\bmechanical\b|\belectrical\b|\bcivil\b|\btooling\b", False),
    ("it", r"\binformation technology\b|\binformation systems?\b|\bcio\b|\berp\b|\bsap\b"
           r"|\bsoftware\b|\binfrastructure\b|\bnetworks?\b|\bnetworking\b|\bcyber ?security\b"
           r"|\binformation security\b|\binfosec\b|\bdata\b|\bcloud\b|\bdevops\b|\bdeveloper\b"
           r"|\bprogrammer\b|\btechnology\b|\banalytics\b|\bdatabase\b", False),
    ("supply_chain", r"\bsupply chain\b|\bscm\b|\blogistics?\b|\bwarehous(?:e|es|ing)\b"
                     r"|\bmaterials?\b|\bpurchas(?:e|es|ing)\b|\bprocurement\b|\bsourcing\b"
                     r"|\bbuyer\b|\binventory\b|\bstores\b|\bdistribution\b|\bexim\b"
                     r"|\bimports?\b|\bexports?\b|\bcommodit(?:y|ies)\b|\bdispatch\b|\bfleet\b"
                     r"|\btransport(?:ation)?\b|\bvendors?\b|\bsuppliers?\b", False),
    ("quality", r"\bquality\b|\bqa\b|\bqc\b|\btqm\b|\binspection\b|\binspector\b|\btesting\b"
                r"|\bmetrology\b|\bassurance\b", False),
    ("maintenance", r"\bmaintenance\b|\bfacilit(?:y|ies)\b|\butilit(?:y|ies)\b|\breliability\b"
                    r"|\btpm\b|\bestates?\b", False),
    ("projects", r"\bprojects?\b|\bpmo\b|\bprogram(?:me)? manage(?:r|ment)\b|\bcommissioning\b"
                 r"|\berection\b|\bepc\b", False),
    ("research", r"\bresearch\b|\binnovation\b|\bscientist\b|\blab(?:oratory|oratories|s)?\b"
                 r"|\bformulation\b", False),
    ("sales", r"\bsales\b|\bselling\b|\bterritory\b|\bdealers?\b|\bchannel\b|\bpre ?sales\b"
              r"|\brevenue\b|\bcro\b|\bcommercial\b", False),
    ("business_development", r"\bpartnerships?\b|\balliances?\b|\bgrowth\b", False),
    ("marketing", r"\bmarketing\b|\bbrand(?:ing|s)?\b|\bcommunications?\b|\bpublic relations\b"
                  r"|\bpr\b|\badvertising\b|\bcontent\b|\bseo\b|\bdemand generation\b|\bcmo\b", False),
    ("product", r"\bproducts?\b", False),
    ("finance", r"\bfinance\b|\bfinancial\b|\baccounts?\b|\baccounting\b|\baccountant\b|\bcfo\b"
                r"|\btreasury\b|\btax(?:ation)?\b|\baudit(?:or|ing)?\b|\bcontroller\b|\bcosting\b"
                r"|\bfp and a\b|\bcredit\b|\binvestor relations\b", False),
    ("hr", r"\bhr\b|\bhuman resources?\b|\bpeople\b|\btalent\b|\brecruit(?:ment|er|ing)\b"
           r"|\bhiring\b|\bindustrial relations\b|\bpersonnel\b|\bpayroll\b|\blnd\b"
           r"|\blearning and development\b|\btraining\b|\bchro\b|\bhrbp\b", False),
    ("legal", r"\blegal\b|\bcompliance\b|\bcounsel\b|\blawyer\b|\badvocate\b|\battorney\b"
              r"|\bregulatory\b|\bgovernance\b|\bcontracts?\b", False),
    ("customer", r"\bcustomers?\b|\bclients?\b|\bafter sales\b|\bservice\b|\bsupport\b|\bcx\b"
                 r"|\bcrm\b|\bcall cent(?:er|re)\b|\bhelp ?desk\b", False),
    ("strategy", r"\bstrateg(?:y|ic)\b|\bgeneral management\b|\b(?:business|business unit|bu|country) head\b"
                 r"|\bceo\b|\bchief executive\b|\bmanaging director\b|\b[jd]?md\b|\bcmd\b"
                 r"|(?<!vice )\bpresident\b|\bcountry manager\b|\bcorporate planning\b"
                 r"|\bchief of staff\b|\b(?:executive|whole ?time) director\b"
                 r"|\bprofit cent(?:er|re)\b", False),
    ("admin", r"\badmin\b|\badministration\b|\badministrative\b|\boffice manager\b"
              r"|\bexecutive assistant\b|\bsecretary\b|\breceptionist\b|\bfront office\b"
              r"|\bpersonal assistant\b", False),
))


def function_of(title: str) -> frozenset:
    """Every FUNCTIONS key the title reads as ("Head - Manufacturing
    Excellence" → {manufacturing, operations}); empty when none."""
    text = _norm_title(title)
    keys = set()
    # "IT" only in capitals: case-folded it is the English word.
    if isinstance(title, str) and re.search(r"\bIT\b", title):
        keys.add("it")
    for key, pattern, consume in _FUNCTION_RULES:
        if pattern.search(text):
            keys.add(key)
            if consume:
                text = pattern.sub(" ", text)
    return frozenset(keys)


# -- dates ---------------------------------------------------------------------
_DATE = re.compile(r"^\s*(\d{4})(?!\d)(?:-(\d{1,2})(?!\d)(?:-(\d{1,2})(?!\d))?)?")


def _start_date(started) -> tuple | None:
    """(date, "day" | "month" | "year") for a role start, or None."""
    if not isinstance(started, str):
        return None
    m = _DATE.match(started)
    if m is None:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    try:
        start = datetime.date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None
    return start, ("day" if day else "month" if month else "year")


def _today(today) -> datetime.date:
    if isinstance(today, datetime.datetime):
        return today.date()
    if isinstance(today, datetime.date):
        return today
    return datetime.date.today()


def tenure_band(started: str, today=None) -> str:
    """The YEARS_IN_ROLE key for a role that started on `started` ("2021-04-01"
    or "2021-04"), as of `today` (a datetime.date; default today). Whole years:
    0 → "lt1", 1-2 → "1-2", 3-5 → "3-5", 6-10 → "6-10", 11+ → "gt10". "" when
    the start date can't be read or is in the future."""
    parsed = _start_date(started)
    if parsed is None:
        return ""
    start, now = parsed[0], _today(today)
    if start > now:
        return ""
    years = now.year - start.year - ((now.month, now.day) < (start.month, start.day))
    if years < 1:
        return "lt1"
    if years <= 2:
        return "1-2"
    if years <= 5:
        return "3-5"
    if years <= 10:
        return "6-10"
    return "gt10"


def _started_within(started, days: int, today=None) -> bool:
    """The role began no more than `days` ago. A start known only to the month
    (or year) counts that whole month (year): "2026-06" is recent until 90
    days after 30 June."""
    parsed = _start_date(started)
    if parsed is None:
        return False
    start, precision = parsed
    now = _today(today)
    if start > now:
        return False
    if precision == "month":
        end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) \
            - datetime.timedelta(days=1)
    elif precision == "year":
        end = datetime.date(start.year, 12, 31)
    else:
        end = start
    return (now - end).days <= days


# -- the person row --------------------------------------------------------------

def _live_role(props) -> dict:
    """The open-ended job in an Exa person's workHistory (the latest-starting
    one), else the first listed — the same pick source._current_job makes."""
    wh = props.get("workHistory") if isinstance(props, dict) else None
    wh = [w for w in wh if isinstance(w, dict)] if isinstance(wh, list) else []

    def dates(w):
        return w.get("dates") if isinstance(w.get("dates"), dict) else {}

    live = [w for w in wh if not dates(w).get("to")]
    if live:
        return max(live, key=lambda w: str(dates(w).get("from") or ""))
    return wh[0] if wh else {}


def _locations_of(lead, props) -> list:
    """Where the person is, best source first: the profile's location, then
    the live job's."""
    extra = getattr(lead, "extra", None) or {}
    candidates = (extra.get("location"),
                  props.get("location") if isinstance(props, dict) else None,
                  _live_role(props).get("location"))
    out = []
    for value in candidates:
        if isinstance(value, str) and value.strip() and value.strip() not in out:
            out.append(value.strip())
    return out


def _role_start(lead, props) -> str:
    role = _live_role(props)
    dates = role.get("dates") if isinstance(role.get("dates"), dict) else {}
    start = dates.get("from")
    if isinstance(start, str) and start.strip():
        return start
    since = (getattr(lead, "extra", None) or {}).get("since")
    return since if isinstance(since, str) else ""


def _place_verdict(where: str, include, exclude, reason: str) -> str:
    """"" / reason / "unknown" for one location string against a place facet.
    An exclusion that can't be ruled out is not passed: a place the reader
    can't place might be the excluded one."""
    from . import places
    outside = [places.matches(where, p) for p in exclude]
    if True in outside:
        return reason
    if None in outside:
        return "unknown"
    if include:
        inside = [places.matches(where, p) for p in include]
        if True in inside:
            return ""
        return "unknown" if None in inside else reason
    return ""


def _company_key(name) -> str:
    from .identity import norm_company
    return " ".join(w for w in norm_company(name).split() if w != "and")


def _carries(title_words: set, phrase: str) -> bool:
    want = [w for w in _tokens(phrase) if w not in _STOP]
    return bool(want) and set(want) <= title_words


def match_person(spec: SearchSpec, lead, props=None, today=None) -> str:
    """"" when the person passes every PERSON-level filter, else the REASONS
    key of the first one they fail. Reads lead.title, lead.company,
    lead.extra["location"] and, when given, the raw Exa person `props` (the
    live job's location and start date). Rules:
      · locations — the person's location (or the live job's location when the
        profile has none) must match an include place when there are includes,
        and must match no exclude place. A place matches by country, region,
        state or city (places.py), and a country named in the location string
        wins over a city name that also exists elsewhere. With any location
        filter set, a person whose location can't be read fails with
        "location_unknown" — a hidden location can't be proven outside India.
      · job_titles — any exclude phrase in the title fails; with
        similar_titles False the title must carry one include (all the
        significant words of one include, or of one "/"-separated alternative).
      · seniority / functions — the title's keys must meet an include (if any)
        and miss every exclude.
      · companies — current company matched after legal-suffix normalisation.
      · industries (exclude only) and keywords (exclude only) — the phrase must
        not appear in the title or the company name.
      · years_in_role — tenure_band of the live role must be a chosen band;
        unknown start fails.
      · changed_jobs_90d — the live role must have started within 90 days
        (month precision counts the whole month)."""
    title = getattr(lead, "title", "") or ""
    company = getattr(lead, "company", "") or ""

    loc = spec.locations
    if loc.active:
        verdict = "unknown"
        # A profile location nobody can place falls back to the live job's.
        for where in _locations_of(lead, props):
            verdict = _place_verdict(where, loc.include, loc.exclude, "location")
            if verdict != "unknown":
                break
        if verdict:
            return "location_unknown" if verdict == "unknown" else verdict

    jt = spec.job_titles
    for value in jt.exclude:
        if any(_has_phrase(title, alt) for alt in _alternatives(value)):
            return "job_title"
    if jt.include and not spec.similar_titles:
        words = set(_tokens(title))
        if not any(_carries(words, alt) for value in jt.include
                   for alt in _alternatives(value)):
            return "job_title"

    for name, reader, reason in (("seniority", seniority_of, "seniority"),
                                 ("functions", function_of, "function")):
        facet = spec.facet(name)
        if facet.active:
            keys = reader(title)
            if facet.include and not keys & set(facet.include):
                return reason
            if keys & set(facet.exclude):
                return reason

    if spec.companies.active:
        key = _company_key(company)
        if spec.companies.include and key not in {_company_key(c) for c in spec.companies.include}:
            return "company"
        if key and key in {_company_key(c) for c in spec.companies.exclude}:
            return "company"

    for name, reason in (("industries", "industry"), ("keywords", "keyword")):
        for value in spec.facet(name).exclude:
            if any(_has_phrase(text, alt) for text in (title, company)
                   for alt in _alternatives(value)):
                return reason

    if spec.years_in_role or spec.changed_jobs_90d:
        started = _role_start(lead, props)
        if spec.years_in_role and tenure_band(started, today) not in spec.years_in_role:
            return "years_in_role"
        if spec.changed_jobs_90d and not _started_within(started, 90, today):
            return "changed_jobs"
    return ""


# -- the company ---------------------------------------------------------------

def needs_company_facts(spec: SearchSpec) -> bool:
    """True when a COMPANY-level filter is set that a company lookup answers:
    headcount, revenue, company_hq, or an industry / keyword exclusion
    (checked against the company's description)."""
    return bool(spec.headcount or spec.revenue or spec.company_hq.active
                or spec.industries.exclude or spec.keywords.exclude)


def _on_record(value) -> int | None:
    """A company's size as a whole number, or None when the record holds none:
    missing, not a number, or nought — a size nobody wrote down, not a size."""
    try:
        n = None if value is None or isinstance(value, bool) else int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if n is not None and n > 0 else None


def match_company(spec: SearchSpec, lead, facts) -> str:
    """"" when the company passes every company-level filter, else the REASONS
    key. `facts` is the company lookup result — {"headcount": int|None,
    "revenue": int|None (US dollars a year), "hq": str, "description": str} —
    or None when nothing was found. Headcount bands are inclusive both ends;
    revenue bands take the lower bound and stop short of the upper ($10M is
    "10m-50m"). A company whose size is not on record, or that could not be
    looked up, passes headcount, revenue and the description checks (the
    caller counts it unverified), but NOT a Company HQ filter: like a person's
    hidden location, an HQ nobody found can't be proven outside an excluded
    place, so it fails "company_hq_unknown"."""
    if not isinstance(facts, dict):
        return "company_hq_unknown" if spec.company_hq.active else ""
    # An unknown size is unverified, not wrong.
    n = _on_record(facts.get("headcount")) if spec.headcount else None
    if n is not None:
        bands = [HEADCOUNT_RANGES[k] for k in spec.headcount if k in HEADCOUNT_RANGES]
        if not any(lo <= n and (hi is None or n <= hi) for lo, hi in bands):
            return "headcount"
    usd = _on_record(facts.get("revenue")) if spec.revenue else None
    if usd is not None:
        bands = [REVENUE_RANGES[k] for k in spec.revenue if k in REVENUE_RANGES]
        if not any(lo <= usd and (hi is None or usd < hi) for lo, hi in bands):
            return "revenue"
    hq = facts.get("hq") if isinstance(facts.get("hq"), str) else ""
    if spec.company_hq.active:
        # An empty or unreadable HQ is unknown, and unknown is not a pass: the
        # owner's rule is that an exclusion is real, not best-effort.
        verdict = _place_verdict(hq, spec.company_hq.include, spec.company_hq.exclude,
                                 "company_hq")
        if verdict:
            return "company_hq_unknown" if verdict == "unknown" else verdict
    texts = (getattr(lead, "title", "") or "", getattr(lead, "company", "") or "",
             facts.get("description") if isinstance(facts.get("description"), str) else "")
    for name, reason in (("industries", "industry"), ("keywords", "keyword")):
        for value in spec.facet(name).exclude:
            if any(_has_phrase(text, alt) for text in texts for alt in _alternatives(value)):
                return reason
    return ""


# -- planning the searches -------------------------------------------------------

# Title words people write both ways (the source's top-up swaps): one swap
# per role, longest phrase first, so "Managing Director" becomes "MD" rather
# than "Managing Head".
_ROLE_SWAPS = (
    ("chief executive officer", "CEO"), ("chief operating officer", "COO"),
    ("chief technology officer", "CTO"), ("chief financial officer", "CFO"),
    ("managing director", "MD"), ("vice president", "VP"),
    ("general manager", "GM"),
    ("ceo", "Chief Executive Officer"), ("coo", "Chief Operating Officer"),
    ("cto", "Chief Technology Officer"), ("cfo", "Chief Financial Officer"),
    ("md", "Managing Director"), ("vp", "Vice President"),
    ("gm", "General Manager"),
    ("head", "Director"), ("director", "Head"),
)


def _role_alt(role: str) -> str:
    for word, alt in _ROLE_SWAPS:
        new, hits = re.subn(rf"\b{re.escape(word)}\b", alt, role, count=1, flags=re.IGNORECASE)
        if hits:
            return new
    return role


def _qkey(query: str) -> str:
    return " ".join(query.casefold().split())


def _size_phrase(bands) -> str:
    """"small" (up to 50), "mid-size" (51-1,000), "large" (1,001+), joined;
    every size at once says nothing, so it says nothing."""
    sizes = set()
    for key in bands:
        lo, hi = HEADCOUNT_RANGES.get(key, (None, None))
        if lo is None:
            continue
        sizes.add("small" if hi is not None and hi <= 50
                  else "mid-size" if hi is not None and hi <= 1000 else "large")
    ordered = [s for s in ("small", "mid-size", "large") if s in sizes]
    return "" if len(ordered) in (0, 3) else " and ".join(ordered)


def _keyword_phrase(keywords) -> str:
    kws = list(keywords)[:3]
    if not kws:
        return ""
    text = kws[0] if len(kws) == 1 else ", ".join(kws[:-1]) + " and " + kws[-1]
    return f" with {text} experience"


def _where(spec: SearchSpec) -> tuple:
    """("person" | "hq" | "", the places to rotate through). Includes are
    asked for as given (less what an exclusion removes from inside them); with
    only exclusions, the major regions that are left."""
    loc, hq = spec.locations, spec.company_hq
    for kind, facet in (("person", loc), ("hq", hq)):
        if facet.include:
            if not facet.exclude:
                return kind, list(facet.include)
            # "Europe except Germany" → the European countries left. Nothing
            # left (Gujarat, except India) names no place rather than an
            # excluded one.
            from . import places
            return kind, list(places.regions_outside(facet.exclude, facet.include))
    for kind, facet in (("person", loc), ("hq", hq)):
        if facet.exclude:
            from . import places
            return kind, list(places.regions_outside(facet.exclude))
    return "", []


def _banned(spec: SearchSpec, trust: str = "") -> dict:
    """Every excluded value as word lists a query must not contain: the typed
    values ("/" alternatives apart), the labels of excluded options, and for an
    excluded place every name inside it — "India" also bans "Pune", "Bengaluru",
    "Maharashtra". `trust` names a place facet whose aliases are left out."""
    phrases = []
    for name in CHIP_FACETS:
        options = CLOSED_FACETS.get(name)
        for value in spec.facet(name).exclude:
            phrases.extend(_alternatives(label_of(options, value) if options else value))
    for name in ("locations", "company_hq"):
        values = spec.facet(name).exclude
        if values and name != trust:
            from . import places
            for value in values:
                # Two-letter codes ("in", "up") are English words in a query.
                phrases.extend(a for a in places.aliases_of(value)
                               if isinstance(a, str) and len(a.strip()) >= 3)
    index: dict = {}                    # first word → the phrases starting with it
    for phrase in phrases:
        words = _tokens(phrase)
        if words and words not in index.setdefault(words[0], []):
            index[words[0]].append(words)
    return index


def _names_any(words: list, index: dict) -> bool:
    """Does any banned phrase stand, word for word, in `words`?"""
    return any(words[i:i + len(b)] == b
               for i, w in enumerate(words) for b in index.get(w, ()))


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _phrase(variant: int, role: str, target: str, is_company: bool, size: str,
            kind: str, place: str, kw: str) -> str:
    """One query. Variant 0 is the first pass; 1-4 are the top-up rounds, each
    a different way of asking for the same people (the spirit of the source's
    _VARIANTS): a plainer noun, the other spelling of the seniority word, a
    "senior" in front, the industry leading."""
    alt = _role_alt(role)

    def where(has_org: bool) -> str:
        if not place:
            return ""
        if kind == "hq":
            return f" headquartered in {place}" if has_org else f" at a company headquartered in {place}"
        return f" in {place}"

    senior = "" if "senior" in _tokens(role) else "senior "
    if is_company:
        body = (f"{role} at {target}", f"{alt} at {target}", f"{role}, {target}",
                f"{senior}{role} at {target}", f"{target} leader, {alt}")[variant]
        return body + where(True) + kw
    org = " ".join(x for x in (size, target) if x)
    one_size = size.replace(" and ", " or ")        # "a mid-size or large company"
    one_org = " ".join(x for x in (one_size, target) if x)
    if variant == 0:
        body = f"{role} at {org} companies" + where(True) if org else role + where(False)
    elif variant == 1:
        body = f"{role} at {org} firms" + where(True) if org else f"{role} at a company" + where(True)
    elif variant == 2:
        if target:
            lead_in = f" at {_article(size)} {one_size} company" if size else ""
            body = f"{alt}{lead_in} in the {target} industry" + where(True)
        else:
            body = (f"{alt} at {_article(size)} {one_size} company" + where(True)) if size \
                else alt + where(False)
    elif variant == 3:
        body = (f"{senior}{role} at {_article(one_org)} {one_org} company" + where(True)) if org \
            else senior + role + where(False)
    else:
        body = f"{org + ' ' if org else ''}business leader, {alt}" + where(False)
    return body + kw


_TOPUP_ROUNDS = 4
# The fewest first-pass searches a location rotation is spread over: a lone
# pairing is asked in this many places, a 6 × 10 grid still once per pairing.
_FIRST_PASS_FLOOR = 12
# Places written with "the" in a sentence.
_THE = frozenset({"united states", "united kingdom", "united arab emirates", "netherlands",
                  "philippines", "czech republic", "dominican republic", "bahamas",
                  "gambia", "maldives", "middle east", "caribbean", "americas", "nordics",
                  "european union", "central african republic", "marshall islands",
                  "solomon islands", "cayman islands", "republic of the congo",
                  "democratic republic of the congo"})


def _in_place(place: str) -> str:
    """"United States" → "the United States"; anything else as written."""
    return f"the {place}" if place.casefold() in _THE else place


def _queries(spec: SearchSpec, variant: int) -> list:
    roles = [r for r in spec.role_terms() if r.strip()]
    if not roles:
        return []
    kind, places_ = _where(spec)
    # Headcount only: "a $10M-50M company" is not how a profile is written, and
    # a size word read off revenue would be a guess. Revenue bands are checked
    # on the company's record (match_company), not asked for.
    size = _size_phrase(spec.headcount)
    kw = _keyword_phrase(spec.keywords.include)
    banned = _banned(spec)
    # The rotating place was picked clear of its OWN facet's exclusions by
    # places.regions_outside, so only the other checks apply to it; checking
    # it against those aliases again would let one veto a clean place —
    # "america" (the US) inside "Latin America".
    own = {"person": "locations", "hq": "company_hq"}.get(kind, "")
    banned_place = _banned(spec, trust=own) if own else banned
    if spec.companies.include:
        # A named company is a sharper target than any industry; the label
        # stays the industry when there is exactly one to name.
        label = spec.industries.include[0] if len(spec.industries.include) == 1 else ""
        targets = [(label, c, True) for c in spec.companies.include]
    else:
        targets = [(ind, ind, False) for ind in (spec.industries.include or [""])]
    # Role + target pick the place, so every industry meets every place across
    # the roles. A small grid asks each pairing in several places (one Exa
    # page is 100 people — one country is not "anywhere except India"); a big
    # one already spreads. Each top-up round moves the rotation on — past every
    # place a round uses when the list is longer (the world minus India is
    # ~190 countries), else by one.
    n, pairings = len(places_), len(roles) * len(targets)
    per_pairing = min(n, -(-_FIRST_PASS_FLOOR // pairings)) if n else 1
    width = len(roles) + len(targets) + per_pairing - 2
    shift = variant * width if n > width else variant
    out, seen = [], set()
    for slot in range(per_pairing):                         # every pairing once, then again
        for ri, role in enumerate(roles):                   # role-outer: breadth first
            for ti, (label, target, is_company) in enumerate(targets):
                place = _in_place(places_[(ri + ti + slot + shift) % n]) if n else ""
                query = _phrase(variant, role, target, is_company, size, kind, place, kw)
                key = _qkey(query)
                if key in seen:
                    continue
                bare = _tokens(_phrase(variant, role, target, is_company, size, kind, "", kw))
                if _names_any(bare, banned) or _names_any(_tokens(query), banned_place):
                    continue
                seen.add(key)
                out.append((label, query))
    return out


def plan(spec: SearchSpec) -> list:
    """The first-pass Exa queries as (industry_label, query) pairs, breadth-
    first across industries (role-outer, like source.queries). Never contains an
    excluded value; locations rotate through the includes, or — with only
    exclusions — through the major regions left once those are removed."""
    return _queries(spec, 0)


def top_up(spec: SearchSpec, round_no: int) -> list:
    """Round `round_no` (1, 2, …) of top-up queries once the first pass came
    back short: the same pairings asked in other words, with the location
    rotation moved on, so a round reaches people and regions the earlier ones
    did not. Nothing the first pass or an earlier round already sent; the same
    exclusion rule as `plan`. [] once the phrasings run out."""
    if not isinstance(round_no, int) or not 1 <= round_no <= _TOPUP_ROUNDS:
        return []
    sent = {_qkey(q) for _, q in plan(spec)}
    for earlier in range(1, round_no):
        sent.update(_qkey(q) for _, q in _queries(spec, earlier))
    fresh = [(label, q) for label, q in _queries(spec, round_no) if _qkey(q) not in sent]
    # A round whose every query repeats an earlier one is not the end — the
    # caller stops at the first empty round, so hand it the next phrasing.
    return fresh or top_up(spec, round_no + 1)
