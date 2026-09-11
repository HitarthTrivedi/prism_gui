"""
Leads & Outreach — every run, kept
──────────────────────────────────
A Leads run costs real money and real minutes: an Exa search per industry, a
verify pass, a Groq call per qualified lead, a draft per reachable person. The
result lived only in the open window, and the next run had no idea who the
last one had already pulled — so it paid to pull them again, and the owner
could reach the same person from two runs.

So every run is saved as a SESSION: one plain JSON file per run, in a folder
the caller names, with `index.json` beside them. The session file is the
truth — the whole lead → dossier → draft graph, enough to reopen the run
exactly as it was left. The index is a cache over those files that answers
the two frequent questions without parsing every run:

  · which runs are there, newest first     → list_sessions() / latest()
  · who has an earlier run already pulled  → seen_keys()

What "pulled" means is decided per mode by pulled_keys(): a search pulled
everyone it sourced; a sheet run pulled only the people it spent the
expensive pass on, so running the same big sheet again moves on to the next
best people instead of refusing the whole sheet.

Rules this module keeps:

  · Qt-free and path-free. Every function takes the folder; nothing here looks
    up a home directory, a workspace or a config. The caller owns where
    sessions live, and a test owns a temp folder the same way.
  · Only whitelisted run parameters reach disk. The dialog builds its params
    next to `cfg`, which holds the Groq and Exa keys; params are copied key by
    key from PARAM_KEYS and everything else is dropped.
  · Writes are atomic (temp file in the same folder → fsync → os.replace), the
    precedent addons/email/sent_log.py set, so a crash mid-save leaves the
    previous file whole, never half of one.
  · Readers forgive, writers refuse. A damaged index is rebuilt from the
    session files; a damaged session is reported when it is opened
    (SessionStoreError) and never takes the list down with it.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from dataclasses import MISSING, asdict, fields, is_dataclass
from datetime import datetime

from prospector.filters import SearchSpec
from prospector.identity import keys_of
from prospector.models import HOT, WARM, Dimension, Dossier, Lead
from prospector.models import Signal as LeadSignal    # not PySide's Signal

SCHEMA = 1
MODES = ("sheet", "icp", "icp_leads_only")
# "filters" is the run's SearchSpec dict (prospector/filters.py); the legacy
# industries / roles / location stay beside it so an older build still reads
# the run.
PARAM_KEYS = ("mode", "sheet_path", "industries", "roles", "location", "target",
              "offer", "limit", "verify_limit", "claims_path", "include_earlier",
              "filters")

INDEX = "index.json"
_COUNT_KEYS = ("leads", "qualified", "hot", "warm", "drafted", "sent")
_LEAD_FIELDS = tuple(f.name for f in fields(Lead))
_DOSSIER_FIELDS = tuple(f.name for f in fields(Dossier) if f.name != "lead")
# reach.Draft is only imported inside load(), so its fields are named here for
# save(); a Draft that is a dataclass is still read through fields() below.
_DRAFT_FIELDS = ("subject", "body", "status", "error", "note")

# Prototypes whose default values tell load() what type each field should be.
_LEAD_PROTO = Lead()
_DOSSIER_PROTO = Dossier(lead=_LEAD_PROTO)
_DIMENSION_PROTO = Dimension(name="")
_SIGNAL_PROTO = LeadSignal()

# A session id is also a file name. No separators and no dots, so an id can
# never write outside the folder; "index" is refused so a session can never
# overwrite the index.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")

# The dialog saves from a worker thread while the screen may be listing; the
# index is read-modify-write, so the two must not interleave inside Prism.
_LOCK = threading.RLock()


class SessionStoreError(Exception):
    """A session could not be saved or opened. The message is written for the
    owner ("Couldn't save this session: …"), so the UI can show it as is."""


# ── ids and time ──────────────────────────────────────────────────────────────

def new_id() -> str:
    """"20260911-142233-a1b2c3": sorts by start time when read as text, and the
    random tail keeps two runs started in the same second apart."""
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def _now() -> str:
    """Local time with its UTC offset, to the second. One seam, so a test can
    move the clock between two saves."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _valid_id(value) -> bool:
    return (isinstance(value, str) and _ID.fullmatch(value) is not None
            and value.lower() != "index")


