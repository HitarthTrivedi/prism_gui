"""Which conversations THIS seat has read.

Unread is derived, not stored server-side: a conversation is unread when its
last message is inbound and newer than the moment this seat last opened it.
That needs no new column and no n8n change, and it is per person on purpose —
one team member opening a chat must not clear the badge for everyone else.

The stamp saved is the conversation's own `last_active_at`, copied verbatim, so
the comparison is always between two strings from the same source and never
depends on clock skew or timestamp formatting.

Never raises: a read-state file that cannot be read or written costs a badge,
not the inbox.

STDLIB ONLY (paths is the repo's own stdlib-only module).
"""
from __future__ import annotations

import json
import os

_cache: dict | None = None


def _path() -> str:
    import paths
    return paths.user_dir("whatsapp_read.json")


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            _cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def reset_cache() -> None:
    global _cache
    _cache = None


def is_unread(row: dict) -> bool:
    if (row.get("last_direction") or "") != "in":
        return False
    stamp = _load().get(str(row.get("id")), "")
    return (row.get("last_active_at") or "") > stamp


def mark_read(conversation_id, stamp: str) -> None:
    data = _load()
    key = str(conversation_id)
    if not stamp or data.get(key, "") >= stamp:
        return
    data[key] = stamp
    try:
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass
