"""
Leads & Outreach — saved searches
─────────────────────────────────
A good list takes a while to describe: the titles, the seniorities, the
industries, "anywhere except India", the headcount bands. The owner builds it
once and wants it back next week, run again, to pick up the people who were
not there last time. Apollo and Sales Navigator call that a saved search, and
this module keeps them.

A saved search is the FILTERS (prospector.filters.SearchSpec, as its plain
dict) and the few run SETTINGS that shape what comes back — how many people
to aim for, how many to qualify and verify, whether people an earlier run
pulled may come back, what the owner sells — under a name the owner chose.
Each run of it is recorded (when, which session holds it, how many new people
it found), so the list can say "ran yesterday · 34 new".

All of them live in ONE file, `saved_searches.json`, in a folder the caller
names. They are few, small and edited one at a time; a file per search would
buy nothing and turn "is this name taken?" into a scan of the folder.

Rules this module keeps — the ones addons/leads/sessions.py keeps:

  · Qt-free and path-free. Every function takes the folder; nothing here looks
    up a home directory, a workspace or a config.
  · Only whitelisted data reaches disk. The panel builds filters and settings
    next to `cfg`, which holds the Groq and Exa keys. Filters go through
    SearchSpec.from_dict(...).to_dict(), which writes every field a filter can
    hold and nothing else; settings are copied key by key from SETTING_KEYS.
  · Writes are atomic (temp file in the same folder → fsync → os.replace), and
    every read-modify-write holds one module lock, so two saves from two
    threads can never lose one of them.
  · Readers forgive, writers refuse. Listing never raises: a missing or damaged
    file lists nothing. A blank name, a name already taken, an id that is not
    there — a writer refuses with a message written for the owner, before it
    writes anything.
  · Nothing is silently destroyed. A damaged file is moved aside, as
    saved_searches.damaged-<when>.json, by the next save that would replace
    it; a file this build cannot read, or one a newer Prism wrote, is never
    written over at all.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime

from prospector.filters import SearchSpec

SCHEMA = 1
FILE = "saved_searches.json"
SETTING_KEYS = ("target", "limit", "verify_limit", "include_earlier", "offer")

# The longest name a search may have — also what the name box should allow.
NAME_MAX = 80

# Whole-number settings and the range each is pulled into. The same bounds the
# Leads workbench's spin boxes use (workbench.py), so a saved search can never
# ask for a run the workbench would not have let the owner start.
_RANGES = {"target": (20, 2000), "limit": (1, 500), "verify_limit": (0, 200)}
_OFFER_MAX = 4000

# "ss-20260911-142233-a1b2c3": when it was made, then a random tail.
_ID = re.compile(r"ss-\d{8}-\d{6}-[0-9a-f]{6}")
# A session id as addons/leads/sessions.py accepts one — the only store a
# search's runs are ever saved in, so anything else can't be opened later.
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")

# What _read() found at the path.
_MISSING, _OK, _DAMAGED, _NEWER, _UNREADABLE = (
    "missing", "ok", "damaged", "newer", "unreadable")

# The panel saves while a run's worker records its result on the same search;
# every change is read-modify-write of one file, so the two must not
# interleave inside Prism. Readers take it too: on Windows a file another
# thread holds open cannot be replaced.
_LOCK = threading.RLock()


class SavedSearchError(Exception):
    """A saved search could not be saved, renamed, deleted or updated. The
    message is written for the owner ("Couldn't save this search: …"), so the
    UI can show it as is."""


# ── ids and time ──────────────────────────────────────────────────────────────

def _stamp() -> str:
    """Local time to the second, as ids and set-aside file names carry it.
    One seam, so a test can hold the clock still."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _new_id(taken) -> str:
    """"ss-20260911-142233-a1b2c3": sorts by creation when read as text; the
    random tail keeps two searches saved in the same second apart."""
    while True:
        candidate = f"ss-{_stamp()}-{secrets.token_hex(3)}"
        if candidate not in taken:
            return candidate