def _check_id(session_id, doing: str) -> None:
    if not _valid_id(session_id):
        raise SessionStoreError(f"{doing}: {session_id!r} is not a session id.")


# ── who a run pulled ──────────────────────────────────────────────────────────

def pulled_keys(mode, all_leads, dossiers) -> frozenset:
    """The identity keys of everyone this run PULLED — what a later run skips.

    A search (qualified or leads-only) pulled every person it sourced, so all
    of them count. A sheet is different: the owner brought the whole list and
    the run spent the expensive pass on only the best `limit` of it. Marking
    the whole sheet would leave a second run on the same sheet with nobody;
    marking the dossier leads makes it continue with the next best people.

    A dossier's lead counts in every mode, even if a caller's all_leads lacks
    it — it was qualified, so it was pulled — and that is also exactly what an
    index rebuilt from the saved file can see. A mode this build does not know
    is read as a search: better to skip a person than pull them twice."""
    people = [getattr(d, "lead", None) for d in (dossiers or ())]
    if mode != "sheet":
        people = list(all_leads or ()) + people
    keys = set()
    for lead in people:
        if lead is not None:
            keys.update(keys_of(lead))
    return frozenset(keys)


# ── object graph → plain data ─────────────────────────────────────────────────

def _jsonable(value, _depth: int = 0):
    """value made safe for json.dump. Lead.extra holds whatever a sheet row or
    a source handed over; anything JSON cannot hold is kept as its str(),
    rather than one odd cell failing the save of a whole run."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if _depth > 32:                          # a structure that contains itself
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v, _depth + 1) for v in value]
    return str(value)


def _leaf(item):
    """A Dimension or Signal as a dict (a dict passes through); anything else
    is None, so a malformed entry is dropped rather than saved as garbage."""
    if is_dataclass(item) and not isinstance(item, type):
        return _jsonable(asdict(item))
    if isinstance(item, dict):
        return _jsonable(item)
    return None


def _serialise(all_leads, dossiers, drafts):
    """Flatten the graph into rows that point at each other by position.

    Identity decides membership, not equality: two different people can have
    identical fields, and the cockpit keys drafts by id(dossier). A dossier
    whose lead is not in all_leads brings its lead along; a draft whose dossier
    is not being saved is left out, since there is nothing to hang it on.
    Every object is held in a list while its id() is in use, so no id can be
    reused mid-save."""
    leads, lead_at = [], {}

    def lead_index(lead) -> int:
        if id(lead) not in lead_at:
            lead_at[id(lead)] = len(leads)
            leads.append(lead)
        return lead_at[id(lead)]

    for lead in all_leads or ():
        if lead is not None:
            lead_index(lead)

    kept_dossiers, dossier_rows, dossier_at = [], [], {}
    for d in dossiers or ():
        lead = getattr(d, "lead", None)
        if d is None or lead is None or id(d) in dossier_at:
            continue
        row = {"lead": lead_index(lead)}
        for name in _DOSSIER_FIELDS:
            value = getattr(d, name, None)
            if name in ("dimensions", "signals"):
                items = value if isinstance(value, (list, tuple)) else ()
                row[name] = [x for x in map(_leaf, items) if x is not None]
            else:
                row[name] = _jsonable(value)
        dossier_at[id(d)] = len(dossier_rows)
        kept_dossiers.append(d)
        dossier_rows.append(row)

    kept_drafts, draft_rows = [], []
    for dr in drafts or ():
        j = dossier_at.get(id(getattr(dr, "dossier", None)))
        if dr is None or j is None:
            continue
        names = ([f.name for f in fields(dr) if f.name != "dossier"]
                 if is_dataclass(dr) else _DRAFT_FIELDS)
        row = {"dossier": j}
        row.update((n, _jsonable(getattr(dr, n, None))) for n in names)
        kept_drafts.append(dr)
        draft_rows.append(row)

    lead_rows = [{n: _jsonable(getattr(lead, n, None)) for n in _LEAD_FIELDS}
                 for lead in leads]
    return leads, lead_rows, kept_dossiers, dossier_rows, kept_drafts, draft_rows


# ── plain data → object graph ─────────────────────────────────────────────────

def _int(value, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _text(value) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _index(value):
    """A row position, or None. bool and float are refused on purpose: True
    and 1.0 both hash equal to 1 and would silently fetch row 1."""
    return value if type(value) is int else None


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _coerce(value, default):
    """value when it already has default's type, else the nearest reading of
    it, else default — so a hand-edited "72" still reads as 72, and one
    wrong-typed cell falls back instead of failing the whole run."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, str):
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return default
    if isinstance(default, int):
        return _int(value, default)
    if isinstance(default, float):
        if isinstance(value, bool):
            return default
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):  # an int no float holds
            return default
    if isinstance(default, dict):
        return value if isinstance(value, dict) else {}
    if isinstance(default, list):
        return value if isinstance(value, list) else []
    return default if value is None else value


