"""
Leads & Outreach — one JSON file, kept the way every store here keeps one
─────────────────────────────────────────────────────────────────────────
sessions.py and saved_searches.py each grew the same disk rules by hand. The
two stores Apollo's Find People adds — contacts.py (who is Saved) and
imports.py (every Contact / Account CSV import) — share this one copy of them
instead of a third and a fourth:

  · Readers forgive. read() never raises: no file is an empty store; a file
    that is not JSON, or not this store's shape, reads as DAMAGED (empty);
    one a newer Prism wrote reads as NEWER (empty, and never written over).
  · Writers refuse. for_writing() raises StoreError, worded for the owner,
    when the file must not be replaced — it exists but can't be opened, or a
    newer Prism wrote it.
  · Nothing is silently destroyed. A DAMAGED file is renamed to
    <name>.damaged-<when>.json before a new one takes its place.
  · Writes are atomic: a temp file in the SAME folder (so os.replace is a
    rename, never a copy across drives) → fsync → os.replace. On any failure
    the temp file goes and the previous file is untouched.

Qt-free and path-free, like the stores that use it: every call takes the
folder, and a test owns a temp one.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime

MISSING, OK, DAMAGED, NEWER, UNREADABLE = (
    "missing", "ok", "damaged", "newer", "unreadable")


class StoreError(Exception):
    """A write that could not happen, in words for the owner."""


def _reason(e: OSError) -> str:
    what = e.strerror or str(e) or e.__class__.__name__
    return f"{what} ({e.filename})." if e.filename else f"{what}."


def _utf8(text: str) -> bytes:
    """text as UTF-8, with any lone half of a surrogate pair (web text cut
    mid-emoji) made U+FFFD instead of failing the whole save — the repair
    sessions.py and saved_searches.py make."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return (text.encode("utf-16", "surrogatepass")
                .decode("utf-16", "replace").encode("utf-8"))


def read(folder, name: str, key: str, schema: int):
    """(state, items, reason) for <folder>/<name>, whose payload is
    {"schema": n, key: [...]}. items is the raw list — the caller decides
    what in it is readable. Never raises."""
    path = os.path.join(folder or "", name)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except (FileNotFoundError, NotADirectoryError):
        return MISSING, [], ""
    except OSError as e:
        return UNREADABLE, [], _reason(e)
    try:
        data = json.loads(raw.decode("utf-8-sig"))     # Notepad adds a BOM
    except (ValueError, RecursionError):
        return DAMAGED, [], ""
    version = data.get("schema") if isinstance(data, dict) else None
    # Before the shape check: a newer schema is exactly when the shape may
    # change, and that file must be left alone, not set aside as damage.
    if type(version) is int and version > schema:
        return NEWER, [], ""
    if (type(version) is not int or version < 1
            or not isinstance(data.get(key), list)):
        return DAMAGED, [], ""
    return OK, list(data[key]), ""


def for_writing(folder, name: str, key: str, schema: int, doing: str, what: str):
    """(state, items) for a read-modify-write — or StoreError when the file
    must not be written over. `what` names the store in the message ("your
    saved contacts")."""
    state, items, reason = read(folder, name, key, schema)
    if state == UNREADABLE:
        raise StoreError(f"{doing}: " + reason)
    if state == NEWER:
        raise StoreError(
            f"{doing}: {what} were saved by a newer version of Prism. Update "
            "Prism to change them.")
    return state, items


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _set_aside(folder, name: str, doing: str, what: str) -> None:
    """Move a damaged file to <name>.damaged-<when>.json before a new one
    takes its name. Never over an earlier set-aside file: a second in the same
    second gets "-2". If it can't be moved, nothing is written."""
    base = os.path.splitext(name)[0] + ".damaged-" + _stamp()
    target, n = base + ".json", 1
    while os.path.exists(os.path.join(folder, target)):
        n += 1
        target = f"{base}-{n}.json"
    try:
        os.rename(os.path.join(folder, name), os.path.join(folder, target))
    except OSError as e:
        raise StoreError(
            f"{doing}: the file holding {what} is damaged and could not be set "
            "aside, so it was left as it was. " + _reason(e)) from e


def _write_json(folder, name: str, doing: str, payload) -> None:
    target = os.path.join(folder, name)
    tmp = None
    try:
        data = _utf8(json.dumps(payload, ensure_ascii=False, indent=1))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder,
                                   prefix=os.path.splitext(name)[0] + "-",
                                   suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        tmp = None
    except OSError as e:
        raise StoreError(f"{doing}: " + _reason(e)) from e
    except (TypeError, ValueError) as e:     # something the cleaning did not catch
        raise StoreError(f"{doing}: part of it could not be written ({e}).") from e
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def commit(folder, name: str, key: str, schema: int, doing: str, what: str,
           state: str, items: list) -> None:
    """Write items back as the whole file; a DAMAGED original is set aside
    first. Only call with a state for_writing() returned."""
    if state == DAMAGED:
        _set_aside(folder, name, doing, what)
    _write_json(folder, name, doing, {"schema": schema, key: items})
