"""
Leads & Outreach — saved accounts (Apollo's companies you keep)
───────────────────────────────────────────────────────────────
Apollo keeps ACCOUNTS — companies — beside its contacts: an Account CSV import
creates them, a contacts import can "Assign/create account based on
Website/Email Domain in the CSV", and a person's panel shows the account they
work at, with its stage. Prism kept companies only on the account-import record
(imports.py, which still drives the Account CSV import filter and the paid
search's batches); this is the store the person panel — and the Companies page
after it — reads.

One file, accounts.json, in a folder the caller names. An account:

    name, domain, website, location, industry, headcount, revenue, phone,
    linkedin, description      what is known about the company
    custom                     the sheet's own columns, kept verbatim
    stage                      Apollo's account stages (STAGES), "Cold" to start
    saved_at, updated_at       first saved; last changed
    via                        "import", "contact", "save", "enrich"
    imports                    the Account CSV imports that brought it in
    lists                      the lists it was added to

One company, one account: the same web domain, or — where either side has no
domain — the same name once legal words are dropped (prospector.identity.
norm_company: "Acme Pvt. Ltd." is "Acme"). A free-mail domain (gmail.com …) is
nobody's company and never makes or matches an account.

Rules this module keeps (store.py): Qt-free and path-free; readers forgive,
writers refuse; atomic writes under one module lock; a damaged file is set
aside, a newer one is never written over.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, fields
from datetime import datetime

from prospector.identity import norm_company

from addons.leads import store
from addons.leads.imports import domain_of

SCHEMA = 1
FILE = "accounts.json"
_KEY = "accounts"
_WHAT = "your saved accounts"
VIA = ("import", "contact", "save", "enrich")
# Apollo's default account stages, in its order (knowledge.apollo.io, "Contact
# and Account Stages Overview", read 23-Sep-2026). A stage an imported sheet
# names that is not one of these is kept as written (stage_named).
STAGES = ("Cold", "Current Client", "Active Opportunity", "Dead Opportunity",
          "Do Not Prospect")
DEFAULT_STAGE = "Cold"
# Mailboxes anyone can open: an address there says nothing about an employer.
FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in",
    "ymail.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "aol.com", "rediffmail.com", "protonmail.com",
    "proton.me", "zoho.com", "gmx.com", "mail.com", "yandex.com",
})
_TEXT_FIELDS = ("name", "domain", "website", "location", "industry", "headcount",
                "revenue", "phone", "linkedin", "description")

_LOCK = threading.RLock()

StoreError = store.StoreError


@dataclass
class Account:
    name: str = ""
    domain: str = ""
    website: str = ""
    location: str = ""
    industry: str = ""
    headcount: str = ""
    revenue: str = ""
    phone: str = ""
    linkedin: str = ""
    description: str = ""
    custom: dict = field(default_factory=dict)
    stage: str = DEFAULT_STAGE
    saved_at: str = ""
    updated_at: str = ""
    via: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    lists: list = field(default_factory=list)

    def keys(self) -> set:
        return company_keys(self.name, self.domain or self.website)


_ACCOUNT_FIELDS = tuple(f.name for f in fields(Account))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = f"{value:g}"
    return " ".join(value.split()) if isinstance(value, str) else ""


def _strings(value) -> list:
    out = []
    for item in value if isinstance(value, list) else ():
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def stage_named(text) -> str:
    """One of STAGES matched without regard to case or spacing, else the text
    itself tidied, else ""."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for known in STAGES:
        if known.casefold() == cleaned.casefold():
            return known
    return cleaned[:60]


def company_domain(website_or_email) -> str:
    """The web domain a website or an e-mail address points at — "" for none,
    and "" for a free-mail provider, which is nobody's company."""
    host = domain_of(website_or_email)
    return "" if host in FREE_MAIL else host


def company_keys(name, website="") -> set:
    """{"d:<domain>", "n:<name>"} — what one company is known by."""
    out = set()
    domain = company_domain(website)
    if domain:
        out.add("d:" + domain)
    n = norm_company(name)
    if n:
        out.add("n:" + n)
    return out


def _account(item):
    """A stored row or an incoming company dict → Account, or None when it
    names no company at all."""
    if not isinstance(item, dict):
        return None
    values = {k: _text(item.get(k)) for k in _TEXT_FIELDS}
    if not values["domain"]:
        values["domain"] = company_domain(values["website"])
    else:
        values["domain"] = company_domain(values["domain"])
    if not (values["name"] or values["domain"]):
        return None
    custom = item.get("custom")
    custom = ({str(k).strip(): _text(v) for k, v in custom.items()
               if str(k).strip() and _text(v)} if isinstance(custom, dict) else {})
    return Account(
        **values, custom=custom,
        stage=stage_named(item.get("stage")) or DEFAULT_STAGE,
        saved_at=item.get("saved_at") if isinstance(item.get("saved_at"), str) else "",
        updated_at=item.get("updated_at") if isinstance(item.get("updated_at"), str) else "",
        via=[v for v in _strings(item.get("via")) if v in VIA],
        imports=_strings(item.get("imports")), lists=_strings(item.get("lists")))


def _row(account: Account) -> dict:
    return {name: (dict(value) if isinstance(value, dict) else
                   list(value) if isinstance(value, list) else value)
            for name, value in ((n, getattr(account, n)) for n in _ACCOUNT_FIELDS)}


def _read_accounts(items) -> list:
    return [a for a in (_account(item) for item in items) if a is not None]


# ── reading ───────────────────────────────────────────────────────────────────

def list_accounts(folder) -> list:
    """Every saved account, most recently saved first. Never raises: a
    missing, damaged or newer file lists nothing."""
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        accounts = _read_accounts(items)
    except Exception:                                   # noqa: BLE001
        return []
    accounts.sort(key=lambda a: a.saved_at, reverse=True)
    return accounts


