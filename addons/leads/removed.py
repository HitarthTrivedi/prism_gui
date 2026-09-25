"""
Leads & Outreach — the people taken off the list
────────────────────────────────────────────────
The owner, 23-Sep-2026: ticking people and pressing Clear should take them
off the list. Asked what that means, he chose "Remove from list": they leave
People (Total, Net New and Saved), new searches never bring them back, and
they can be restored. Apollo has nothing like it (its database is not yours
to prune), but Prism's people are the owner's own finds, and one search that
went wrong ("i clicked on load sheet and it started sourcing", 22-Sep) left
dozens nobody wanted with no way to be rid of them.

Nothing is deleted. The sessions and saved contacts they came from stay
exactly as they were, so Restore puts someone back as they stood: their
stage, notes and Activities included. What changes is who is shown:

  · the pool leaves out anyone who shares an identity key with a removed
    person (pool.without; prospector.identity, the rule a search uses to
    skip someone it already pulled);
  · a search skips them before they take a slot (workers._seen_index),
    whatever "Only find people no earlier search found" says;
  · Send all and Export sheets leave them out of the run on screen.

An import that names a removed person brings them back (restore_leads): the
owner picked that sheet, row by row.

One file, removed.json, in a folder the caller names. A record:

    id           the handle Restore asks for
    keys         every identity key the person's records carried
    name, title, company, email, location    what the Removed list shows
    removed_at   ISO time

Rules this module keeps (store.py): Qt-free and path-free; readers forgive,
writers refuse; atomic writes under one module lock; a damaged file is set
aside, a newer one is never written over.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from prospector.identity import keys_of

from addons.leads import store

SCHEMA = 1
FILE = "removed.json"
_KEY = "removed"
_WHAT = "the people you removed"
_TEXT_FIELDS = ("name", "title", "company", "email", "location")

_LOCK = threading.RLock()

StoreError = store.StoreError


@dataclass
class Removed:
    id: str = ""
    keys: frozenset = field(default_factory=frozenset)
    name: str = ""
    title: str = ""
    company: str = ""
    email: str = ""
    location: str = ""
    removed_at: str = ""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value) -> str:
    return " ".join(value.split())[:200] if isinstance(value, str) else ""


def _record(item):
    """A stored row → Removed, or None when it holds no identity key (it
    could never match anyone, so it is not worth keeping)."""
    if not isinstance(item, dict):
        return None
    keys = frozenset(k for k in item.get("keys") or ()
                     if isinstance(k, str) and ":" in k and k.strip() == k)
    if not keys:
        return None
    rid = item.get("id") if isinstance(item.get("id"), str) and item.get("id") else ""
    return Removed(id=rid or uuid.uuid4().hex[:12], keys=keys,
                   **{name: _text(item.get(name)) for name in _TEXT_FIELDS},
                   removed_at=item.get("removed_at")
                   if isinstance(item.get("removed_at"), str) else "")


def _row(record: Removed) -> dict:
    out = {"id": record.id, "keys": sorted(record.keys)}
    out.update({name: getattr(record, name) for name in _TEXT_FIELDS})
    out["removed_at"] = record.removed_at
    return out


def _read(items) -> list:
    return [r for r in (_record(item) for item in items) if r is not None]


def _about(person) -> tuple:
    """(keys, lead) for a pool.Person — every key its records carried — or
    for a bare Lead."""
    lead = getattr(person, "lead", person)
    keys = frozenset(getattr(person, "keys", None) or ()) | keys_of(lead)
    return keys, lead


# ── reading ───────────────────────────────────────────────────────────────────

def list_removed(folder) -> list:
    """Everyone removed, most recently first. Never raises: a missing,
    damaged or newer file lists nobody."""
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        records = _read(items)
    except Exception:                                   # noqa: BLE001
        return []
    records.sort(key=lambda r: r.removed_at, reverse=True)
    return records


def keys(records) -> frozenset:
    """Every key the removed people carry: who the pool and a search leave out."""
    out: set = set()
    for record in records or ():
        out |= record.keys
    return frozenset(out)


# ── writing ───────────────────────────────────────────────────────────────────

def remove(folder, people) -> list:
    """Take these people off the list; return the ids of their records (what
    Undo restores). Someone who shares a key with a person removed before
    joins that record rather than making a second. Raises StoreError when the
    file cannot be written."""
    doing = "Couldn't remove these people"
    ids: list = []
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records = _read(items)
        now = _now()
        for person in people or ():
            person_keys, lead = _about(person)
            if not person_keys:
                continue
            hit = next((r for r in records if not r.keys.isdisjoint(person_keys)), None)
            if hit is None:
                hit = Removed(id=uuid.uuid4().hex[:12], keys=person_keys,
                              **{name: _text(getattr(lead, name, "")) for name in
                                 ("name", "title", "company", "email")},
                              location=_text((getattr(lead, "extra", None) or {})
                                             .get("location")),
                              removed_at=now)
                records.append(hit)
            else:
                hit.keys = hit.keys | person_keys
                hit.removed_at = now
            if hit.id not in ids:
                ids.append(hit.id)
        if ids:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(r) for r in records])
    return ids


def restore(folder, ids) -> int:
    """Put these people back on the list; return how many. Raises StoreError
    when the file cannot be written."""
    wanted = {i for i in ids or () if isinstance(i, str) and i}
    if not wanted:
        return 0
    doing = "Couldn't restore these people"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        records = _read(items)
        kept = [r for r in records if r.id not in wanted]
        gone = len(records) - len(kept)
        if gone:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(r) for r in kept])
    return gone


def restore_leads(folder, leads) -> int:
    """Put back anyone these leads name — an import of a removed person.
    Never raises into an import: a failed write leaves them removed."""
    named: set = set()
    for lead in leads or ():
        named |= keys_of(lead)
    if not named:
        return 0
    try:
        ids = [r.id for r in list_removed(folder) if not r.keys.isdisjoint(named)]
        return restore(folder, ids)
    except Exception:                                   # noqa: BLE001
        return 0
