"""
Leads & Outreach — everyone Prism already has, filtered as you click
────────────────────────────────────────────────────────────────────
Apollo's Find People re-answers every filter change from its own database, so
the table moves the moment you tick something. Prism's people come from Exa —
a search costs credits — so the owner chose (23-Sep-2026) the Apollo feel
without the Apollo bill: filters are instant over the people Prism ALREADY
holds, and fetching new ones is a separate, explicit button.

The POOL is those people, one row per person however many ways they arrived:

  · saved contacts (contacts.py) — CSV imports, saves, exports, sequences;
  · everyone every past run found (sessions.py), with the newest qualified
    dossier when a run qualified them.

Two people are one when their identity keys touch (prospector.identity) —
the same rule a run uses to skip someone it already pulled. A saved contact's
fields win (the owner saved that record); among runs, the newest wins.

`filter_people` applies a SearchSpec the way Apollo does — AND across filters,
OR within one — using the SAME checks a search enforces (filters.match_person
and match_company), plus what only a local pool can check:

  · Job titles with "similar titles" on: match_person lets an include only
    steer an Exa query then; here it is a real filter — a title carrying the
    words of an include, or reading as the same seniority and function
    ("Plant Head" ~ "Head of Manufacturing").
  · Industry and Keywords INCLUDES, which a search could only steer: checked
    against what the person carries (their industry, their account's, their
    imported columns); a person carrying no match fails.
  · …except the people a SEARCH steered by those same values found. Those
    three includes only ever steered that search, which then took whoever
    came back — so a person it found passes them here too (Person.steered,
    from the run's own filters). Without that, pressing Find new people
    brought back 300 people and the page showed the dozen whose Exa row
    happened to name the industry: the "why only 37?" of 22-Sep-2026 again.
  · Contact CSV import — the person carries one of the chosen import ids.
  · Account CSV import — the person's company (by name, or by the domain of
    their e-mail / website) is one of the chosen imports' companies; that
    company's own record then answers the company-level filters (industry,
    headcount, HQ) the person row never carried.
  · The "Search people" box — name, title or company contains the text.

Total / Net New / Saved (`split`) is Apollo's: Saved = saved contacts,
Net New = everyone else in the result.

Qt-free and stdlib-only beyond prospector; the widget and the workbench build a
pool off the UI thread and filter it in memory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from prospector import filters as F
from prospector.identity import keys_of, norm_company, norm_text
from prospector.models import Lead

from addons.leads.imports import company_keys, domain_of

PAGE_SIZE = 25                      # Apollo's page
SORTS = ("relevance", "name", "newest", "company")


@dataclass
class Person:
    lead: Lead
    dossier: object = None          # the newest qualified Dossier, if any
    draft: object = None           # that dossier's draft, if one was written
    saved: bool = False
    imports: tuple = ()             # Contact CSV import ids
    first_seen: str = ""            # ISO: the earliest save / run that had them
    last_seen: str = ""
    sessions: tuple = ()            # ids of the runs they appear in
    account: dict = field(default_factory=dict)   # their Account CSV import company
    # What the searches that found them were steered by: {facet: frozenset
    # of casefolded include values} for the STEERED facets (_steering).
    steered: dict = field(default_factory=dict)

    @property
    def fit(self) -> float:
        """The triage fit — what the table's FIT column shows."""
        return float(getattr(self.lead, "fit_score", 0) or 0)

    @property
    def score(self) -> float:
        """The qualified dossier's score, 0 when never qualified."""
        value = getattr(self.dossier, "score", None)
        return float(value) if isinstance(value, (int, float)) else 0.0

    @property
    def qualified(self) -> bool:
        return self.dossier is not None


# ── deliverability ────────────────────────────────────────────────────────────

# key → the label the table's STATUS column shows (cockpit.status_of).
EMAIL_STATUS_LABEL = {
    "mailed": "Mailed", "no_email": "No email", "verified": "Verified",
    "invalid": "Invalid", "catch_all": "Catch-all", "unknown": "Unknown",
    "guessed": "Guessed",
}


def email_status_of(lead, draft=None) -> str:
    """The deliverability KEY for a person — one rule for the STATUS column
    and the "Email status" filter. Someone already sent to is "mailed";
    otherwise the free verify verdict, or "guessed" for an un-checked
    pattern address."""
    if draft is not None and getattr(draft, "status", "") == "sent":
        return "mailed"
    if not (getattr(lead, "email", "") or "").strip():
        return "no_email"
    check = (getattr(lead, "extra", None) or {}).get("email_check") or ""
    return {"valid": "verified", "invalid": "invalid",
            "catch-all": "catch_all", "unknown": "unknown"}.get(check, "guessed")


