"""
Leads & Outreach — CSV imports (Apollo's "Contact CSV import" / "Account CSV import")
─────────────────────────────────────────────────────────────────────────────────────
In Apollo, importing a sheet is its own action — People or Companies > Import >
CSV — and every import is kept by its file name, so it can come back later as
a FILTER: "Click Account CSV import or Contact CSV import > then check one or
more CSV import file names. Apollo updates your search results based on the
imports you selected." This store is the list those filters pick from.

One file, imports.json, in a folder the caller names. Two kinds, as in Apollo:

  · "contacts" — people. The people themselves are saved as contacts
    (contacts.py), each tagged with this import's id; the record here keeps
    what the import WAS — its file, the column mapping, the settings, the
    counts — and the Contact CSV import filter asks contacts.py who carries
    the tag.
  · "accounts" — companies. They are saved as accounts (accounts.py), and the
    record keeps its own copy too, each as {"name", "website", "domain",
    "location", "industry", "headcount", …}: the Account CSV import filter
    keeps people who work at one of them, and a paid search walks them in
    order to find people there (mark_searched).

A record: {"id", "name" (the file's name, what the filter shows), "kind",
"created_at", "source" (the path it was read from — shown, never re-read),
"sheet" (the tab, for a workbook), "mapping" ({column header: field}),
"settings", "counts" ({"rows", "added", "updated", "skipped"}), and for
accounts "companies" and "searched" — how many of those companies, in order,
a paid search has already asked for people at (mark_searched). Kept here, not
in memory: a restart that forgot it would spend the same searches on the same
companies again.

Rules this module keeps (store.py): Qt-free and path-free; readers forgive,
writers refuse; atomic writes under one module lock; a damaged file is set
aside, a newer one is never written over.
"""
from __future__ import annotations

import re
import secrets
import threading
from datetime import datetime
from urllib.parse import urlsplit

from prospector.identity import norm_company

from addons.leads import store

SCHEMA = 1
FILE = "imports.json"
_KEY = "imports"
_WHAT = "your CSV imports"
KINDS = ("contacts", "accounts")
_ID = re.compile(r"imp-\d{8}-\d{6}-[0-9a-f]{6}")
_COMPANY_FIELDS = ("name", "website", "domain", "location", "industry",
                   "headcount", "phone", "linkedin", "stage", "revenue",
                   "description")
_COUNT_KEYS = ("rows", "added", "updated", "skipped")

_LOCK = threading.RLock()

StoreError = store.StoreError


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_id(taken) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    while True:
        candidate = f"imp-{stamp}-{secrets.token_hex(3)}"
        if candidate not in taken:
            return candidate


def valid_id(value) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


# A real host: dot-separated labels, and a last label of letters ("acme.example",
# "idmc.company") — so "Not Found", "N/A", "localhost" and "192.168.0.1" are not one.
_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}")


def domain_of(website) -> str:
    """"https://www.acme.example/about" → "acme.example"; "" when there is no
    host — or when what is there is not a web address at all. The same reduction
    a company's e-mail domain gets in pool.py, so a person at @acme.example is at
    the account whose website is acme.example.

    The last rule is not a nicety (24-Sep-2026): the owner's AE _ Leads.xlsx had
    "Not Found" in 115 website cells and "Not available" in 19 more, "Not Found"
    read as the domain "not found", and every company after the first was
    dropped as a duplicate of it — 215 rows imported as 74 companies."""
    raw = (website if isinstance(website, str) else "").strip().lower()
    if not raw:
        return ""
    if "@" in raw and "/" not in raw:          # an address, not a site
        raw = raw.split("@", 1)[1]
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return ""
    host = host[4:] if host.startswith("www.") else host
    return host if _HOST.fullmatch(host) else ""


def _text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _company(item):
    """A stored or incoming company → the clean dict, or None when it names no
    company at all (no name and no website)."""
    if not isinstance(item, dict):
        return None
    out = {k: _text(item.get(k)) for k in _COMPANY_FIELDS}
    if not out["domain"]:
        out["domain"] = domain_of(out["website"])
    if not (out["name"] or out["domain"]):
        return None
    # The sheet's own columns the owner kept ("Why they outsource?", "Lead
    # quality" …) — research, not noise; kept verbatim, strings only.
    custom = item.get("custom")
    if isinstance(custom, dict):
        kept = {str(k).strip(): _text(v) for k, v in custom.items()
                if str(k).strip() and _text(v)}
        if kept:
            out["custom"] = kept
    return out


