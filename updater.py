"""In-app updates — Phase 0: know that a newer Prism exists, and say so.

Prism has no self-update yet. What exists today is the licence server telling
every client, on every lease, two things it already knew:

    latest_version          the newest build we have shipped        (advisory)
    min_supported_version   the oldest build it will still lease to (enforced
                            SERVER-side: an older client keeps opening, keeps
                            its History, and cannot start new protected work)

Until 1.3.1 the client dropped both on the floor. This module is what reads
them: it turns the pair into a banner with a Download button, and remembers
which version the customer has already said "not now" to. That is the whole
of Phase 0 in update-plan.md §2. The real updater — a signed manifest, a
staged copy of the new build, a swap on restart, a rollback — is Phase 1 and
grows in this file, which is why it is not three functions inside
main_window.py.

Kept free of Qt, like licensing/, so the CLI and the tests can use it.

Trust
─────
Everything here is advisory. The two strings arrive UNSIGNED beside the
signed lease, so a tampered server answer, a proxy, or a hand-edited
license.json can make Prism *suggest* an update — it cannot make Prism fetch
or run anything. The Download button opens a fixed vendor address
(app_meta.DOWNLOAD_URL), never a URL the server handed us; the day this
module downloads code, that code is verified against a key that ships in the
build (update-research.md §5), not against anything in a response.
"""
from __future__ import annotations

import os
import time
from typing import Any

import app_meta
import licensing
from licensing import store
from licensing.status import LicenseState, newer

STATE_FILENAME = "update_state.json"

_DEFAULT: dict[str, Any] = {
    # The version the customer pressed "Not now" on. Compared exactly: a
    # newer release than the one dismissed shows the banner again, which is
    # the point — "not now" means this one, not for ever.
    "dismissed": "",
    "dismissed_at": 0,
}


# ── the state file ─────────────────────────────────────────────────────────
def state_path() -> str:
    """~/.prism/update_state.json. Beside license.json, through the same
    user_dir() the tests redirect, so a test can never dismiss a real
    customer's banner."""
    return os.path.join(licensing.user_dir(), STATE_FILENAME)


def _load() -> dict[str, Any]:
    return store.read_json(state_path(), _DEFAULT)


def _save(data: dict[str, Any]) -> None:
    store.write_json(state_path(), {**_DEFAULT, **data})


# ── what the server said, against what is running ──────────────────────────
def available(state: LicenseState | None = None,
              running: str | None = None) -> str:
    """The newer version the server knows about, or "" if this IS the newest
    (or nobody has told us otherwise). Never raises: an unparseable answer
    is "no advice", not "update now"."""
    state = licensing.state() if state is None else state
    running = app_meta.VERSION if running is None else running
    latest = (state.latest_version or "").strip()
    return latest if newer(latest, running) else ""


def required(state: LicenseState | None = None,
             running: str | None = None) -> bool:
    """Has the server's floor moved above this build?

    True means the server has ALREADY stopped leasing to this build — the
    refusal is theirs, this only repeats it. The app still opens and History
    still works; what changes is the banner's wording, from "there is a newer
    one" to "update to continue".
    """
    state = licensing.state() if state is None else state
    running = app_meta.VERSION if running is None else running
    return newer((state.min_supported_version or "").strip(), running)


def target(state: LicenseState | None = None,
           running: str | None = None) -> str:
    """The version to tell the customer to get: the newest we know of, or
    failing that the floor itself — a floor with no `latest` beside it is a
    misconfigured server, and the banner should still name a number."""
    state = licensing.state() if state is None else state
    return (available(state, running)
            or (state.min_supported_version or "").strip())


# ── "Not now" ──────────────────────────────────────────────────────────────
def dismissed(version: str) -> bool:
    """Has the customer already waved THIS version away?"""
    version = (version or "").strip()
    return bool(version) and _load().get("dismissed") == version


def dismiss(version: str) -> None:
    """Hide the banner for this version. Never raises — a full disk must not
    turn "Not now" into a crash; the worst case is the banner coming back."""
    version = (version or "").strip()
    if not version:
        return
    try:
        _save({"dismissed": version, "dismissed_at": int(time.time())})
    except Exception:                               # noqa: BLE001
        pass


def download_url() -> str:
    """Where the Download button goes. Fixed at build time on purpose."""
    return app_meta.DOWNLOAD_URL
