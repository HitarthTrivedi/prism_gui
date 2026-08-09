"""Where licence state lives on disk: ~/.prism/license.json.

Deliberately NOT in config.json. core/config.py's save() rewrites the whole
dict from whatever the caller is holding, and the GUI keeps `self.cfg` in
memory across dialogs — so any stale copy written back would silently erase the
licence. That would surface as apparently random deactivations, which is about
the worst bug this system could have. A separate file also leaves the
prism_terminal submodule untouched, keeping the CLI a genuinely separate
product.

Every read here is defensive. A truncated or hand-edited file must resolve to
"no licence", never to a crash: the file is user-writable, and the one thing
worse than a customer losing their activation is Prism refusing to launch
because of it.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

FILENAME = "license.json"
PAYLOAD_FILENAME = "payload.enc"

_DEFAULT: dict[str, Any] = {
    "token": "",
    "license_id": "",
    "key": "",              # kept so the app can silently re-activate itself
    "last_seen_utc": 0,     # clock high-water mark
    "last_refresh_attempt": 0,
    "payload_etag": "",
    "server": "",
    # The member's designation key (licensing/designation.py). Beside the
    # licence rather than in config.json for the same reason as the token:
    # config.py rewrites the whole dict from whatever the caller holds, and a
    # stale copy written back would silently demote somebody to no role.
    "designation": "",
}


def path(user_dir: str) -> str:
    return os.path.join(user_dir, FILENAME)


def payload_path(user_dir: str) -> str:
    return os.path.join(user_dir, PAYLOAD_FILENAME)


def load(user_dir: str) -> dict[str, Any]:
    try:
        with open(path(user_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(_DEFAULT)
        return {**_DEFAULT, **data}
    except (OSError, ValueError):
        # Missing, unreadable, truncated, or not JSON. All the same to us.
        return dict(_DEFAULT)


def save(user_dir: str, data: dict[str, Any]) -> None:
    """Write atomically.

    A half-written license.json is indistinguishable from a tampered one, and
    would lock the customer out over a power cut. Write a sibling temp file and
    rename — os.replace is atomic on POSIX and on Windows.
    """
    os.makedirs(user_dir, exist_ok=True)
    target = path(user_dir)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=user_dir, prefix=".license-", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump({**_DEFAULT, **data}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def update(user_dir: str, **fields: Any) -> dict[str, Any]:
    """Change some fields and leave the rest alone.

    The read-modify-write that save() alone invites callers to do by hand —
    and doing it by hand is how a caller holding a stale dict wipes the token
    while only meaning to set the designation.
    """
    data = load(user_dir)
    data.update(fields)
    save(user_dir, data)
    return data


def touch_clock(user_dir: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Advance the high-water mark to now, if now is later than it.

    Only ever moves forward. That is what makes winding the clock back
    detectable at all — see state.clock_rolled_back().
    """
    data = load(user_dir) if data is None else data
    now = int(time.time())
    if now > int(data.get("last_seen_utc") or 0):
        data["last_seen_utc"] = now
        save(user_dir, data)
    return data


def clear(user_dir: str) -> None:
    """Forget this machine's activation. Used by Deactivate this device."""
    for p in (path(user_dir), payload_path(user_dir)):
        try:
            os.unlink(p)
        except OSError:
            pass