def _counts(value) -> dict:
    src = value if isinstance(value, dict) else {}
    out = {}
    for key in _COUNT_KEYS:
        v = src.get(key)
        out[key] = v if type(v) is int and v >= 0 else 0
    return out


def _normal(item):
    """A stored row → the record, or None when it is not an import this build
    can list."""
    if not isinstance(item, dict) or not valid_id(item.get("id")):
        return None
    kind = item.get("kind")
    name = _text(item.get("name"))
    if kind not in KINDS or not name:
        return None
    mapping = item.get("mapping") if isinstance(item.get("mapping"), dict) else {}
    record = {
        "id": item["id"], "name": name, "kind": kind,
        "created_at": item.get("created_at") if isinstance(item.get("created_at"), str) else "",
        "source": _text(item.get("source")), "sheet": _text(item.get("sheet")),
        "mapping": {str(k): str(v) for k, v in mapping.items()
                    if isinstance(v, str)},
        "settings": item.get("settings") if isinstance(item.get("settings"), dict) else {},
        "counts": _counts(item.get("counts")),
    }
    if kind == "accounts":
        companies = []
        for c in item.get("companies") if isinstance(item.get("companies"), list) else ():
            clean = _company(c)
            if clean is not None:
                companies.append(clean)
        record["companies"] = companies
        searched = item.get("searched")
        record["searched"] = (min(searched, len(companies))
                              if type(searched) is int and searched > 0 else 0)
    return record


def _split(items) -> tuple:
    """(records, kept): the imports this build can list, newest first, and
    every other OBJECT in the file exactly as it was — a record with its id
    mistyped by a hand edit is still the owner's data, and a write puts it
    back after the records rather than dropping it (saved_searches.py's
    rule). Anything that is not an object holds nothing and is dropped."""
    out, kept, seen = [], [], set()
    for item in items:
        try:
            record = _normal(item)
        except Exception:                               # noqa: BLE001
            record = None
        if record is not None and record["id"] not in seen:
            seen.add(record["id"])
            out.append(record)
        elif isinstance(item, dict):
            kept.append(item)
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out, kept


def _records(items) -> list:
    return _split(items)[0]


def _header(record: dict) -> dict:
    """The record without its (possibly long) company list, plus how many."""
    out = {k: v for k, v in record.items() if k != "companies"}
    if record["kind"] == "accounts":
        out["n_companies"] = len(record.get("companies") or ())
    return out


# ── reading ───────────────────────────────────────────────────────────────────

def list_imports(folder, kind: str = "") -> list:
    """Every import's header, newest first — optionally only one kind. Never
    raises: a missing, damaged or newer file lists nothing."""
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        records = _records(items)
    except Exception:                                   # noqa: BLE001
        return []
    return [_header(r) for r in records if not kind or r["kind"] == kind]


def get(folder, import_id):
    """One whole record (companies included), or None."""
    if not valid_id(import_id):
        return None
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        for record in _records(items):
            if record["id"] == import_id:
                return record
    except Exception:                                   # noqa: BLE001
        pass
    return None


def companies_of(folder, import_ids) -> dict:
    """{import id: [company dict, …]} for the accounts imports among the ids —
    what the Account CSV import filter resolves. An id that is not an accounts
    import is left out. Never raises."""
    wanted = {i for i in import_ids or () if valid_id(i)}
    if not wanted:
        return {}
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        return {r["id"]: list(r.get("companies") or ())
                for r in _records(items)
                if r["id"] in wanted and r["kind"] == "accounts"}
    except Exception:                                   # noqa: BLE001
        return {}


def company_keys(companies) -> tuple:
    """(names, domains) — the normalised company names and web domains of a
    company list, what a person's company and e-mail are checked against."""
    names, domains = set(), set()
    for c in companies or ():
        n = norm_company(c.get("name", ""))
        if n:
            names.add(n)
        d = c.get("domain") or domain_of(c.get("website", ""))
        if d:
            domains.add(d)
    return frozenset(names), frozenset(domains)


