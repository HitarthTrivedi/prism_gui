"""Prism licensing — the whole public surface.

Everything outside this package imports only this module:

    licensing.state()                  what the licence currently allows
    licensing.has("boq")               entitlement check
    licensing.require("boq", self)     check, and show the paywall if not
    licensing.activate(key)            from the activation dialog
    licensing.deactivate()             release this machine's seat
    licensing.refresh()                background token renewal
    licensing.set_paywall_handler(fn)  wire the UI in, once, at startup

There is deliberately no start_trial(). Trials are keys we issue by hand; the
client cannot mint one.

Two rules run through all of it:

  · Never block the UI. refresh() returns immediately; the network happens on a
    daemon thread and the window builds against the cached token.
  · Fail toward the customer. Any unexpected failure in here resolves to the
    last state we were sure about, never to "expired". A bug in our code must
    not lock out someone who has paid.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

import app_meta
import paths

from . import client, device, keyformat, keys, status as _status, store, token
from .client import ServerError, Unreachable
from .status import (EXPIRED, GRACE, NONE, TAMPERED, VALID,  # noqa: F401
                     LicenseState)
from .token import TokenError

# NB: the module is status.py, not state.py, because this package also exposes
# a state() function — and a submodule and a function of the same name means
# `from licensing import state` silently hands back whichever won the import,
# which is the sort of thing that is only ever debugged once.

__all__ = [
    "state", "has", "require", "activate", "deactivate", "refresh",
    "set_paywall_handler", "device_fingerprint", "reload", "user_dir",
    "LicenseState", "ServerError", "Unreachable", "TokenError", "keyformat",
    "NONE", "VALID", "GRACE", "EXPIRED", "TAMPERED",
]

_lock = threading.Lock()
_cached: LicenseState | None = None
_paywall: Callable[[str, Any, LicenseState], None] | None = None


def user_dir() -> str:
    return paths.user_dir()


def device_fingerprint() -> str:
    return device.fingerprint(user_dir())[0]


# ── reading the current state ──────────────────────────────────────────────
def _compute() -> LicenseState:
    data = store.load(user_dir())
    if not data.get("token"):
        return _status.none()

    if _status.clock_rolled_back(int(data.get("last_seen_utc") or 0)):
        return _status.tampered(
            "This computer's clock has been set back. Connect to the internet "
            "so Prism can check your licence.")

    try:
        claims = token.verify(data["token"],
                              device_fp=device_fingerprint(),
                              public_keys=keys.public_keys())
    except TokenError as e:
        return _status.tampered(str(e))

    return _status.resolve(claims)


def state() -> LicenseState:
    """The current licence state. Cached, cheap, safe to call from paint code."""
    global _cached
    with _lock:
        if _cached is None:
            try:
                _cached = _compute()
            except Exception:                       # noqa: BLE001
                # Something we did not anticipate — an unreadable registry, a
                # platform id that vanished mid-session. Send them to the
                # activation screen, which is recoverable, rather than to
                # "expired", which looks like we took their licence away.
                _cached = _status.none(
                    "Prism couldn't read its licence. Please re-enter your key.")
        return _cached


def reload() -> LicenseState:
    """Drop the cache and re-read from disk."""
    global _cached
    with _lock:
        _cached = None
    return state()


def has(feature: str) -> bool:
    return state().has(feature)


def set_paywall_handler(fn: Callable[[str, Any, LicenseState], None]) -> None:
    """Register what to show when a locked feature is opened. Called once, from
    main(), so this package never imports Qt."""
    global _paywall
    _paywall = fn


def require(feature: str, parent: Any = None) -> bool:
    """Gate an action. Shows the paywall itself, so call sites stay one line:

        if not licensing.require("boq", self):
            return
    """
    if has(feature):
        return True
    if _paywall is not None:
        try:
            _paywall(feature, parent, state())
        except Exception:                           # noqa: BLE001
            pass    # a broken dialog must not turn into a crash on a click
    return False


# ── talking to the server ──────────────────────────────────────────────────
def _apply(response: dict[str, Any], *, key: str = "") -> LicenseState:
    """Persist whatever the server just told us, and re-read."""
    data = store.load(user_dir())
    if response.get("token"):
        data["token"] = response["token"]
    if key:
        data["key"] = keyformat.normalise(key)
    if response.get("license_id"):
        data["license_id"] = response["license_id"]
    data["server"] = client.server_url()
    store.save(user_dir(), data)
    store.touch_clock(user_dir())
    return reload()


def activate(key: str) -> LicenseState:
    """Turn a licence key into a token on this machine. Raises ServerError with
    the server's own customer-facing wording, or Unreachable."""
    normalised = keyformat.normalise(key)
    response = client.activate(
        normalised, device_fingerprint(),
        app_version=app_meta.VERSION,
        hostname_label=_hostname())
    return _apply(response, key=normalised)


