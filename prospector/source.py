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
"""
from __future__ import annotations

from collections import defaultdict

from .models import Lead

EXA_SEARCH_URL = "https://api.exa.ai/search"


def _exa_people(query: str, api_key: str, n: int = 50, timeout: int = 60) -> list:
    import requests  # lazy, like the rest of the engine
    try:
        r = requests.post(
            EXA_SEARCH_URL,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "category": "people", "type": "auto",
                  "numResults": n}, timeout=timeout)
        return r.json().get("results", []) if r.status_code == 200 else []
    except Exception:                                   # noqa: BLE001 — network is a status line
        return []


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
    inds = [i.strip() for i in industries if i.strip()]
    rols = [r.strip() for r in roles if r.strip()]
    out = []
    for role in rols:
        for ind in inds:
            out.append((ind, f"{role} at {where}{ind} companies and manufacturers"))
    return out


def source(industries: list, roles: list, api_key: str, *, location: str = "India",
           target: int = 300, per_company: int = 3, per_query: int = 50,
           max_queries: int = 30, on_progress=None) -> list[Lead]:
    """A deduped, company-diverse list of real people across the ICP.

    Runs the industry×role searches in PARALLEL batches (so a wide ICP doesn't
    feel like a hang), stops the moment `target` is reached, and never fires more
    than `max_queries` Exa calls however large the industries×roles grid is — a
    big matrix (11×10 = 110 pairings) must not quietly burn the key one slow
    sequential request at a time. `target` and `max_queries` are the two guards."""
    from concurrent.futures import ThreadPoolExecutor

    leads: list[Lead] = []
    seen: set = set()
    comp_count: "defaultdict[str, int]" = defaultdict(int)
    ind_count: "defaultdict[str, int]" = defaultdict(int)
    qs = queries(industries, roles, location)[:max(1, max_queries)]
    # Per-industry cap so ONE productive industry can't fill the whole target and
    # starve the rest of the ICP. Each industry may take up to its fair share
    # (target / #industries); later role-passes top up any that came back sparse.
    n_inds = len({i.strip().lower() for i in industries if i.strip()}) or 1
    per_ind = max(per_company * 2, -(-target // n_inds))    # ceil(target / n_inds)

    def _take(ind: str, rows: list) -> None:
        ik = ind.lower()
        if ind_count[ik] >= per_ind:            # this industry has its share — skip
            return
        for r in rows:
            for e in (r.get("entities") or []):
                if e.get("type") != "person":
                    continue
                p = e.get("properties") or {}
                name = (p.get("name") or "").strip()
                title, company, since = _current_job(p)
                key = name.lower()
                if not (name and company and title) or key in seen:
                    continue
                if comp_count[company.lower()] >= per_company:   # keep it diverse
                    continue
                seen.add(key)
                comp_count[company.lower()] += 1
                ind_count[ik] += 1
                lead = Lead(name=name, title=title, company=company, industry=ind)
                lead.extra["location"] = p.get("location", "")
                lead.extra["since"] = since
                lead.extra["linkedin"] = r.get("url", "")
                leads.append(lead)
                if len(leads) >= target or ind_count[ik] >= per_ind:
                    return

    done, batch_size = 0, 8
    for start in range(0, len(qs), batch_size):
        if len(leads) >= target:
            break
        batch = qs[start:start + batch_size]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            fetched = list(ex.map(
                lambda iq: (iq[0], _exa_people(iq[1], api_key, n=per_query)), batch))
        for ind, rows in fetched:
            done += 1
            _take(ind, rows)
            if on_progress:
                on_progress(done, len(qs), ind, len(leads))
            if len(leads) >= target:
                break
    return leads[:target]