def label(header: dict) -> str:
    """What a filter row shows beside the file name: "3 contacts · 22 Sep",
    "193 companies · 50 searched · 22 Sep"."""
    counts = header.get("counts") or {}
    if header.get("kind") == "accounts":
        n = header.get("n_companies", len(header.get("companies") or ()))
        what = "1 company" if n == 1 else f"{n} companies"
        searched = header.get("searched") or 0
        if searched:
            what += " · all searched" if searched >= n else f" · {searched} searched"
    else:
        n = counts.get("added", 0) + counts.get("updated", 0)
        what = "1 contact" if n == 1 else f"{n} contacts"
    when = ""
    try:
        when = datetime.fromisoformat(header.get("created_at", "")).strftime("%d %b")
    except (TypeError, ValueError):
        pass
    return f"{what} · {when}" if when else what


# ── writing ───────────────────────────────────────────────────────────────────

def create(folder, *, name: str, kind: str, source: str = "", sheet: str = "",
           mapping=None, settings=None, counts=None, companies=()) -> dict:
    """Record a new import; return its header. `companies` only for kind
    "accounts" (cleaned: a row naming no company and no website is dropped,
    the same company twice — by name or domain — kept once). Raises
    StoreError when the file can't be written, ValueError on a bad call."""
    if kind not in KINDS:
        raise ValueError(f"unknown import kind {kind!r}")
    name = _text(name)
    if not name:
        raise ValueError("an import needs a name")
    doing = "Couldn't record this import"
    record = {
        "name": name, "kind": kind, "created_at": _now(),
        "source": _text(source), "sheet": _text(sheet),
        "mapping": {str(k): str(v) for k, v in (mapping or {}).items()
                    if isinstance(v, str)},
        "settings": dict(settings or {}), "counts": _counts(counts),
    }
    if kind == "accounts":
        clean, seen_names, seen_domains = [], set(), set()
        for c in companies or ():
            c = _company(c)
            if c is None:
                continue
            n, d = norm_company(c["name"]), c["domain"]
            if (n and n in seen_names) or (d and d in seen_domains):
                continue
            seen_names.add(n)
            seen_domains.add(d)
            clean.append(c)
        record["companies"] = clean
        record["searched"] = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records, kept = _split(items)
        record["id"] = _new_id({r["id"] for r in records})
        records.insert(0, record)
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                     records + kept)
    return _header(record)


def update_counts(folder, import_id, counts) -> bool:
    """Replace one import's counts — a contacts import only knows how many it
    added and updated once contacts.save() has run, which needs the id this
    record was given first. Raises StoreError when the file can't be written."""
    if not valid_id(import_id):
        return False
    doing = "Couldn't record this import"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records, kept = _split(items)
        for record in records:
            if record["id"] == import_id:
                record["counts"] = _counts(counts)
                store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                             records + kept)
                return True
    return False


def set_companies(folder, import_id, companies) -> bool:
    """Replace an accounts import's companies — what an enrichment pass found
    (a website, a size, an HQ) written back, in the same order, so the
    Account CSV import filter can match by the domains it learned and the
    searched position still points at the same companies. False when there
    is no such accounts import. Raises StoreError on a failed write."""
    if not valid_id(import_id):
        return False
    clean = [c for c in (_company(c) for c in companies or ()) if c is not None]
    doing = "Couldn't update this import's companies"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records, kept = _split(items)
        for record in records:
            if record["id"] == import_id and record["kind"] == "accounts":
                record["companies"] = clean
                record["searched"] = min(record.get("searched", 0), len(clean))
                store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                             records + kept)
                return True
    return False


def mark_searched(folder, import_id, upto: int) -> bool:
    """Record that a paid search has asked for people at this accounts
    import's companies up to `upto` (a count, from the first, clamped to the
    list) — 0 starts it over. False when there is no such accounts import.
    Raises StoreError when the file can't be written."""
    if not valid_id(import_id) or type(upto) is not int:
        return False
    doing = "Couldn't record how far this import has been searched"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records, kept = _split(items)
        for record in records:
            if record["id"] == import_id and record["kind"] == "accounts":
                record["searched"] = max(0, min(upto, len(record["companies"])))
                store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                             records + kept)
                return True
    return False


def delete(folder, import_id) -> bool:
    """Forget one import. The caller also calls contacts.untag_import for a
    contacts import. Raises StoreError when the file can't be written."""
    if not valid_id(import_id):
        return False
    doing = "Couldn't delete this import"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records, kept = _split(items)
        left = [r for r in records if r["id"] != import_id]
        if len(left) == len(records):
            return False
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state, left + kept)
    return True