# ── building ──────────────────────────────────────────────────────────────────

# The includes a search can only STEER — they shape the query, and whoever
# comes back is taken (source._enforces): industries, keywords, and job
# titles while "similar titles" is on.
STEERED = ("industries", "keywords", "job_titles")


def _fold(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _steering(params) -> dict:
    """{facet: frozenset of casefolded values} — what one run's search was
    steered by, read from the params its session saved (a legacy run's
    industries and roles included). {} for a run that searched nothing (a
    sheet run) or whose params can't be read."""
    if not isinstance(params, dict):
        return {}
    try:
        spec = F.SearchSpec.from_params(params)
    except Exception:                                   # noqa: BLE001
        return {}
    out = {}
    for facet in STEERED:
        if facet == "job_titles" and not spec.similar_titles:
            continue        # enforced by the search itself: match_person read them
        values = frozenset(v for v in (_fold(x) for x in getattr(spec, facet).include) if v)
        if values:
            out[facet] = values
    return out


def _add_steering(person, steer: dict) -> None:
    for facet, values in steer.items():
        person.steered[facet] = person.steered.get(facet, frozenset()) | values


def build(contacts=(), runs=()) -> list:
    """The pool from saved contacts and past runs.

    `contacts` — contacts.Contact records. `runs` — (session_id, created_at,
    all_leads, dossiers[, drafts[, params]]) per run, in any order; `params`
    is what the run's session saved it was asked (its filters). A person's
    dossier is the one from their newest run that qualified them, and their
    draft the one written for that dossier."""
    people: list = []
    by_key: dict = {}

    def place(lead):
        keys = keys_of(lead)
        at = next((by_key[k] for k in keys if k in by_key), None)
        return keys, at

    def index(at, lead):
        for key in keys_of(lead):
            by_key.setdefault(key, at)

    for c in contacts or ():
        lead = getattr(c, "lead", None)
        if lead is None:
            continue
        keys, at = place(lead)
        if not keys:
            continue
        when = getattr(c, "saved_at", "") or ""
        if at is None:
            people.append(Person(lead=lead, saved=True,
                                 imports=tuple(getattr(c, "imports", ()) or ()),
                                 first_seen=when, last_seen=when))
            at = len(people) - 1
        else:
            p = people[at]
            p.saved = True
            p.imports = tuple(dict.fromkeys(p.imports + tuple(getattr(c, "imports", ()) or ())))
        index(at, lead)

    ordered = sorted(runs or (), key=lambda r: r[1] or "", reverse=True)
    for run in ordered:
        session_id, created_at, all_leads, dossiers = run[:4]
        drafts = run[4] if len(run) > 4 else ()
        steer = _steering(run[5] if len(run) > 5 else None)
        written = {id(getattr(dr, "dossier", None)): dr for dr in drafts or ()}
        qualified = {id(getattr(d, "lead", None)): d for d in dossiers or ()}
        leads = list(all_leads or ())
        # A dossier whose lead the run's list lacks still names a person.
        known = {id(x) for x in leads}
        leads += [d.lead for d in dossiers or ()
                  if getattr(d, "lead", None) is not None and id(d.lead) not in known]
        for lead in leads:
            keys, at = place(lead)
            if not keys:
                continue
            dossier = qualified.get(id(lead))
            draft = written.get(id(dossier)) if dossier is not None else None
            if at is None:
                people.append(Person(lead=lead, dossier=dossier, draft=draft,
                                     first_seen=created_at or "",
                                     last_seen=created_at or "",
                                     sessions=(session_id,)))
                at = len(people) - 1
            else:
                p = people[at]
                if p.dossier is None and dossier is not None:
                    p.dossier = dossier       # newest run first: keep the first
                    p.draft = draft
                if session_id not in p.sessions:
                    p.sessions = p.sessions + (session_id,)
                if created_at:
                    p.first_seen = min(x for x in (p.first_seen, created_at) if x)
                    p.last_seen = max(p.last_seen, created_at)
            if steer:
                _add_steering(people[at], steer)
            index(at, lead)
    return people


# ── filtering ─────────────────────────────────────────────────────────────────

def _domains_of(lead) -> set:
    extra = getattr(lead, "extra", None) or {}
    out = set()
    addresses = [getattr(lead, "email", "")] + list(extra.get("other_emails") or ())
    for addr in addresses:
        d = domain_of(addr) if isinstance(addr, str) and "@" in addr else ""
        if d:
            out.add(d)
    site = domain_of(extra.get("website", ""))
    if site:
        out.add(site)
    return out


def _account_for(lead, accounts) -> dict:
    """The Account CSV import company this person works at, or {} — by name
    first, then by the domain of their e-mail or website. `accounts` is
    [(names, domains, {name/domain: company dict})]."""
    name = norm_company(getattr(lead, "company", ""))
    domains = _domains_of(lead)
    for names, doms, by in accounts:
        if name and name in names:
            return by.get(name, {})
        hit = next((d for d in domains if d in doms), None)
        if hit:
            return by.get(hit, {})
    return {}


def resolve_accounts(companies_by_import: dict) -> dict:
    """{import id: (names, domains, lookup)} from imports.companies_of(…) —
    built once per filter change, not once per person."""
    out = {}
    for import_id, companies in (companies_by_import or {}).items():
        names, domains = company_keys(companies)
        by = {}
        for c in companies:
            n = norm_company(c.get("name", ""))
            if n:
                by.setdefault(n, c)
            d = c.get("domain") or domain_of(c.get("website", ""))
            if d:
                by.setdefault(d, c)
        out[import_id] = (names, domains, by)
    return out


def _similar_title(title: str, include) -> bool:
    """A title matches a job-title include "or similar": it carries the
    include's significant words, or it reads as the same seniority AND the
    same function (whichever of the two the include names)."""
    words = set(F._tokens(title))
    t_sen, t_fun = F.seniority_of(title), F.function_of(title)
    for value in include:
        for alt in F._alternatives(value):
            if F._carries(words, alt):
                return True
            sen, fun = F.seniority_of(alt), F.function_of(alt)
            if (sen or fun) and (not sen or sen & t_sen) and (not fun or fun & t_fun):
                return True
    return False


def _industry_text(person: Person) -> str:
    lead = person.lead
    extra = getattr(lead, "extra", None) or {}
    parts = [getattr(lead, "industry", "") or "", str(extra.get("industry") or ""),
             person.account.get("industry", "")]
    return " · ".join(p for p in parts if p)


def _keyword_texts(person: Person) -> list:
    lead = person.lead
    extra = getattr(lead, "extra", None) or {}
    custom = extra.get("custom") if isinstance(extra.get("custom"), dict) else {}
    acc_custom = person.account.get("custom") if isinstance(person.account.get("custom"), dict) else {}
    return [getattr(lead, "title", "") or "", getattr(lead, "company", "") or "",
            _industry_text(person), " ".join(map(str, custom.values())),
            " ".join(map(str, acc_custom.values()))]


def _headcount(value):
    """A company size from a sheet cell — "500+", "51-200", "1,200" → a number
    inside the range (its lower bound), or None."""
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(value or ""))]
    return nums[0] if nums else None