def _now() -> str:
    """Local time with its UTC offset, to the second. One seam, so a test can
    move the clock between two saves."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _valid_id(value) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _valid_session_id(value) -> bool:
    return (isinstance(value, str) and _SESSION_ID.fullmatch(value) is not None
            and value.lower() != "index")


def _moment(text):
    """A timestamp as seconds since the epoch, or None. Compared as moments,
    not text: a search saved before the laptop crossed a timezone still sorts
    by when it happened. A time with no offset is read as local."""
    if not isinstance(text, str) or not text:
        return None
    try:
        when = datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.astimezone()
        return when.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _last_used(record) -> float:
    """What "most recently used" sorts on: the last run, or — for a search
    never run — its last edit. Unreadable times sort last."""
    for key in ("last_run_at", "updated_at"):
        moment = _moment(record.get(key))
        if moment is not None:
            return moment
    return float("-inf")


def _sort(records: list) -> None:
    # Stable, even reversed: among searches used in the same second, the order
    # they already had (a new one is inserted first) is kept.
    records.sort(key=_last_used, reverse=True)


# ── cleaning what a panel, a worker or a hand-edited file hands over ─────────

def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _whole(value):
    """value as a whole number, or None. bool is refused — True is not 1 of
    anything — and "300" from a hand-edited file still reads as 300."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        try:
            return int(value)
        except ValueError:
            pass
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):   # NaN, inf, a list, junk
        return None


def _count(value) -> int:
    return max(0, _whole(value) or 0)


def _clean_name(value) -> str:
    """Trimmed, every run of whitespace (newlines and tabs too) made one
    space; "" for anything that is not text."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _clean_settings(settings) -> dict:
    """SETTING_KEYS only — the one thing standing between cfg's API keys and a
    plain file in the owner's folder. Each value is coerced to its type and
    range; one that cannot be read is left out rather than guessed, so the
    dialog's own default applies when the search is run."""
    src = settings if isinstance(settings, dict) else {}
    out = {}
    for key in SETTING_KEYS:
        if key not in src:
            continue
        value = src[key]
        if key in _RANGES:
            number = _whole(value)
            if number is not None:
                low, high = _RANGES[key]
                out[key] = min(max(number, low), high)
        elif key == "include_earlier":
            if isinstance(value, bool):
                out[key] = value
        elif key == "offer":
            if isinstance(value, str):
                out[key] = value[:_OFFER_MAX]
    return out


def _filters_to_write(filters, doing: str) -> dict:
    """The filters as SearchSpec normalises them: labels become option keys
    ("Head" → "head"), a value on both sides becomes an exclusion, unknown
    keys are dropped. A SearchSpec is taken as is; anything that is not
    filters at all is refused rather than saved as an empty search."""
    if isinstance(filters, SearchSpec):
        filters = filters.to_dict()
    if not isinstance(filters, dict):
        raise SavedSearchError(f"{doing}: its filters could not be read.")
    return SearchSpec.from_dict(filters).to_dict()


def _checked_name(name, records, doing: str, search_id=None) -> str:
    """The cleaned name, or SavedSearchError. Unique regardless of case across
    the listed searches — two searches called "Pharma heads" and "pharma
    heads" can't be told apart in a list — except that a search being updated
    may keep its own name."""
    clean = _clean_name(name)
    if not clean:
        raise SavedSearchError(f"{doing}: give it a name.")
    if len(clean) > NAME_MAX:
        raise SavedSearchError(
            f"{doing}: a name can be at most {NAME_MAX} characters "
            f"(this one has {len(clean)}).")
    folded = clean.casefold()
    for record in records:
        if record["id"] != search_id and record["name"].casefold() == folded:
            raise SavedSearchError(
                f"{doing}: another saved search is already called "
                f"“{record['name']}”. Pick a different name.")
    return clean


