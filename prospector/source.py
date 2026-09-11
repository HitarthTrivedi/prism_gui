"""
Prism Sales Automation — source: build the list from the ICP
─────────────────────────────────────────────────────────────
Turns "here is who I sell to" into an actual list of named people at real
companies, with no sheet to start from. It drives Exa's People Search across
the seller's industries × the decision-maker roles that buy what they sell,
keeps the companies diverse (a cap per company, so one big name does not fill
the page), and hands the rest of the pipeline the same `Lead` objects an
ingested sheet would — so qualify, draft and export are unchanged.

Nothing here is invented: every lead is an Exa 'person' entity with a real name
and a live job. The e-mail is left to the enrich stage; a name in a role is all
this stage claims.

A person pulled in an earlier session is not pulled again: the caller passes
them in as `skip`, and because Exa has no "next page", the places they would
have taken are made up by top-up searches that ask for the same pairings in
other words. See `source`.

A search can also arrive as FILTERS — a `filters.SearchSpec`, the Apollo /
Sales Nav include-and-exclude facets ("Location: anywhere, except India").
Then the filters plan the searches, and every person who comes back is
checked against them before they take a slot: Exa has no exclusion parameter,
so its answer is only a suggestion and the check here is what makes an
exclusion real. Company-level filters (headcount, annual revenue, HQ) need the
company's own facts, looked up once per company per run.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from urllib.parse import urlsplit

from . import filters
from .identity import SeenIndex, norm_company
from .models import Lead

EXA_SEARCH_URL = "https://api.exa.ai/search"

# filters.top_up is asked round by round until it says it has nothing left;
# this only stops a planner that never does from looping for ever.
_MAX_TOP_UP_ROUNDS = 50
# Two top-up rounds in a row in which EVERY call failed: the key is spent or Exa
# is down, and further rounds would only burn the budget on errors.
_DEAD_ROUNDS = 2


def _exa_people(query: str, api_key: str, n: int = 50, timeout: int = 60) -> list | None:
    """The people rows for one search: a list — possibly empty — when Exa
    answered, None when the call itself failed (an exception, a non-200, a body
    with no results list). The two must stay apart: read as an empty page, a
    spent key or a dropped connection looks exactly like "no more people", and
    the run comes back short with nothing to say why."""
    import requests  # lazy, like the rest of the engine
    try:
        r = requests.post(
            EXA_SEARCH_URL,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "category": "people", "type": "auto",
                  "numResults": n}, timeout=timeout)
        if r.status_code != 200:
            return None
        results = r.json().get("results")
    except Exception:                                   # noqa: BLE001 — network is a status line
        return None
    return results if isinstance(results, list) else None


def _host(url) -> str:
    try:
        host = (urlsplit(url if isinstance(url, str) else "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _company_score(want: str, got, host: str = "") -> float:
    """How surely a company entity named `got` (at `host`) is the company a
    person row calls `want` (already norm_company'd): 1 for the same name,
    word overlap otherwise, lifted when one multi-word name holds the other
    ("Tata Motors" / "Tata Motors Passenger Vehicles") or the site is the name
    ("acmemotors.com")."""
    have = norm_company(got)
    if not have:
        return 0.0
    if have == want:
        return 1.0
    a, b = set(want.split()), set(have.split())
    score = len(a & b) / len(a | b)
    if min(len(a), len(b)) >= 2 and (a <= b or b <= a):
        score = max(score, 0.75)
    if host and host.split(".")[0] == want.replace(" ", ""):
        score = max(score, 0.9)
    return score


def _headcount(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        digits = re.sub(r"[,\s+]", "", value)
        return int(digits) if digits.isdigit() and int(digits) > 0 else None
    return None


# "$12.5M", "USD 1.2 billion", "12,500,000", "12,50,00,000" (the Indian
# grouping): an optional dollar mark, a number grouped in threes, the Indian way
# or not at all, and an optional scale word. Any other currency is not read — a
# rupee figure taken as dollars would put a company in the wrong band — and nor
# is a comma decimal: "1,25M" read as grouping would be a hundred times the figure.
_MONEY = re.compile(
    r"^(?:us\s*\$|usd|\$)?\s*(\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)(\.\d+)?\s*"
    r"(k|thousand|mm|mn|m|million|bn|b|billion|tn|t|trillion)?\s*(?:usd)?$",
    re.IGNORECASE)
_SCALE = {"k": 10 ** 3, "thousand": 10 ** 3, "m": 10 ** 6, "mm": 10 ** 6, "mn": 10 ** 6,
          "million": 10 ** 6, "b": 10 ** 9, "bn": 10 ** 9, "billion": 10 ** 9,
          "t": 10 ** 12, "tn": 10 ** 12, "trillion": 10 ** 12}


def _revenue(value) -> int | None:
    """Annual revenue in whole US dollars from what Exa's financials.revenueAnnual
    holds — a number, or text like "$12.5M" — else None. Nought, a negative and
    anything unreadable are None: a revenue not on record, which never fails a
    filter."""
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            amount = float(value)
        elif isinstance(value, str):
            m = _MONEY.match(value.strip())
            if m is None:
                return None
            whole, frac, scale = m.groups()
            amount = float(whole.replace(",", "") + (frac or "")) \
                * _SCALE.get((scale or "").lower(), 1)
        else:
            return None
    except OverflowError:                               # a figure past any float
        return None
    if not math.isfinite(amount) or amount < 1:
        return None
    return int(round(amount))


def _exa_company(name: str, api_key: str, timeout: int = 30) -> dict | None:
    """What Exa's company index knows about one employer: {"headcount": int |
    None, "revenue": int | None (US dollars a year, see `_revenue`), "hq":
    "City, Country", "description": str, "domain": host}. None when the call
    failed or nothing that came back is recognisably THAT company — a different
    firm's headcount would turn people away for a number that is not theirs, so
    a weak name match is no match. None never fails a filter: the caller passes
    the company and counts it unverified."""
    want = norm_company(name)
    if not want:
        return None
    import requests  # lazy, like the rest of the engine
    try:
        r = requests.post(
            EXA_SEARCH_URL,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": f"{name} company", "category": "company", "type": "auto",
                  "numResults": 3}, timeout=timeout)
        if r.status_code != 200:
            return None
        results = r.json().get("results")
    except Exception:                                   # noqa: BLE001 — a lookup is best-effort
        return None
    if not isinstance(results, list):
        return None
    best, best_score = None, 0.0
    for row in results:
        if not isinstance(row, dict):
            continue
        host = _host(row.get("url"))
        for e in (row.get("entities") or []):
            if not isinstance(e, dict) or e.get("type") not in (None, "", "company"):
                continue
            props = e.get("properties") or {}
            score = _company_score(want, props.get("name"), host)
            if score > best_score:
                best, best_score = (props, host), score
    if best is None or best_score < 0.5:
        return None
    props, host = best
    workforce = props.get("workforce")
    financials = props.get("financials")
    hq = props.get("headquarters")
    if isinstance(hq, dict):
        where = ", ".join(str(hq[k]).strip() for k in ("city", "country")
                          if isinstance(hq.get(k), str) and hq[k].strip())
        hq = where or str(hq.get("address") or "").strip()
    return {"headcount": _headcount(workforce.get("total") if isinstance(workforce, dict)
                                    else workforce),
            "revenue": _revenue(financials.get("revenueAnnual")
                                if isinstance(financials, dict) else None),
            "hq": hq if isinstance(hq, str) else "",
            "description": str(props.get("description") or ""),
            "domain": host}


def _enforces(spec) -> bool:
    """True when some filter can turn a person away. The includes that only
    steer the search — industries, keywords, job titles with "similar titles"
    on — cannot, so a spec made of those alone sources like the old ICP."""
    return bool(spec.locations.active or spec.seniority.active or spec.functions.active
                or spec.companies.active or spec.company_hq.active
                or spec.job_titles.exclude
                or (spec.job_titles.include and not spec.similar_titles)
                or spec.industries.exclude or spec.keywords.exclude
                or spec.headcount or spec.revenue or spec.years_in_role
                or spec.changed_jobs_90d)


def _current_job(props: dict) -> tuple:
    """(title, company, since) from the person's live (open-ended) role, else the
    most recent one — never a role they have already left."""
    wh = props.get("workHistory") or []
    live = [w for w in wh if not (w.get("dates") or {}).get("to")]
    pick = (sorted(live, key=lambda w: (w.get("dates") or {}).get("from") or "",
                   reverse=True)[0] if live else (wh[0] if wh else None))
    if not pick:
        return "", "", ""
    comp = pick.get("company") or {}
    company = comp.get("name", "") if isinstance(comp, dict) else str(comp)
    since = ((pick.get("dates") or {}).get("from") or "")[:7]
    return pick.get("title", ""), company, since


def _lead_of(row: dict, entity: dict, ind: str) -> Lead | None:
    """The Lead one person entity makes, or None when it is not a person with
    a name, a live title and a company — the only people worth a slot."""
    if entity.get("type") != "person":
        return None
    p = entity.get("properties") or {}
    name = (p.get("name") or "").strip()
    title, company, since = _current_job(p)
    if not (name and company and title):
        return None
    lead = Lead(name=name, title=title, company=company, industry=ind)
    lead.extra["location"] = p.get("location", "")
    lead.extra["since"] = since
    lead.extra["linkedin"] = row.get("url", "")
    return lead


def _pairings(industries: list, roles: list) -> list:
    """(role, industry) for every non-blank pairing, ROLE-OUTER — the one order
    both the first pass and the top-up rounds walk (see `queries`)."""
    inds = [i.strip() for i in industries if i.strip()]
    rols = [r.strip() for r in roles if r.strip()]
    return [(role, ind) for role in rols for ind in inds]


def queries(industries: list, roles: list, location: str = "India") -> list:
    """Every role × industry pairing as a natural-language people search, ordered
    ROLE-OUTER so the first passes span ALL industries (breadth first) before
    going deep. Otherwise one productive early industry fills `target` and the
    rest of the ICP is never sourced — the "only got one industry" bug."""
    loc = (location or "").strip()
    # Firm SIZE is NOT hardcoded — it lives in the industry text the user types
    # ("small and mid-size mechanical firms" vs "large automobile makers"), so
    # the same engine targets SMEs or enterprises with no code change. (It used
    # to force "large", quietly biasing every search toward big companies.)
    where = f"{loc} " if loc else ""
    return [(ind, f"{role} at {where}{ind} companies and manufacturers")
            for role, ind in _pairings(industries, roles)]


# ── top-up phrasings ──────────────────────────────────────────────────────────
# Exa has no "next page": the same query string returns the same people. Once
# earlier sessions' people are skipped, the only way further down a pairing is
# to ask for it in other words. Each template is one top-up round over every
# pairing; a seniority synonym or a plainer noun shifts the ranking enough to
# surface different names. An identical string is never sent twice (`_qkey`).
_VARIANTS = (
    "{role} at {ind} firms{loc}",
    "{role_alt} in the {ind} industry{loc}",
    "senior {role} at a {ind} company{loc}",
    "{ind} business leader, {role_alt}{loc}",
)

# Title words people write both ways. One swap per role, longest phrase first,
# so "Managing Director" becomes "MD" rather than "Managing Head".
_SENIORITY_SWAPS = (
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
    """The role with one seniority word written the other way ("VP Operations"
    → "Vice President Operations", "Plant Head" → "Plant Director"), or the
    role unchanged when it has none."""
    for word, alt in _SENIORITY_SWAPS:
        new, hits = re.subn(rf"\b{re.escape(word)}\b", alt, role, count=1,
                            flags=re.IGNORECASE)
        if hits:
            return new
    return role


def _qkey(query: str) -> str:
    """A query as "the same question?" sees it: case and spacing are not a
    different search, so they must not buy a second identical page."""
    return " ".join(query.casefold().split())


def source(industries: list, roles: list, api_key: str, *, location: str = "India",
           target: int = 300, per_company: int = 3, per_query: int = 50,
           max_queries: int = 30, on_progress=None,
           skip=None, stats: dict | None = None,
           max_extra_queries: int = 30, spec=None, today=None,
           max_company_lookups: int = 150) -> list[Lead]:
    """A deduped, company-diverse list of real people across the ICP.

    Runs the industry×role searches in PARALLEL batches (so a wide ICP doesn't
    feel like a hang), stops the moment `target` is reached, and never fires more
    than `max_queries` Exa calls however large the industries×roles grid is — a
    big matrix (11×10 = 110 pairings) must not quietly burn the key one slow
    sequential request at a time. `target` and `max_queries` are the two guards.

    `skip` is everyone earlier sessions already pulled (a SeenIndex, or anything
    answering `lead in skip`). They are passed over the moment their row is
    read — before the company and industry counters, or a re-run at the same
    ICP would spend its slots on people it then throws away. Skipping alone
    leaves the run short, though: the people behind them are only reachable by
    asking again differently. So when `skip` is given (or filters turn people
    away, below) and the first pass ends short of `target`, top-up rounds run —
    first the pairings the `max_queries` cut dropped, then each `_VARIANTS`
    phrasing over every pairing — with the per-industry share relaxed to
    `target` (the first pass already spread the list; now the productive
    industries may fill it) and `per_company` kept. They stop at `target`, after
    `max_extra_queries` extra calls in total, after a round that added nobody,
    or after two rounds in a row in which every call failed (a spent key must
    not burn the whole budget on errors). One failed call proves nothing about
    the ICP, so a round with some failures never ends the top-up on its own.

    `spec` (a filters.SearchSpec, or its dict) replaces industries, roles and
    location, which are then ignored. `filters.plan` makes the first pass and
    `filters.top_up(spec, 1, 2, ...)` the top-up rounds (an identical query is
    still never sent twice). Every person is checked with `filters.match_person`
    FIRST — someone outside the filters is not "already pulled" and takes no
    company or industry slot. When a company-level filter is set
    (`filters.needs_company_facts`), each new employer is looked up once per run
    (`_exa_company`, in parallel, only for people who could still be taken, at
    most `max_company_lookups`) and `filters.match_company` checks it before the
    quotas; a company that could not be looked up passes, counted unverified —
    unless a Company HQ filter is set, when its people are turned away as
    "company_hq_unknown" (an unproven HQ might be the excluded one). A company
    found without the headcount or revenue a band asks about passes and is
    counted unverified too.
    `today` is handed to match_person for the tenure filters.

    `stats`, if a dict, gets every one of these keys (0 when unused):
    skipped_seen (distinct people passed over as already pulled), duplicates
    (repeat rows for someone already taken this run), queries_used (every Exa
    call, first pass and top-up), query_errors (calls that failed), extra_queries
    (the top-up calls) and short_by (how far the list fell under `target`).
    With a `spec` it also gets filtered ({REASONS key: distinct people turned
    away}), company_lookups (company calls made) and company_unverified
    (distinct companies met that could not be checked)."""
    from concurrent.futures import ThreadPoolExecutor

    if isinstance(spec, dict):
        spec = filters.SearchSpec.from_dict(spec)
    needs_facts = spec is not None and bool(filters.needs_company_facts(spec))

    leads: list[Lead] = []
    # Identity, not the name: two Rahul Shahs at two companies are two people,
    # and one person reached by two searches (the same profile) is still one.
    seen = SeenIndex()
    passed = SeenIndex()        # already-pulled people met so far, counted once each
    rejected = SeenIndex()      # people outside the filters, counted once each
    filtered: "defaultdict[str, int]" = defaultdict(int)
    facts: dict = {}            # norm_company -> lookup result; None = looked, not found
    unverified: set = set()     # companies met that could not be checked
    lookups = 0
    comp_count: "defaultdict[str, int]" = defaultdict(int)
    ind_count: "defaultdict[str, int]" = defaultdict(int)
    counts = dict.fromkeys(("skipped_seen", "duplicates", "queries_used",
                            "query_errors", "extra_queries"), 0)
    if spec is None:
        grid = queries(industries, roles, location)
        labels = industries
    else:
        grid = [(str(ind), str(q)) for ind, q in (filters.plan(spec) or [])]
        labels = [ind for ind, _ in grid]
    qs = grid[:max(1, max_queries)]
    # Per-industry cap so ONE productive industry can't fill the whole target and
    # starve the rest of the ICP. Each industry may take up to its fair share
    # (target / #industries); later role-passes top up any that came back sparse.
    n_inds = len({i.strip().lower() for i in labels if i.strip()}) or 1
    per_ind = max(per_company * 2, -(-target // n_inds))    # ceil(target / n_inds)

    def _reject(lead: Lead, reason: str) -> None:
        if lead not in rejected:
            rejected.add(lead)
            filtered[reason] += 1

    def _take(ind: str, rows: list, ind_cap: int) -> None:
        ik = ind.lower()
        if ind_count[ik] >= ind_cap:            # this industry has its share — skip
            return
        for r in rows:
            for e in (r.get("entities") or []):
                lead = _lead_of(r, e, ind)
                if lead is None:
                    continue
                company = lead.company
                # Outside the filters: out before everything else. They are not
                # "already pulled", and they must cost no company or industry slot.
                if spec is not None:
                    reason = filters.match_person(spec, lead, e.get("properties") or {},
                                                  today)
                    if reason:
                        _reject(lead, reason)
                        continue
                # Pulled in an earlier session: out before the in-run and quota
                # checks, so they cost this run no company or industry slot.
                if skip is not None and lead in skip:
                    if lead not in passed:
                        passed.add(lead)
                        counts["skipped_seen"] += 1
                    continue
                if lead in seen:
                    counts["duplicates"] += 1
                    continue
                known = None
                if needs_facts:
                    key = norm_company(company)
                    known = facts.get(key)
                    if known is None:           # not found, failed, or past the cap
                        unverified.add(key)
                        if spec.company_hq.active:
                            # An HQ filter is a rule, like a location one: a
                            # company nobody could look up can't be shown to sit
                            # outside an excluded place, so it takes no slot —
                            # else the lookup cap quietly switched the filter off.
                            _reject(lead, "company_hq_unknown")
                            continue
                    else:
                        reason = filters.match_company(spec, lead, known)
                        if reason:
                            _reject(lead, reason)
                            continue
                        if ((spec.headcount and known.get("headcount") is None)
                                or (spec.revenue and known.get("revenue") is None)):
                            # Found, but the size a band asks about is not on
                            # its record: it passed on trust, like a company
                            # never found, and is counted the same way.
                            unverified.add(key)
                if comp_count[company.lower()] >= per_company:   # keep it diverse
                    continue
                if known:
                    if known.get("headcount") is not None:
                        lead.extra["headcount"] = known["headcount"]
                    if known.get("revenue") is not None:
                        lead.extra["revenue"] = known["revenue"]
                    if known.get("hq"):
                        lead.extra["company_hq"] = known["hq"]
                seen.add(lead)
                comp_count[company.lower()] += 1
                ind_count[ik] += 1
                leads.append(lead)
                if len(leads) >= target or ind_count[ik] >= ind_cap:
                    return

    def _look_up(fetched: list, ind_cap: int) -> None:
        """Look up, in parallel and once per run, the employers of the people in
        this batch who could still be taken. Someone already turned away by a
        person filter, already pulled or already on the list would make the
        company's answer buy nothing, so they ask for none."""
        nonlocal lookups
        wanted: dict = {}
        for ind, rows in fetched:
            if not rows or ind_count[ind.lower()] >= ind_cap:
                continue
            for r in rows:
                for e in (r.get("entities") or []):
                    lead = _lead_of(r, e, ind)
                    if lead is None:
                        continue
                    key = norm_company(lead.company)
                    if not key or key in facts or key in wanted:
                        continue
                    if filters.match_person(spec, lead, e.get("properties") or {}, today):
                        continue
                    if (skip is not None and lead in skip) or lead in seen:
                        continue
                    wanted[key] = lead.company
        batch = list(wanted.items())[:max(0, max_company_lookups - lookups)]
        if not batch:
            return
        with ThreadPoolExecutor(max_workers=min(8, len(batch))) as ex:
            found = list(ex.map(lambda kc: _exa_company(kc[1], api_key), batch))
        lookups += len(batch)
        for (key, _), got in zip(batch, found):
            facts[key] = got if isinstance(got, dict) else None

    done, batch_size = 0, 8

    def _batch(batch: list, ind_cap: int, total: int) -> tuple:
        """Fire one parallel batch, then take from the replies in query order.
        Returns (people added, calls failed)."""
        nonlocal done
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            fetched = list(ex.map(
                lambda iq: (iq[0], _exa_people(iq[1], api_key, n=per_query)), batch))
        failed = sum(1 for _, rows in fetched if rows is None)
        counts["queries_used"] += len(fetched)
        counts["query_errors"] += failed
        if needs_facts:
            _look_up(fetched, ind_cap)
        before = len(leads)
        for ind, rows in fetched:
            done += 1
            if rows:
                _take(ind, rows, ind_cap)
            if on_progress:
                on_progress(done, total, ind, len(leads))
            if len(leads) >= target:
                break
        return len(leads) - before, failed

    for start in range(0, len(qs), batch_size):
        if len(leads) >= target:
            break
        _batch(qs[start:start + batch_size], per_ind, len(qs))

    budget = max(0, max_extra_queries)
    wants_more = skip is not None or (spec is not None and _enforces(spec))
    if wants_more and len(leads) < target and budget:
        sent = {_qkey(q) for _, q in qs}
        if spec is None:
            loc = (location or "").strip()
            loc = f" in {loc}" if loc else ""
            candidates = [grid[len(qs):]] + [
                [(ind, tpl.format(role=role, role_alt=_role_alt(role), ind=ind, loc=loc))
                 for role, ind in _pairings(industries, roles)]
                for tpl in _VARIANTS]
        else:
            candidates = [grid[len(qs):]]
            for round_no in range(1, _MAX_TOP_UP_ROUNDS + 1):
                more = [(str(ind), str(q))
                        for ind, q in (filters.top_up(spec, round_no) or [])]
                if not more:
                    break
                candidates.append(more)
        rounds = []
        for cand in candidates:
            fresh = []
            for ind, q in cand:
                if _qkey(q) not in sent:        # a repeat would only repeat its people
                    sent.add(_qkey(q))
                    fresh.append((ind, q))
            if fresh:
                rounds.append(fresh)
        total = len(qs) + min(budget, sum(len(r) for r in rounds))
        dead = 0
        for rnd in rounds:
            added = failed = asked = 0
            for start in range(0, len(rnd), batch_size):
                room = budget - counts["extra_queries"]
                if len(leads) >= target or room <= 0:
                    break
                batch = rnd[start:start + batch_size][:room]
                counts["extra_queries"] += len(batch)
                got, lost = _batch(batch, target, total)
                added, failed, asked = added + got, failed + lost, asked + len(batch)
            if len(leads) >= target or counts["extra_queries"] >= budget:
                break
            if asked and failed == asked:
                # Nothing answered. One such round proves nothing about the ICP;
                # two in a row mean the key or Exa is down — stop paying for it.
                dead += 1
                if dead >= _DEAD_ROUNDS:
                    break
                continue
            dead = 0
            if not added and not failed:        # every call answered, nobody new: exhausted
                break

    result = leads[:target]
    if stats is not None:
        stats.update(counts)
        stats["short_by"] = max(0, target - len(result))
        if spec is not None:
            stats["filtered"] = dict(filtered)
            stats["company_lookups"] = lookups
            stats["company_unverified"] = len(unverified)
    return result