def deactivate() -> None:
    """Release this machine's seat. Local state is cleared even if the server
    call fails — a customer who has decommissioned a laptop should not be stuck
    with it activated, and a stranded seat is one admin call to release."""
    current = state()
    try:
        if current.license_id:
            client.deactivate(current.license_id, device_fingerprint(),
                              app_version=app_meta.VERSION)
    except (ServerError, Unreachable):
        pass
    store.clear(user_dir())
    reload()


def _refresh_once() -> LicenseState:
    data = store.load(user_dir())
    license_id = data.get("license_id") or state().license_id
    if not license_id:
        return state()
    try:
        response = client.refresh(license_id, device_fingerprint(),
                                  app_version=app_meta.VERSION,
                                  payload_etag=data.get("payload_etag") or "")
    except ServerError as e:
        if e.code == "DEVICE_NOT_ACTIVATED" and data.get("key"):
            # Someone released this seat, probably by accident. We still hold
            # the key, so re-activate and heal it without troubling anyone.
            try:
                return activate(data["key"])
            except (ServerError, Unreachable):
                return state()
        # Any other refusal — expired, revoked — changes nothing right now.
        # The token we already hold is the authority until it runs out.
        return state()
    except Unreachable:
        return state()
    return _apply(response)


def refresh(blocking: bool = False) -> LicenseState | None:
    """Renew the token. Returns immediately unless `blocking`.

    Called at launch and periodically. Never surfaces an error: an unreachable
    server is a normal condition that the cached token already covers.
    """
    store.touch_clock(user_dir())
    if blocking:
        return _refresh_once()
    threading.Thread(target=_safe_refresh, name="prism-license-refresh",
                     daemon=True).start()
    return None


def _safe_refresh() -> None:
    try:
        _refresh_once()
    except Exception:                               # noqa: BLE001
        pass


def selftest() -> tuple[bool, str]:
    """Verify the committed test vector. Called by main.py's --selftest.

    This has to verify a real signature, not merely import the crypto library.
    `cryptography` loads a native backend dynamically, and freezing breaks
    native extensions in ways that a successful import does not reveal — the
    same class of failure as the SSL trust store and the browser automation
    checks alongside it, both of which are in that self-test because a build
    that imported cleanly still died on a customer's machine.
    """
    import json

    path = paths.resource("licensing", "testdata", "vector.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            vector = json.load(f)
    except OSError as e:
        return False, f"test vector missing ({e})"

    try:
        claims = token.verify(vector["token"],
                              device_fp=vector["device_fp"],
                              public_keys={"vector": vector["public_key"]},
                              now=int(vector["claims"]["iat"]) + 10)
    except TokenError as e:
        return False, f"vector rejected: {e}"
    except Exception as e:                          # noqa: BLE001
        return False, f"crypto backend unusable: {e}"

    if claims != vector["claims"]:
        return False, "vector claims did not round-trip"
    return True, ""


def _hostname() -> str:
    """A human label for the seat list, so a customer asking *which* five
    machines are using their seats gets an answer."""
    import socket
    try:
        return socket.gethostname()[:64]
    except Exception:                               # noqa: BLE001
        return ""