def _normal(raw):
    """A stored entry in the full record shape, or None when it is not a saved
    search this build can list (see _read for what then becomes of it).

    What makes an entry a search is fixed: an object with a valid id, a name,
    and filters that are an object. Everything else is forgiven — a missing
    timestamp reads as "", a count typed as "3" as 3, a setting that can't be
    read is left out — because one wrong-typed field should not cost a search."""
    if not isinstance(raw, dict) or not _valid_id(raw.get("id")):
        return None
    name = _clean_name(raw.get("name"))
    filters = raw.get("filters")
    settings = raw.get("settings")
    if not name or not isinstance(filters, dict) or not isinstance(
            settings, (dict, type(None))):
        return None
    created = _text(raw.get("created_at"))
    session_id = raw.get("last_session_id")
    return {
        "id": raw["id"],
        "name": name,
        "filters": SearchSpec.from_dict(filters).to_dict(),
        "settings": _clean_settings(settings),
        "created_at": created,
        "updated_at": _text(raw.get("updated_at")) or created,
        "last_run_at": _text(raw.get("last_run_at")),
        "last_session_id": session_id if _valid_session_id(session_id) else "",
        "runs": _count(raw.get("runs")),
        "last_new": _count(raw.get("last_new")),
    }


# ── disk ──────────────────────────────────────────────────────────────────────

def _reason(e: OSError) -> str:
    what = e.strerror or str(e) or e.__class__.__name__
    return f"{what} ({e.filename})." if e.filename else f"{what}."


