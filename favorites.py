"""
Prism GUI — favorited files/folders
────────────────────────────────────
A quick-attach shelf: paths the user stars once, then clicks in the sidebar
instead of re-typing/re-describing them every time. Stored alongside the
CLI's own config directory so it survives reinstalls of either app.
"""
from __future__ import annotations
import os
import json

from core_bridge import config as C

_PATH = os.path.join(C.CONFIG_DIR, "gui_favorites.json")


def load() -> list[dict]:
    """[{"path": "...", "label": "...", "kind": "file"|"folder"}, ...]

    Coerces anything that isn't a list-of-dicts-with-a-path back to []: the
    file is plain JSON in ~/.prism that a user can hand-edit, and add()/remove()
    below index i["path"] directly — a wrong shape must not crash them.
    """
    if not os.path.exists(_PATH):
        return []
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [i for i in data if isinstance(i, dict) and "path" in i]


def save(items: list[dict]) -> None:
    """Write atomically. The old version opened the real file in "w", which
    truncates it to zero the instant it opens — so a disk-full or a crash
    anywhere before the write completed left an EMPTY file, and load()'s
    except-returns-[] then read that as "no favourites", silently wiping the
    user's whole shelf. Write a complete temp file, fsync it, and os.replace()
    it in (atomic on POSIX and Windows) so the file is only ever the old
    contents or the new — never a truncated in-between. Mirrors
    workspace.save_team, which already does this right."""
    os.makedirs(C.CONFIG_DIR, exist_ok=True)
    tmp = f"{_PATH}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(path: str) -> list[dict]:
    path = os.path.abspath(os.path.expanduser(path))
    items = load()
    if any(i.get("path") == path for i in items):
        return items
    items.append({
        "path": path,
        "label": os.path.basename(path.rstrip(os.sep)) or path,
        "kind": "folder" if os.path.isdir(path) else "file",
    })
    save(items)
    return items


def remove(path: str) -> list[dict]:
    items = [i for i in load() if i.get("path") != path]
    save(items)
    return items