def _facts(person: Person):
    """What is known about the person's company, in match_company's shape —
    from their Account CSV import record, else their own row. None when
    nothing is known (match_company then passes size filters as unverified
    and fails a Company HQ filter as unknown — its own rules)."""
    extra = getattr(person.lead, "extra", None) or {}
    acc = person.account
    size = _headcount(acc.get("headcount") or extra.get("headcount"))
    hq = acc.get("location", "")
    if size is None and not hq:
        return None
    return {"headcount": size, "revenue": None, "hq": hq, "description": ""}


class Matcher:
    """One filter pass: everything that depends only on the spec, worked out
    once — the loosened copy of the spec, the chosen imports, the query —
    then `test(person)` per person. A pool of thousands re-filters on every
    click, so nothing per-spec may be redone per person."""

    def __init__(self, spec, *, accounts=None, query: str = "", today=None):
        self.spec = spec
        self.today = today
        self.query = norm_text(query or "")
        self.contact_imports = frozenset(spec.contact_imports)
        self.accounts = [accounts[i] for i in spec.account_imports
                         if i in (accounts or {})]
        self.titles = list(spec.job_titles.include) if spec.similar_titles else []
        self.local = spec
        if self.titles:
            self.local = spec.copy()
            self.local.job_titles.include = []      # checked in test(), loosely
        self.industries = list(spec.industries.include)
        self.keywords = list(spec.keywords.include)
        # The same three, folded the way _steering folds a run's: a person a
        # search steered by any one of them found passes that facet here.
        self.steer = {"industries": frozenset(_fold(v) for v in self.industries),
                      "keywords": frozenset(_fold(v) for v in self.keywords),
                      "job_titles": frozenset(_fold(v) for v in self.titles)}
        self.company_facts = F.needs_company_facts(spec)
        self.statuses = frozenset(spec.email_status)

    def _steered(self, person: Person, facet: str) -> bool:
        """A search steered by one of this facet's includes found them."""
        return bool(person.steered.get(facet, frozenset()) & self.steer[facet])

    def test(self, person: Person) -> bool:
        spec, lead = self.spec, person.lead
        if self.contact_imports and not self.contact_imports.intersection(person.imports):
            return False
        if spec.qualified_only and not person.qualified:
            return False
        if spec.min_fit and person.fit < spec.min_fit:
            return False
        if self.statuses and email_status_of(lead, person.draft) not in self.statuses:
            return False
        if spec.account_imports:
            person.account = _account_for(lead, self.accounts)
            if not person.account:
                return False
        else:
            person.account = {}
        if self.query:
            # What the cockpit's own search always read: name, company,
            # title, e-mail and where they are.
            extra = getattr(lead, "extra", None) or {}
            hay = norm_text(" ".join(str(x or "") for x in (
                getattr(lead, "name", ""), getattr(lead, "title", ""),
                getattr(lead, "company", ""), getattr(lead, "email", ""),
                extra.get("location", ""))))
            if self.query not in hay:
                return False
        if self.titles and not self._steered(person, "job_titles") \
                and not _similar_title(getattr(lead, "title", "") or "", self.titles):
            return False
        if F.match_person(self.local, lead, None, self.today):
            return False
        for facet, include, texts in (
                ("industries", self.industries, lambda: [_industry_text(person)]),
                ("keywords", self.keywords, lambda: _keyword_texts(person))):
            if include and not self._steered(person, facet):
                got = [t for t in texts() if t]
                if not got or not any(F._has_phrase(t, alt) for t in got
                                      for v in include for alt in F._alternatives(v)):
                    return False
        if self.company_facts and F.match_company(spec, lead, _facts(person)):
            return False
        return True