def _utf8(text: str) -> bytes:
    """text as UTF-8, with any lone half of a surrogate pair (an offer pasted
    from a web page that cut an emoji in two) made U+FFFD instead of failing
    the save. The same repair addons/leads/sessions.py makes."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return (text.encode("utf-16", "surrogatepass")
                .decode("utf-16", "replace").encode("utf-8"))


def _read(folder):
    """(state, records, kept, reason) for <folder>/saved_searches.json.

    state is _MISSING (no file — nothing saved yet), _OK, _DAMAGED (not JSON,
    or not this store's shape), _NEWER (a later schema: its shape may have
    changed, so it is neither listed nor written over) or _UNREADABLE (the
    file is there but can't be opened; `reason` says why). records are the
    listable searches, most recently used first.

    An entry inside a readable file that is not a search this build can list
    is kept out of the listing. What the next write does with it is decided
    by whether anything in it could be a search:

      · an OBJECT — a search with its id mistyped, its name blanked or its
        filters turned into text by a hand edit; or a second entry with an id
        already listed (the first one is the search) — goes in `kept` and is
        written back exactly as it was, after the searches. It is the owner's
        data and can still be repaired by hand;
      · anything that is not an object (a number, a string, null) holds
        nothing that could be a search, and the next write drops it.

    One entry that fails in a way nobody foresaw costs only itself: the
    never-raise of list_searches() covers the whole read, so an error let out
    of here would empty the list instead."""
    path = os.path.join(folder, FILE)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except (FileNotFoundError, NotADirectoryError):
        return _MISSING, [], [], ""
    except OSError as e:
        return _UNREADABLE, [], [], _reason(e)
    try:
        data = json.loads(raw.decode("utf-8-sig"))     # Notepad adds a BOM
    except (ValueError, RecursionError):
        return _DAMAGED, [], [], ""
    schema = data.get("schema") if isinstance(data, dict) else None
    # Before the shape check: a newer schema is exactly when the shape may
    # change, and that file must be left alone, not set aside as damage.
    if type(schema) is int and schema > SCHEMA:
        return _NEWER, [], [], ""
    if (type(schema) is not int or schema < 1
            or not isinstance(data.get("searches"), list)):
        return _DAMAGED, [], [], ""
    records, kept, listed = [], [], set()
    for item in data["searches"]:
        try:
            record = _normal(item)
        except Exception:                                   # noqa: BLE001
            record = None
        if record is not None and record["id"] not in listed:
            listed.add(record["id"])
            records.append(record)
        elif isinstance(item, dict):
            kept.append(item)
    _sort(records)
    return _OK, records, kept, ""


def _for_writing(folder, doing: str):
    """(state, records, kept) for a writer — or SavedSearchError when the file
    must not be written over: one that exists but can't be opened, or one a
    newer Prism wrote."""
    state, records, kept, reason = _read(folder)
    if state == _UNREADABLE:
        raise SavedSearchError(f"{doing}: " + reason)
    if state == _NEWER:
        raise SavedSearchError(
            f"{doing}: your saved searches were saved by a newer version of "
            "Prism. Update Prism to change them.")
    return state, records, kept


def _set_aside(folder, doing: str) -> None:
    """Move a damaged file to saved_searches.damaged-<when>.json before a new
    one takes its name. Never over an earlier set-aside file: a second one in
    the same second gets "-2". If it can't be moved, nothing is written."""
    base = os.path.splitext(FILE)[0] + ".damaged-" + _stamp()
    name, n = base + ".json", 1
    while os.path.exists(os.path.join(folder, name)):
        n += 1
        name = f"{base}-{n}.json"
    try:
        os.rename(os.path.join(folder, FILE), os.path.join(folder, name))
    except OSError as e:
        raise SavedSearchError(
            f"{doing}: the saved searches file is damaged and could not be set "
            "aside, so it was left as it was. " + _reason(e)) from e


def _write_json(folder, doing: str, payload) -> None:
    """Atomic replace of <folder>/saved_searches.json. The bytes go to a temp
    file in the SAME folder (so os.replace is a rename, never a copy across
    drives), are fsynced, and only then take the real name. On any failure the
    temp file is removed and the previous file is untouched."""
    target = os.path.join(folder, FILE)
    tmp = None
    try:
        data = _utf8(json.dumps(payload, ensure_ascii=False, indent=1))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix="saved_searches-",
                                   suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        tmp = None
    except OSError as e:
        raise SavedSearchError(f"{doing}: " + _reason(e)) from e
    except (TypeError, ValueError) as e:     # something the cleaning did not catch
        raise SavedSearchError(
            f"{doing}: part of it could not be written ({e}).") from e
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _commit(folder, doing: str, state: str, records: list, kept: list) -> None:
    if state == _DAMAGED:
        _set_aside(folder, doing)
    _sort(records)
    _write_json(folder, doing, {"schema": SCHEMA, "searches": records + kept})


def _find(records, search_id):
    for i, record in enumerate(records):
        if record["id"] == search_id:
            return i
    return None


# ── the public surface ────────────────────────────────────────────────────────

def list_searches(folder) -> list:
    """Every saved search, most recently used first (its last run, or its last
    edit if it has never run). Never raises: the Leads screen opens whatever
    state the folder is in, and a missing, damaged or newer file lists
    nothing. Listing never writes."""
    try:
        with _LOCK:
            return _read(folder)[1]
    except Exception:                                       # noqa: BLE001
        return []


def get(folder, search_id):
    """One saved search, or None — for an id that is not there, is not an id,
    or a file that can't be read. Never raises."""
    if not _valid_id(search_id):
        return None
    return next((r for r in list_searches(folder) if r["id"] == search_id), None)


def save(folder, name, filters, settings=None, search_id=None) -> dict:
    """Create a saved search (search_id None) or update the one with that id;
    return the record as written.

    An update replaces the name, the filters and — when `settings` is given —
    the settings; `settings=None` keeps the ones it had, so a caller that only
    owns the filters can't wipe the offer. Its run history and created_at are
    kept. Raises SavedSearchError for a bad or taken name, filters or settings
    that are not objects, an id that is not there, or a file that can't be
    written; nothing is written then."""
    doing = "Couldn't save this search"
    if search_id is not None and not _valid_id(search_id):
        raise SavedSearchError(f"{doing}: {search_id!r} is not a saved search id.")
    clean_filters = _filters_to_write(filters, doing)
    if settings is not None and not isinstance(settings, dict):
        raise SavedSearchError(f"{doing}: its settings could not be read.")
    with _LOCK:
        state, records, kept = _for_writing(folder, doing)
        now = _now()
        if search_id is None:
            clean_name = _checked_name(name, records, doing)
            taken = {r["id"] for r in records} | {
                k.get("id") for k in kept if isinstance(k.get("id"), str)}
            record = {
                "id": _new_id(taken), "name": clean_name,
                "filters": clean_filters, "settings": _clean_settings(settings),
                "created_at": now, "updated_at": now,
                "last_run_at": "", "last_session_id": "", "runs": 0, "last_new": 0,
            }
            records.insert(0, record)
        else:
            i = _find(records, search_id)
            if i is None:
                raise SavedSearchError(
                    f"{doing}: it is no longer in your saved searches.")
            clean_name = _checked_name(name, records, doing, search_id)
            record = dict(records[i], name=clean_name, filters=clean_filters,
                          updated_at=now)
            if settings is not None:
                record["settings"] = _clean_settings(settings)
            records[i] = record
        _commit(folder, doing, state, records, kept)
    return record


def rename(folder, search_id, name) -> dict:
    """Give a saved search a new name; return the record. Renaming to the name
    it already has writes nothing. Raises SavedSearchError for a bad or taken
    name, or an id that is not there."""
    doing = "Couldn't rename this search"
    if not _valid_id(search_id):
        raise SavedSearchError(f"{doing}: {search_id!r} is not a saved search id.")
    with _LOCK:
        state, records, kept = _for_writing(folder, doing)
        i = _find(records, search_id)
        if i is None:
            raise SavedSearchError(f"{doing}: it is no longer in your saved searches.")
        clean_name = _checked_name(name, records, doing, search_id)
        if clean_name == records[i]["name"]:
            return records[i]
        record = dict(records[i], name=clean_name, updated_at=_now())
        records[i] = record
        _commit(folder, doing, state, records, kept)
    return record


def delete(folder, search_id) -> bool:
    """Forget a saved search. True when it was there and is gone; False when
    there was no such search. The sessions its runs saved are not touched.
    Raises SavedSearchError only when the file can't be written."""
    doing = "Couldn't delete this search"
    if not _valid_id(search_id):
        return False
    with _LOCK:
        state, records, kept = _for_writing(folder, doing)
        i = _find(records, search_id)
        if i is None:
            return False
        del records[i]
        _commit(folder, doing, state, records, kept)
    return True


def mark_run(folder, search_id, session_id, *, new_people: int):
    """Record that the search was just run: one more run, now, saved as
    `session_id`, which found `new_people` people no earlier run had. Returns
    the record, or None when there is no such search (it may have been
    deleted while it ran). Raises SavedSearchError only when the file can't be
    written — the run itself is already saved in its session.

    The same session reported twice is one run: the workbench saves a run's
    session again as its drafts are verified and sent, and a caller that
    reports on each of those saves must not make the count climb. The newer
    `new_people` is kept; the run count and when it ran are not moved.
    A session id that is not one (None when the session could not be saved)
    is stored as "", and every such report counts."""
    doing = "Couldn't record this run on the saved search"
    if not _valid_id(search_id):
        return None
    with _LOCK:
        state, records, kept = _for_writing(folder, doing)
        i = _find(records, search_id)
        if i is None:
            return None
        before = records[i]
        session = session_id if _valid_session_id(session_id) else ""
        record = dict(before, last_session_id=session, last_new=_count(new_people))
        if not (session and session == before["last_session_id"]):
            record["runs"] = before["runs"] + 1
            record["last_run_at"] = _now()
        records[i] = record
        _commit(folder, doing, state, records, kept)
    return record


def summary(record) -> str:
    """The search's filters in a few words — "6 titles · 10 industries ·
    Anywhere except India · +3 more" — for the list row. Never raises."""
    filters = record.get("filters") if isinstance(record, dict) else None
    return SearchSpec.from_dict(filters).summary()
