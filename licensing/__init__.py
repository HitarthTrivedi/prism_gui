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

import os
import threading
from typing import Any, Callable

import app_meta
import paths

from . import (client, device, keyformat, keys, meter, status as _status,
               store, token)
from .client import ServerError, Unreachable
from .status import (EXPIRED, GRACE, NONE, STALE, TAMPERED,  # noqa: F401
                     VALID, LicenseState)
from .token import TokenError

# NB: the module is status.py, not state.py, because this package also exposes
# a state() function — and a submodule and a function of the same name means
# `from licensing import state` silently hands back whichever won the import,
# which is the sort of thing that is only ever debugged once.

__all__ = [
    "state", "has", "require", "activate", "deactivate", "refresh",
    "authorize", "report_usage", "Authorization", "meter",
    "set_paywall_handler", "device_fingerprint", "reload", "user_dir",
    "LicenseState", "ServerError", "Unreachable", "TokenError", "keyformat",
    "NONE", "VALID", "GRACE", "STALE", "EXPIRED", "TAMPERED",
]

_lock = threading.Lock()
_cached: LicenseState | None = None
_paywall: Callable[[str, Any, LicenseState], None] | None = None


def _offline_dev() -> bool:
    """PRISM_LICENSE_OFFLINE_DEV — run against a minted token, no server.

    Exists so that working on a dialog does not require uvicorn in another
    terminal. Honoured ONLY when running from source: in a frozen build this
    returns False no matter what the environment says, exactly like the
    PRISM_LICENSE_SERVER override and the DEVELOPMENT keys in keys.py.

    If it were readable in a release build it would be a total bypass of the
    licensing system, settable by any customer with an environment variable.
    That is why the frozen check comes first and there is no way to reorder it.
    """
    if paths.is_frozen():
        return False
    return bool(os.environ.get("PRISM_LICENSE_OFFLINE_DEV"))


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
            "This computer's date and time look wrong — the clock has gone "
            "backwards.\n\nCheck the date and time in your computer's "
            "settings and set them to update automatically, then connect to "
            "the internet so Prism can re-check your licence.")

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


# ── live authorisation & metering ──────────────────────────────────────────
class Authorization:
    """The server's answer for one run or one add-on."""

    def __init__(self, allowed: bool, run_id: str = "", message: str = "",
                 code: str = ""):
        self.allowed = allowed
        self.run_id = run_id
        self.message = message
        self.code = code

    def __bool__(self) -> bool:
        return self.allowed


def authorize(feature: str = "core", action: str = "run") -> Authorization:
    """Ask the server whether this may go ahead, right now.

    **There is no offline fallback.** If the licence server cannot be reached,
    the answer is no. That is a deliberate product decision: Prism needs the
    internet regardless — it calls Groq for every plan and drives claude.ai
    through a browser — so a customer who cannot reach us cannot do useful
    work anyway, and the alternative is a window in which a revoked or expired
    licence keeps running.

    The cost is real and is being paid on purpose: our availability is now our
    customers' availability. That is why the licence server is deliberately
    tiny (three endpoints, one table's worth of writes per run) and hosted
    accordingly.

    Called at the START of a run or add-on — never during one. A pipeline is
    tens of minutes of browser automation, and failing it part-way would
    discard real work for a reason the customer cannot act on.
    """
    current = state()
    if current.status == NONE:
        return Authorization(False, message="Prism isn't activated on this "
                                            "computer yet.", code="NONE")

    data = store.load(user_dir())
    license_id = data.get("license_id") or current.license_id
    if license_id:
        try:
            response = client.authorize(
                license_id, device_fingerprint(),
                app_version=app_meta.VERSION, action=action, feature=feature)
            _apply(response)
            return Authorization(True, run_id=response.get("run_id", ""))
        except ServerError as e:
            if e.code == "DEVICE_NOT_ACTIVATED" and data.get("key"):
                # A seat released by mistake. Heal it and try once more.
                try:
                    activate(data["key"])
                    response = client.authorize(
                        license_id, device_fingerprint(),
                        app_version=app_meta.VERSION, action=action,
                        feature=feature)
                    _apply(response)
                    return Authorization(True, run_id=response.get("run_id", ""))
                except (ServerError, Unreachable):
                    pass
            # A definite no — revoked, expired, add-on not licensed. The
            # server's wording is customer-facing copy; show it as-is.
            return Authorization(False, message=e.message, code=e.code)
        except Unreachable:
            if _offline_dev():
                # Working on the UI shouldn't require running uvicorn. Source
                # builds only — see _offline_dev().
                if not feature or has(feature):
                    return Authorization(True, run_id="dev")
                return Authorization(False, code="FEATURE_NOT_LICENSED",
                                     message="Not in this dev licence.")
            # Name the address. Without it this message is the same whether
            # the network is down, a firewall is in the way, or the build is
            # simply pointed at a server that does not exist yet — and those
            # need completely different fixes.
            return Authorization(
                False, code="UNREACHABLE",
                message=f"Prism couldn't reach the licence server at "
                        f"{client.server_url()}, so it can't start new work "
                        "right now.\n\nCheck this computer's internet "
                        "connection and try again. Everything you've already "
                        "produced is still in History.")

    # No licence id at all — never activated, or the file was cleared.
    return Authorization(False, code=state().status,
                         message="Prism isn't activated on this computer.")


def report_usage(run_id: str = "") -> None:
    """Send buffered usage. Fire-and-forget; never blocks, never raises.

    Nothing the customer does depends on this arriving, so a failure puts the
    events back on the buffer for the next attempt rather than surfacing.
    """
    threading.Thread(target=_send_usage, args=(run_id,),
                     name="prism-usage", daemon=True).start()


def _send_usage(run_id: str = "") -> None:
    events = meter.drain()
    if not events:
        return
    try:
        data = store.load(user_dir())
        license_id = data.get("license_id") or state().license_id
        if not license_id:
            return
        client.usage(license_id, device_fingerprint(),
                     app_version=app_meta.VERSION, run_id=run_id,
                     events=events)
    except Exception:                               # noqa: BLE001
        meter.restore(events)


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
