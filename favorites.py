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
    """[{"path": "...", "label": "...", "kind": "file"|"folder"}, ...]"""
    if not os.path.exists(_PATH):
        return []
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save(items: list[dict]) -> None:
    os.makedirs(C.CONFIG_DIR, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def add(path: str) -> list[dict]:
    path = os.path.abspath(os.path.expanduser(path))
    items = load()
    if any(i["path"] == path for i in items):
        return items
    items.append({
        "path": path,
        "label": os.path.basename(path.rstrip(os.sep)) or path,
        "kind": "folder" if os.path.isdir(path) else "file",
    })
    save(items)
    return items


def remove(path: str) -> list[dict]:
    items = [i for i in load() if i["path"] != path]
    save(items)
    return items
