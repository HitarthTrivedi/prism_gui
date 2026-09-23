"""
Leads & Outreach — saved contacts (Apollo's "Saved")
────────────────────────────────────────────────────
Apollo's Find People splits every result three ways — Total, Net New, Saved —
and Saved is a real store, not a filter: the people you import from a CSV,
save, export or put in a sequence become CONTACTS in your workspace, and "Net
New" is everyone a search turns up who is not one yet. (Apollo's own words:
"Adding prospects to a sequence saves them as contacts"; "When you export
prospects, Apollo also saves them as contacts in your account".) Prism had no
such store — sessions remember what a run pulled, lists are files you export —
so this is it.

One file, contacts.json, in a folder the caller names. A contact is a Lead,
written exactly as a session writes one (sessions.lead_to_row), plus how it
got here:

    saved_at    when it was first saved (kept on every later save)
    updated_at  when a save last changed it
    via         how, in the order it happened: "import", "save", "export",
                "sequence", "list", "email"
    imports     ids of the Contact CSV imports that brought it in — what the
                "Contact CSV import" filter reads (see imports.py)

One person, one contact: a lead whose identity keys (prospector.identity —
e-mail, profile link, Apollo id, name + company) touch a saved contact's is
THAT contact, tagged again rather than saved twice. Apollo's import setting
"If contacts already exist" is `update`: True writes the incoming non-empty
fields over the saved ones ("Update the existing record"); False leaves the
record as it is and only adds the tag.

Rules this module keeps — the ones sessions.py and saved_searches.py keep, via
store.py: Qt-free and path-free; readers forgive, writers refuse; writes are
atomic, every read-modify-write holds the module lock; a damaged file is set
aside, a newer one is never written over.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from prospector.identity import keys_of
from prospector.models import Lead

from addons.leads import store
from addons.leads.sessions import lead_from_row, lead_to_row

SCHEMA = 1
FILE = "contacts.json"
_KEY = "contacts"
_WHAT = "your saved contacts"
VIA = ("import", "save", "export", "sequence", "list", "email")

_LOCK = threading.RLock()

StoreError = store.StoreError


@dataclass
class Contact:
    lead: Lead
    saved_at: str = ""
    updated_at: str = ""
    via: list = field(default_factory=list)
    imports: list = field(default_factory=list)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _strings(value) -> list:
    """A list of distinct non-empty strings, in order; anything else → []."""
    out = []
    for item in value if isinstance(value, list) else ():
        if isinstance(item, str) and item.strip() and item not in out:
            out.append(item.strip())
    return out


def _contact(item):
    """A stored row → Contact, or None for a row that holds no person."""
    if not isinstance(item, dict):
        return None
    lead = lead_from_row(item.get("lead"))
    if lead is None or not keys_of(lead):
        return None
    return Contact(
        lead=lead,
        saved_at=item.get("saved_at") if isinstance(item.get("saved_at"), str) else "",
        updated_at=item.get("updated_at") if isinstance(item.get("updated_at"), str) else "",
        via=[v for v in _strings(item.get("via")) if v in VIA],
        imports=_strings(item.get("imports")))


def _row(contact: Contact) -> dict:
    return {"lead": lead_to_row(contact.lead), "saved_at": contact.saved_at,
            "updated_at": contact.updated_at, "via": list(contact.via),
            "imports": list(contact.imports)}


def _read_contacts(items) -> list:
    return [c for c in (_contact(item) for item in items) if c is not None]


# ── reading ───────────────────────────────────────────────────────────────────

def list_contacts(folder) -> list:
    """Every saved contact, most recently saved first. Never raises: a missing,
    damaged or newer file lists nothing."""
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        contacts = _read_contacts(items)
    except Exception:                                   # noqa: BLE001
        return []
    contacts.sort(key=lambda c: c.saved_at, reverse=True)
    return contacts


def saved_keys(folder) -> frozenset:
    """Every identity key of every saved contact — what splits a result into
    Net New and Saved (see pool.py). Never raises."""
    keys = set()
    for contact in list_contacts(folder):
        keys.update(keys_of(contact.lead))
    return frozenset(keys)


# ── writing ───────────────────────────────────────────────────────────────────

def merge(saved: Lead, incoming: Lead) -> bool:
    """Write incoming's non-empty fields over saved's — Apollo's "Update the
    existing record". Returns whether anything changed. `extra` merges key by
    key; the fit/triage fields are left alone (they describe a run, not the
    person)."""
    changed = False
    for name in ("name", "title", "company", "email", "phone", "industry"):
        value = getattr(incoming, name, "") or ""
        if isinstance(value, str) and value.strip() and value != getattr(saved, name):
            setattr(saved, name, value)
            changed = True
    for key, value in (incoming.extra or {}).items():
        if value not in (None, "", [], {}) and saved.extra.get(key) != value:
            saved.extra[key] = value
            changed = True
    return changed


def save(folder, leads, *, via: str, import_id: str = "", update: bool = False) -> dict:
    """Save people as contacts; return {"added": n, "updated": n, "tagged": n}.

    A lead that is already a contact (any shared identity key) gets `via` —
    and `import_id`, when given — added to its record; with `update` its
    non-empty fields are written over the saved ones too. A lead with no
    identity key at all (no e-mail, no profile, no name AND company) cannot
    be told apart from anyone and is skipped. Raises StoreError when the file
    cannot be written; nothing is then saved."""
    if via not in VIA:
        raise ValueError(f"unknown via {via!r}")
    doing = "Couldn't save these contacts"
    added = updated = tagged = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        by_key = {}
        for i, contact in enumerate(contacts):
            for key in keys_of(contact.lead):
                by_key.setdefault(key, i)
        now = _now()
        for lead in leads or ():
            if lead is None:
                continue
            keys = keys_of(lead)
            if not keys:
                continue
            at = next((by_key[k] for k in keys if k in by_key), None)
            if at is None:
                contact = Contact(lead=_copy(lead), saved_at=now, updated_at=now,
                                  via=[via], imports=[import_id] if import_id else [])
                contacts.append(contact)
                at = len(contacts) - 1
                added += 1
            else:
                contact = contacts[at]
                changed = update and merge(contact.lead, lead)
                if via not in contact.via:
                    contact.via.append(via)
                    changed = True
                if import_id and import_id not in contact.imports:
                    contact.imports.append(import_id)
                    changed = True
                if changed:
                    contact.updated_at = now
                    if update:
                        updated += 1
                    else:
                        tagged += 1
            # The merged record may carry keys the incoming lead did not.
            for key in keys_of(contacts[at].lead) | keys:
                by_key.setdefault(key, at)
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                     [_row(c) for c in contacts])
    return {"added": added, "updated": updated, "tagged": tagged}


def _copy(lead: Lead) -> Lead:
    """A contact holds its own copy: the run that found the person goes on
    mutating its Lead (verify, enrich), and the saved record must change only
    when it is saved again."""
    return lead_from_row(lead_to_row(lead))


def remove(folder, leads) -> int:
    """Delete the contacts these leads are (by any shared identity key);
    return how many were removed. Raises StoreError when the file cannot be
    written."""
    doing = "Couldn't remove these contacts"
    gone = set()
    for lead in leads or ():
        if lead is not None:
            gone.update(keys_of(lead))
    if not gone:
        return 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        kept = [c for c in contacts if keys_of(c.lead).isdisjoint(gone)]
        if len(kept) != len(contacts):
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(c) for c in kept])
    return len(contacts) - len(kept)


def untag_import(folder, import_id: str) -> int:
    """Forget one Contact CSV import on every contact that carries it — the
    import itself was deleted (imports.delete). A contact that came in ONLY
    through that import and was never saved any other way goes with it,
    matching Apollo's "delete the import and start over"; one saved again
    since (exported, sequenced, saved by hand) stays. Returns how many
    contacts were removed."""
    doing = "Couldn't remove that import's contacts"
    if not import_id:
        return 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        kept, removed, changed = [], 0, False
        for c in contacts:
            if import_id not in c.imports:
                kept.append(c)
                continue
            changed = True
            c.imports = [i for i in c.imports if i != import_id]
            if not c.imports and set(c.via) <= {"import"}:
                removed += 1
                continue
            kept.append(c)
        if changed:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(c) for c in kept])
    return removed