def _build(cls, row: dict, proto, **fixed):
    """cls(...) from a row: known fields coerced to proto's types, unknown keys
    ignored (a file from a slightly different build still opens), and a field
    the row lacks left to the dataclass's own default."""
    kwargs = dict(fixed)
    for f in fields(cls):
        if f.name in kwargs:
            continue
        if f.name in row:
            kwargs[f.name] = _coerce(row[f.name], getattr(proto, f.name))
        elif f.default is MISSING and f.default_factory is MISSING:
            kwargs[f.name] = _coerce(None, getattr(proto, f.name))
    return cls(**kwargs)


# ── the header ────────────────────────────────────────────────────────────────

def _label(mode, params: dict) -> str:
    """What the session list calls a run: the sheet's file name, or how wide
    the search was and where."""
    if mode == "sheet":
        path = params.get("sheet_path")
        name = (re.split(r"[\\/]", path.strip().rstrip("\\/"))[-1]
                if isinstance(path, str) else "")
        return name or "Sheet"
    if isinstance(params.get("filters"), dict):
        # A filtered search says where from its facets — "Anywhere except
        # India" — not from a line of text that meant the opposite.
        spec = SearchSpec.from_dict(params["filters"])
        n = len(spec.industries.include)
        where = spec.location_label()
        if not n:
            return where
        return (f"{n} industry" if n == 1 else f"{n} industries") + f" · {where}"
    raw = params.get("industries")
    items = raw.splitlines() if isinstance(raw, str) else (
        raw if isinstance(raw, (list, tuple)) else ())
    n = sum(1 for x in items if isinstance(x, str) and x.strip())
    text = f"{n} industry" if n == 1 else f"{n} industries"
    where = params.get("location")
    where = where.strip() if isinstance(where, str) else ""
    return f"{text} · {where}" if where else text


def _header(session_id, mode, params, n_leads, dossiers, drafts, skipped_seen,
            created_at, updated_at) -> dict:
    """The small record the list shows. Counted off the objects actually
    saved, so the list and a reopened run can never disagree."""
    return {
        "id": session_id, "created_at": created_at, "updated_at": updated_at,
        "mode": mode, "label": _label(mode, params),
        "skipped_seen": skipped_seen,
        "counts": {
            "leads": n_leads,
            "qualified": len(dossiers),
            "hot": sum(1 for d in dossiers if getattr(d, "verdict", "") == HOT),
            "warm": sum(1 for d in dossiers if getattr(d, "verdict", "") == WARM),
            "drafted": len(drafts),
            "sent": sum(1 for dr in drafts if getattr(dr, "status", "") == "sent"),
        },
    }


def _clean_params(params, mode=None) -> dict:
    """PARAM_KEYS only — the one thing standing between cfg's API keys and a
    plain file in the owner's folder. `mode`, when given, wins over whatever
    params says, so the file and the header never name two different modes."""
    src = params if isinstance(params, dict) else {}
    out = {k: _jsonable(src[k]) for k in PARAM_KEYS if k in src}
    if "filters" in out:
        # Through SearchSpec, so only what a filter can hold reaches disk —
        # never a key someone parked inside the dict.
        out["filters"] = SearchSpec.from_dict(out["filters"]).to_dict()
    if mode is not None:
        out["mode"] = mode
    return out


# ── disk ──────────────────────────────────────────────────────────────────────

def _reason(e: OSError) -> str:
    what = e.strerror or str(e) or e.__class__.__name__
    return f"{what} ({e.filename})." if e.filename else f"{what}."


