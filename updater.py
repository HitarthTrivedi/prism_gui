"""Updates — Phase 0: a banner and a link, nothing fetched, nothing run.

The decision behind this module was taken out loud: Prism will never
download or execute an update by itself. Giving an app permission to open
a terminal and run whatever a server hands it is the exact pattern
antivirus flags, and one bad update on a factory owner's only laptop, with
no undo, breaks his machine instead of helping him. So the owner is TOLD,
and the owner clicks: the banner says a newer Prism exists, the button opens
the download page in the browser, and installing it is the same thing they
did the first time.

Two levels, both read off the licence server's answer (`LicenseState`):

  * **available** — a newer version exists. Advisory; dismissible per
    version ("Not now"), and a newer one brings the banner back.
  * **required** — the server has stopped leasing to this build, so new
    work is already refused. Not dismissible; outranks everything else on
    the banner.

The server's advice arrives in the licence file (`latest_version`,
`min_supported_version`, written by the licensing round trip) and is read
from there — `LicenseState` itself does not carry version fields. Until the
server sends them, both answer "no", which is honest: there is no update to
report. The comparison is a plain dotted-number compare so "1.10.0" is
newer than "1.9.0".

This file was written to unblock `main` — the commit that added the two
call sites (main_window.py, widgets/settings_panel.py) did not include it.
If a fuller updater.py lands from that work, it should replace this one
wholesale; every name the callers use is defined here and nowhere else.
"""
from __future__ import annotations

import json
import os

import app_meta
import licensing
from licensing import store

# Per-version "Not now" answers live beside the licence file (never in
# config.json — a config rewrite must not quietly forget them), under the
# same user_dir the licensing tests redirect, so a test never touches the
# developer's real ~/.prism.
_DISMISSALS = "updates.json"

LATEST_FIELDS = ("latest_version", "latest", "update_available")
FLOOR_FIELDS = ("min_supported_version", "min_version", "minimum_version",
                "required_version")


# ── versions ──────────────────────────────────────────────────────────────────

def _parts(version: str) -> tuple:
    out = []
    for piece in str(version or "").strip().split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(candidate: str, than: str = app_meta.VERSION) -> bool:
    """True when `candidate` is a strictly higher dotted version."""
    if not (candidate or "").strip():
        return False
    return _parts(candidate) > _parts(than)


def _field(state, names) -> str:
    """The first of `names` found — on the state object, in a payload dict
    it may carry, or in the licence file on disk, which is where the
    licensing round trip actually writes the server's version advice."""
    for name in names:
        value = getattr(state, name, None)
        if value:
            return str(value)
    payload = getattr(state, "payload", None)
    if isinstance(payload, dict):
        for name in names:
            if payload.get(name):
                return str(payload[name])
    try:
        data = store.load(licensing.user_dir())
    except Exception:                          # noqa: BLE001 — advice only
        return ""
    for name in names:
        if data.get(name):
            return str(data[name])
    return ""


# ── what the callers ask ──────────────────────────────────────────────────────

def available(state) -> str | None:
    """The newest version the server knows of, if it is newer than this
    build; else None."""
    latest = _field(state, LATEST_FIELDS)
    return latest if is_newer(latest) else None


def required(state) -> bool:
    """True when the server says this build may no longer start new work."""
    return is_newer(_field(state, FLOOR_FIELDS))


def target(state) -> str:
    """The version a required update is to: the newest the server names,
    else the floor it insists on, else this build."""
    return (available(state) or _field(state, FLOOR_FIELDS)
            or app_meta.VERSION)


def download_url() -> str:
    return app_meta.DOWNLOAD_URL


# ── "Not now" ─────────────────────────────────────────────────────────────────

def _dismissals_path() -> str:
    return os.path.join(licensing.user_dir(), _DISMISSALS)


def _load() -> dict:
    try:
        with open(_dismissals_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def dismissed(version: str) -> bool:
    """Has "Not now" been pressed for exactly this version?"""
    return str(version or "").strip() in set(_load().get("dismissed") or [])


def dismiss(version: str) -> None:
    version = str(version or "").strip()
    if not version:
        return
    data = _load()
    done = list(data.get("dismissed") or [])
    if version not in done:
        done.append(version)
    data["dismissed"] = done
    try:
        os.makedirs(licensing.user_dir(), exist_ok=True)
        with open(_dismissals_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass        # a nudge that comes back tomorrow is not worth an error