class Index:
    """Saved accounts, looked up by person many times over: the People page
    asks once per person on every filter change, so each account's keys are
    worked out once here, not on every ask. `match` is match()'s rule."""

    def __init__(self, accounts=()):
        self.accounts = list(accounts or ())
        self._by_domain: dict = {}
        self._by_name: dict = {}
        for account in self.accounts:
            for key in account.keys():
                into = self._by_domain if key.startswith("d:") else self._by_name
                into.setdefault(key, account)

    def match(self, lead):
        if lead is None:
            return None
        extra = getattr(lead, "extra", None) or {}
        for source in (getattr(lead, "email", ""), extra.get("website", "")):
            domain = company_domain(source)
            if domain and "d:" + domain in self._by_domain:
                return self._by_domain["d:" + domain]
        name = norm_company(getattr(lead, "company", ""))
        return self._by_name.get("n:" + name) if name else None


def match(accounts, lead):
    """The saved account a person works at — by the domain of their e-mail or
    their company's website first, then by their company's name — or None.
    For many people, build one Index and ask it."""
    return Index(accounts).match(lead)


def from_lead(lead, by: str = "domain") -> dict | None:
    """The company a person works at, as a company dict to save — Apollo's
    contact-import "Assign/create account". `by` "domain" needs a website or
    a company e-mail domain (the name rides along); "name" needs only the
    company's name. None when the person gives nothing to go on."""
    extra = getattr(lead, "extra", None) or {}
    name = _text(getattr(lead, "company", ""))
    website = _text(extra.get("website", ""))
    domain = company_domain(website) or company_domain(getattr(lead, "email", ""))
    if by == "domain" and not domain:
        return None
    if by == "name" and not name:
        return None
    return {"name": name, "website": website or domain, "domain": domain,
            "industry": _text(getattr(lead, "industry", "")),
            "headcount": _text(extra.get("headcount", ""))}


# ── writing ───────────────────────────────────────────────────────────────────

def _merge(saved: Account, incoming: Account) -> bool:
    """Write incoming's non-empty fields over saved's — "Update the existing
    record with information from CSV"."""
    changed = False
    for name in _TEXT_FIELDS:
        value = getattr(incoming, name)
        if value and value != getattr(saved, name):
            setattr(saved, name, value)
            changed = True
    for key, value in incoming.custom.items():
        if value and saved.custom.get(key) != value:
            saved.custom[key] = value
            changed = True
    return changed


def save(folder, companies, *, via: str, import_id: str = "", update: bool = False,
         stage_of=None, list_name: str = "") -> dict:
    """Save companies as accounts; return {"added", "updated", "tagged"}.

    A company that is already an account (same domain, or same name where a
    domain is missing) gets `via` and `import_id` added; with `update` its
    non-empty fields are written over the saved ones — and a stage from
    `stage_of(company)` taken — too. A new account takes `stage_of(company)`
    or DEFAULT_STAGE. Raises StoreError when the file cannot be written."""
    if via not in VIA:
        raise ValueError(f"unknown via {via!r}")
    doing = "Couldn't save these accounts"
    added = updated = tagged = 0
    list_name = " ".join(str(list_name or "").split())
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        accounts = _read_accounts(items)
        by_key = {}
        for i, account in enumerate(accounts):
            for key in account.keys():
                by_key.setdefault(key, i)
        now = _now()
        for company in companies or ():
            incoming = _account(company)
            if incoming is None:
                continue
            keys = incoming.keys()
            stage = stage_named(stage_of(company)) if stage_of is not None else ""
            domain_keys = {k for k in keys if k.startswith("d:")}
            at = next((by_key[k] for k in domain_keys if k in by_key), None)
            if at is None:
                # By name only when one side has no domain: two companies with
                # different websites are two companies, whatever they are called.
                for k in keys - domain_keys:
                    hit = by_key.get(k)
                    if hit is not None and (not domain_keys or not accounts[hit].domain):
                        at = hit
                        break
            if at is None:
                incoming.stage = stage or DEFAULT_STAGE
                incoming.saved_at = incoming.updated_at = now
                incoming.via = [via]
                incoming.imports = [import_id] if import_id else []
                incoming.lists = [list_name] if list_name else []
                accounts.append(incoming)
                at = len(accounts) - 1
                added += 1
            else:
                account = accounts[at]
                changed = update and _merge(account, incoming)
                if via not in account.via:
                    account.via.append(via)
                    changed = True
                if import_id and import_id not in account.imports:
                    account.imports.append(import_id)
                    changed = True
                if update and stage and stage != account.stage:
                    account.stage = stage
                    changed = True
                if list_name and list_name not in account.lists:
                    account.lists.append(list_name)
                    changed = True
                if changed:
                    account.updated_at = now
                    if update:
                        updated += 1
                    else:
                        tagged += 1
            for key in accounts[at].keys() | keys:
                by_key.setdefault(key, at)
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                     [_row(a) for a in accounts])
    return {"added": added, "updated": updated, "tagged": tagged}


def set_stage(folder, account: Account, stage: str) -> bool:
    """Move a saved account to another stage. False when there is no such
    account or it is already there. Raises StoreError on a failed write."""
    stage = stage_named(stage)
    keys = account.keys() if isinstance(account, Account) else set()
    if not (stage and keys):
        return False
    doing = "Couldn't change this account's stage"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        accounts = _read_accounts(items)
        for saved in accounts:
            if saved.keys() & keys:
                if saved.stage == stage:
                    return False
                saved.stage = stage
                saved.updated_at = _now()
                store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                             [_row(a) for a in accounts])
                return True
    return False