def _utf8(text: str) -> bytes:
    """text as UTF-8. Web text can carry half an emoji — a lone surrogate, left
    when a source cut a string mid-pair and its JSON escaped the half — and
    UTF-8 has no way to write one, so a single such snippet would fail the save
    of a whole run. Only those halves become U+FFFD (two halves that do make a
    pair are joined back into their emoji); the JSON stays valid, because every
    character JSON itself adds is ASCII."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return (text.encode("utf-16", "surrogatepass")
                .decode("utf-16", "replace").encode("utf-8"))


def _write_json(folder: str, name: str, payload) -> None:
    """Atomic replace of <folder>/<name>. The bytes go to a temp file in the
    SAME folder (so os.replace is a rename, never a copy across drives), are
    fsynced, and only then take the real name. On any failure the temp file is
    removed and the previous file is untouched."""
    target = os.path.join(folder, name)
    tmp = None
    try:
        data = _utf8(json.dumps(payload, ensure_ascii=False, indent=1))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        tmp = None
    except OSError as e:
        raise SessionStoreError("Couldn't save this session: " + _reason(e)) from e
    except (TypeError, ValueError) as e:     # something _jsonable did not catch
        raise SessionStoreError(
            f"Couldn't save this session: part of it could not be written ({e}).") from e
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _write_index(folder: str, entries: list) -> None:
    # Stable sort: among runs that began in the same second, the order they
    # were inserted in (newest first) is kept.
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    _write_json(folder, INDEX, {"schema": SCHEMA, "sessions": entries})


def _read_index(folder: str):
    """(raw entries, may_rewrite). raw is None when there is no usable index.
    An index written by a newer Prism is read around, and merely listing never
    rewrites it. A save still replaces it — that costs a cache, never a run,
    because the session files it was built from are left untouched."""
    try:
        with open(os.path.join(folder, INDEX), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        return None, True
    schema = data.get("schema") if isinstance(data, dict) else None
    if (type(schema) is not int or schema < 1
            or not isinstance(data.get("sessions"), list)):
        return None, True
    if schema > SCHEMA:
        return None, False
    return data["sessions"], True


def _normal_entry(raw):
    """An index row in the full header shape plus "pulled", or None when it
    does not even name a session."""
    if not isinstance(raw, dict) or not _valid_id(raw.get("id")):
        return None
    counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
    created = _text(raw.get("created_at"))
    return {
        "id": raw["id"], "created_at": created,
        "updated_at": _text(raw.get("updated_at")) or created,
        "mode": _text(raw.get("mode")), "label": _text(raw.get("label")),
        "skipped_seen": _int(raw.get("skipped_seen")),
        "counts": {k: _int(counts.get(k)) for k in _COUNT_KEYS},
        "pulled": [k for k in _list(raw.get("pulled")) if isinstance(k, str) and k],
    }


def _session_ids(folder: str) -> set:
    try:
        names = os.listdir(folder)
    except OSError:
        return set()
    return {n[:-5] for n in names
            if n.lower().endswith(".json") and _valid_id(n[:-5])}


def _entry_from_file(folder: str, session_id: str):
    """The index row for one session file, or None if it cannot be read.

    Any failure at all skips just this file. This runs inside list_sessions()
    and seen_keys(), whose never-raise covers the whole read — so an error let
    out of here would not cost one run: it would empty the list and quietly
    stop every later run from skipping anyone."""
    try:
        data = load(folder, session_id)
        header = data["header"]
        pulled = pulled_keys(header["mode"], data["all_leads"], data["dossiers"])
    except Exception:                                   # noqa: BLE001
        return None
    return dict(header, pulled=sorted(pulled))


def _entries(folder: str, write: bool = True) -> list:
    """The index as it should be: index.json reconciled with the session files
    actually in the folder. The files are the truth and the index a cache:

      · a missing or damaged index is rebuilt from the files;
      · a session file the index does not list is added — save() writes the
        session before the index, so a failure between the two leaves exactly
        that, and the run must not vanish from the list over it;
      · an entry whose file is gone is dropped — deleting a session file is how
        an owner makes Prism forget a run, including who it pulled.

    A repaired index is written back when `write` is set, best effort: a folder
    that cannot be written to still lists."""
    with _LOCK:
        on_disk = _session_ids(folder)
        raw, may_rewrite = _read_index(folder)
        changed = raw is None
        entries, listed = [], set()
        for item in raw or ():
            entry = _normal_entry(item)
            if entry is None or entry["id"] in listed or entry["id"] not in on_disk:
                changed = True
                continue
            listed.add(entry["id"])
            entries.append(entry)
        for session_id in sorted(on_disk - listed):
            entry = _entry_from_file(folder, session_id)
            if entry is not None:
                entries.append(entry)
                changed = True
        entries.sort(key=lambda e: e["created_at"], reverse=True)
        if (write and changed and may_rewrite
                and (entries or os.path.isfile(os.path.join(folder, INDEX)))):
            try:
                _write_index(folder, entries)
            except SessionStoreError:
                pass
        return entries


# ── the public surface ────────────────────────────────────────────────────────

def save(folder, session_id, *, mode, params, all_leads, dossiers, drafts,
         total_in_sheet=0, signal_source="", skipped_seen=0,
         created_at=None) -> dict:
    """Write <folder>/<session_id>.json and record it in <folder>/index.json,
    creating the folder if needed; return the run's header.

    Saving the same id again replaces the run and keeps when it began: the
    original created_at comes from the index (or, if the index lost it, from
    the session file itself) unless one is passed. Raises SessionStoreError
    when the run cannot be written; the previous file is then still whole."""
    _check_id(session_id, "Couldn't save this session")
    if mode not in MODES:
        raise SessionStoreError(
            f"Couldn't save this session: {mode!r} is not a kind of run Prism knows.")
    leads, lead_rows, kept_dossiers, dossier_rows, kept_drafts, draft_rows = \
        _serialise(all_leads, dossiers, drafts)
    clean = _clean_params(params, mode)
    skipped = _int(skipped_seen)
    pulled = sorted(pulled_keys(mode, leads, kept_dossiers))
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat(timespec="seconds")

    with _LOCK:
        entries = _entries(folder, write=False)
        previous = next((e for e in entries if e["id"] == session_id), None)
        now = _now()
        created = ((created_at if isinstance(created_at, str) and created_at else "")
                   or (previous or {}).get("created_at") or now)
        header = _header(session_id, mode, clean, len(leads), kept_dossiers,
                         kept_drafts, skipped, created, now)
        _write_json(folder, session_id + ".json", {
            "schema": SCHEMA, "id": session_id, "header": header, "params": clean,
            "total_in_sheet": _int(total_in_sheet),
            "signal_source": _text(signal_source), "skipped_seen": skipped,
            "leads": lead_rows, "dossiers": dossier_rows, "drafts": draft_rows,
        })
        entry = dict(header, pulled=pulled)
        if previous is None:
            entries.insert(0, entry)
        else:
            entries = [entry if e["id"] == session_id else e for e in entries]
        _write_index(folder, entries)
    return dict(header, counts=dict(header["counts"]))


def load(folder, session_id) -> dict:
    """Reopen a saved run as the object graph it was saved from.

    Returns {"header", "params", "all_leads", "dossiers", "drafts",
    "total_in_sheet", "signal_source", "skipped_seen"} where every
    dossier.lead IS an element of all_leads and every draft.dossier IS an
    element of dossiers — the cockpit keys drafts by id(dossier), so equal
    copies would silently detach every draft from its lead.

    Forgiving inside a session (unknown keys ignored, missing fields defaulted,
    malformed rows skipped, generated_at kept exactly — never re-stamped with
    today), strict about what a session is: a missing file, a damaged one, a
    file that is not a session or one from a newer Prism raises
    SessionStoreError."""
    _check_id(session_id, "Couldn't open this session")
    path = os.path.join(folder, session_id + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise SessionStoreError(
            "Couldn't open this session: it is no longer in the sessions folder.") from e
    except OSError as e:
        raise SessionStoreError("Couldn't open this session: " + _reason(e)) from e
    except (ValueError, RecursionError) as e:
        raise SessionStoreError(
            "Couldn't open this session: the file is damaged and cannot be read.") from e
    schema = data.get("schema") if isinstance(data, dict) else None
    if type(schema) is not int or schema < 1:
        raise SessionStoreError(
            "Couldn't open this session: the file is not a saved Leads session.")
    # Before the shape check: a newer schema is exactly when the shape may
    # change, and "update Prism" is the answer the owner can act on.
    if schema > SCHEMA:
        raise SessionStoreError(
            "Couldn't open this session: it was saved by a newer version of "
            "Prism. Update Prism to open it.")
    if not isinstance(data.get("leads"), list):
        raise SessionStoreError(
            "Couldn't open this session: the file is not a saved Leads session.")

    # Lazy: listing sessions and reading seen keys happen every time the Leads
    # screen opens and never need a Draft — only reopening a run does.
    from prospector.reach import Draft

    leads, lead_at = [], {}
    for i, row in enumerate(data["leads"]):
        if isinstance(row, dict):
            lead_at[i] = _build(Lead, row, _LEAD_PROTO)
            leads.append(lead_at[i])

    dossiers, dossier_at = [], {}
    for j, row in enumerate(_list(data.get("dossiers"))):
        lead = lead_at.get(_index(row.get("lead"))) if isinstance(row, dict) else None
        if lead is None:
            continue
        dossier_at[j] = _build(
            Dossier, row, _DOSSIER_PROTO, lead=lead,
            dimensions=[_build(Dimension, x, _DIMENSION_PROTO)
                        for x in _list(row.get("dimensions")) if isinstance(x, dict)],
            signals=[_build(LeadSignal, x, _SIGNAL_PROTO)
                     for x in _list(row.get("signals")) if isinstance(x, dict)],
            # Always passed: Dossier's default_factory would stamp "now".
            generated_at=_text(row.get("generated_at")))
        dossiers.append(dossier_at[j])

    draft_proto = Draft(dossier=_DOSSIER_PROTO)
    drafts = []
    for row in _list(data.get("drafts")):
        dossier = (dossier_at.get(_index(row.get("dossier")))
                   if isinstance(row, dict) else None)
        if dossier is not None:
            drafts.append(_build(Draft, row, draft_proto, dossier=dossier))

    params = _clean_params(data.get("params"))
    stored = data.get("header") if isinstance(data.get("header"), dict) else {}
    mode = _text(params.get("mode")) or _text(stored.get("mode"))
    if mode:
        params["mode"] = mode
    created = _text(stored.get("created_at")) or _mtime(path)
    updated = _text(stored.get("updated_at")) or created
    skipped = _int(data.get("skipped_seen"), _int(stored.get("skipped_seen")))
    return {
        "header": _header(session_id, mode, params, len(leads), dossiers, drafts,
                          skipped, created, updated),
        "params": params,
        "all_leads": leads,
        "dossiers": dossiers,
        "drafts": drafts,
        "total_in_sheet": _int(data.get("total_in_sheet")),
        "signal_source": _text(data.get("signal_source")),
        "skipped_seen": skipped,
    }


def _mtime(path: str) -> str:
    """When a session file lost its header, its modification time is the most
    honest "when" left."""
    try:
        return (datetime.fromtimestamp(os.path.getmtime(path)).astimezone()
                .isoformat(timespec="seconds"))
    except (OSError, ValueError, OverflowError):
        return ""


def list_sessions(folder) -> list:
    """Every saved run's header, newest first. Never raises: the Leads screen
    opens whatever state the folder is in. A missing or damaged index is
    rebuilt from the session files and written back."""
    try:
        return [{k: v for k, v in e.items() if k != "pulled"}
                for e in _entries(folder)]
    except Exception:                                   # noqa: BLE001
        return []


def latest(folder):
    """The newest run's header, or None — what "carry on where I left off"
    reopens."""
    sessions = list_sessions(folder)
    return sessions[0] if sessions else None


def seen_keys(folder, exclude_id=None) -> frozenset:
    """Every identity key an earlier run pulled; hand it to
    prospector.identity.SeenIndex and a new run skips those people.

    `exclude_id` leaves one run out, so re-running the session that is open
    does not count its own people as already pulled. Never raises: a store
    that cannot be read skips nobody, rather than stopping the run."""
    try:
        keys = set()
        for e in _entries(folder):
            if e["id"] != exclude_id:
                keys.update(e["pulled"])
        return frozenset(keys)
    except Exception:                                   # noqa: BLE001
        return frozenset()