def matches(person: Person, spec, *, accounts=None, query: str = "",
            today=None) -> bool:
    """Whether one person passes the whole spec — see the module docstring.
    `accounts` is resolve_accounts(...) for spec.account_imports. For many
    people, build one Matcher instead (filter_people does)."""
    return Matcher(spec, accounts=accounts, query=query, today=today).test(person)


def filter_people(people, spec, *, accounts=None, query: str = "", today=None) -> list:
    m = Matcher(spec, accounts=accounts, query=query, today=today)
    return [p for p in people or () if m.test(p)]


def split(people) -> dict:
    """Apollo's three tabs: {"total", "net_new", "saved"}."""
    people = list(people or ())
    return {"total": people,
            "net_new": [p for p in people if not p.saved],
            "saved": [p for p in people if p.saved]}


def sort_people(people, how: str = "relevance") -> list:
    """relevance — best fit first (the triage fit the FIT column shows, then
    a qualified score), newest first among equals; name / company — A–Z;
    newest — most recently found or saved first."""
    people = list(people or ())
    if how == "name":
        return sorted(people, key=lambda p: norm_text(getattr(p.lead, "name", "")) or "~")
    if how == "company":
        return sorted(people, key=lambda p: (norm_company(getattr(p.lead, "company", "")) or "~",
                                             norm_text(getattr(p.lead, "name", ""))))
    if how == "newest":
        return sorted(people, key=lambda p: p.last_seen, reverse=True)
    return sorted(people, key=lambda p: (p.fit, p.score, p.last_seen), reverse=True)


def page(people, index: int, size: int = PAGE_SIZE) -> dict:
    """One page: {"rows", "page" (0-based, clamped), "pages", "start", "end",
    "total"} — start/end 1-based for "1 - 25 of 312", 0 and 0 when empty."""
    people = list(people or ())
    total = len(people)
    pages = max(1, -(-total // size))
    index = min(max(0, int(index)), pages - 1)
    lo = index * size
    rows = people[lo:lo + size]
    return {"rows": rows, "page": index, "pages": pages,
            "start": lo + 1 if rows else 0, "end": lo + len(rows), "total": total}
