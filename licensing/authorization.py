"""The authorisation lease cache, and the offline policy that reads it.

Pure logic and one file on disk. No network lives here — client.py owns HTTP
and licensing/__init__.py orchestrates the two, exactly as status.py and
token.py are arranged. That separation is what makes this testable without a
server and what keeps the policy readable in one screen.

    ~/.prism/license.json          the licence token   — "are you licensed?"
    ~/.prism/authorization.json    the lease           — "may you do this now?"

Two files rather than one because they have different lifetimes and different
failure modes. Losing the lease costs one round trip; losing the token costs a
re-activation. Wiping authorization.json is a legitimate support instruction
("sign out of protected features and back in"); wiping license.json is not.

────────────────────────────────────────────────────────────────────────────
What is stored, and what is emphatically not
────────────────────────────────────────────────────────────────────────────
The file holds the signed lease string and nothing that is trusted. It does
NOT hold `{"authorized": true}`. Every field acted on is read out of the
verified payload, after the Ed25519 signature has passed, on every single
read. There is no cached decision for anyone to edit — editing the file can
only turn a working lease into a rejected one.

────────────────────────────────────────────────────────────────────────────
The four lease states
────────────────────────────────────────────────────────────────────────────
    NONE      no lease cached                → ask the server
    FRESH     now < exp                      → proceed, no network
    GRACE     exp <= now < exp + off         → proceed, refresh in background
    STALE     now >= exp + off               → ask the server; refuse if it
                                               cannot be reached
    TAMPERED  forged, wrong machine, wrong
              licence, or a clock wound back → discard it and ask the server

`off` — the offline grace — is a SIGNED claim, set by the backend per licence.
It is not a local constant and not a config value, so a customer cannot widen
their own offline window by editing anything on their machine. That is the
whole difference between an offline policy and an honour system.

A network failure is not a licence failure. GRACE exists so that a flapping
connection, a laptop on a train, or our own host restarting does not stop
someone who has paid. STALE exists so that "offline" cannot be a permanent
operating mode for a licence that has been revoked.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from . import store
from .token import TokenError

FILENAME = "authorization.json"

NONE = "none"
FRESH = "fresh"
GRACE = "grace"
STALE = "stale"
TAMPERED = "tampered"

# Scopes. Free-form strings on the wire — the backend decides what it grants —
# but these are the ones the client asks for by name.
SCOPE_CORE = "core"          # planning and running the pipeline
SCOPE_WORKFLOW = "workflow"  # editing/queueing work that costs us nothing
SCOPE_GROK = "grok"          # Prism-operated model access (backend gateway)

_DEFAULT: dict[str, Any] = {
    "lease": "",
    # Purely diagnostic: when we last got one, and when we last tried. Used to
    # rate-limit retries so an unreachable server is not hammered once per
    # click. Never trusted for an authorisation decision.
    "fetched_at": 0,
    "last_attempt": 0,
}

# Don't re-ask a server that just refused to answer. A user clicking Start
# repeatedly during an outage should produce one request, not one per click.
RETRY_INTERVAL = 60


@dataclass(frozen=True)
class Lease:
    """A verified lease. Constructed only from claims that passed lease.verify."""

    license_id: str = ""
    device_id: str = ""
    scopes: frozenset[str] = field(default_factory=frozenset)
    features: frozenset[str] = field(default_factory=frozenset)
    metered: bool = False
    issued_at: int = 0
    expires_at: int = 0
    offline_seconds: int = 0
    jti: str = ""
    version: int = 0
    # The raw signed string, so a protected backend call can present it and
    # have the BACKEND re-verify rather than taking the client's word.
    raw: str = ""

    @property
    def hard_expiry(self) -> int:
        """When this lease stops being usable even offline."""
        return self.expires_at + self.offline_seconds

    def state(self, now: int | None = None) -> str:
        now = int(time.time()) if now is None else now
        if now < self.expires_at:
            return FRESH
        if now < self.hard_expiry:
            return GRACE
        return STALE

    def allows(self, scope: str) -> bool:
        """Scope membership only — NOT temporal. Callers go through
        decide(), which checks both; this exists so the two questions cannot
        be accidentally conflated at a call site."""
        return not scope or scope in self.scopes


@dataclass(frozen=True)
class Decision:
    """The answer for one protected operation."""

    allowed: bool
    state: str = NONE
    scope: str = ""
    # True when the caller should go to the server before proceeding. Distinct
    # from `allowed`: a GRACE decision is allowed AND wants a refresh.
    needs_server: bool = False
    message: str = ""
    code: str = ""
    lease: Lease | None = None

    def __bool__(self) -> bool:
        return self.allowed


def from_claims(claims: dict[str, Any], raw: str = "") -> Lease:
    """Verified claims → Lease. Assumes lease.verify() has passed."""
    scopes = claims.get("scope") or []
    feats = claims.get("feat") or []
    return Lease(
        license_id=str(claims.get("lid") or ""),
        device_id=str(claims.get("dev") or ""),
        scopes=frozenset(s for s in scopes if isinstance(s, str)),
        features=frozenset(f for f in feats if isinstance(f, str)),
        metered=bool(claims.get("mtr")),
        issued_at=int(claims.get("iat") or 0),
        expires_at=int(claims.get("exp") or 0),
        offline_seconds=max(int(claims.get("off") or 0), 0),
        jti=str(claims.get("jti") or ""),
        version=int(claims.get("ver") or 0),
        raw=raw,
    )


# ── the file ───────────────────────────────────────────────────────────────
def path(user_dir: str) -> str:
    return os.path.join(user_dir, FILENAME)


def load(user_dir: str) -> dict[str, Any]:
    """Read the cache. A missing, truncated or hand-edited file resolves to
    "no lease", never to a crash — the file is user-writable and always will
    be."""
    return store.read_json(path(user_dir), _DEFAULT)


def save(user_dir: str, data: dict[str, Any]) -> None:
    store.write_json(path(user_dir), {**_DEFAULT, **data})


def remember(user_dir: str, lease_str: str, *, now: int | None = None) -> None:
    """Cache a lease the server just issued.

    Called only after lease.verify() has passed on it. Caching something we
    have not verified would mean a bad deploy could poison every client's
    cache with a lease none of them can use, and the only cure would be
    telling customers to delete a file.
    """
    now = int(time.time()) if now is None else now
    save(user_dir, {"lease": lease_str, "fetched_at": now, "last_attempt": now})


def note_attempt(user_dir: str, now: int | None = None) -> None:
    """Record that we tried and failed, so RETRY_INTERVAL can throttle."""
    now = int(time.time()) if now is None else now
    data = load(user_dir)
    data["last_attempt"] = now
    save(user_dir, data)


def clear(user_dir: str) -> None:
    """Forget the lease. Deactivation, and any TAMPERED verdict, go through
    here — a lease that failed verification must not sit on disk being
    re-verified and re-failing on every click."""
    try:
        os.unlink(path(user_dir))
    except OSError:
        pass


def may_retry(user_dir: str, now: int | None = None) -> bool:
    now = int(time.time()) if now is None else now
    return now - int(load(user_dir).get("last_attempt") or 0) >= RETRY_INTERVAL


# ── reading it back ────────────────────────────────────────────────────────
def current(user_dir: str, *, device_fp: str, public_keys: dict[str, str],
            license_id: str = "", now: int | None = None
            ) -> tuple[Lease | None, str]:
    """The cached lease and its state, or (None, NONE | TAMPERED).

    Verifies the signature on every read. That costs a few hundred
    microseconds and removes any possibility of a trusted-but-unchecked cache,
    which is the only reason a local file can be part of a security design at
    all.
    """
    from . import lease as lease_mod        # deferred: keeps import order flat

    raw = (load(user_dir).get("lease") or "").strip()
    if not raw:
        return None, NONE
    try:
        claims = lease_mod.verify(raw, device_fp=device_fp,
                                  public_keys=public_keys,
                                  license_id=license_id, now=now)
    except TokenError:
        # Forged, for another machine, for another licence, or a clock wound
        # back far enough to break `nbf`. Any of those means the cache is
        # worthless; drop it rather than re-failing on every call.
        clear(user_dir)
        return None, TAMPERED
    lease_obj = from_claims(claims, raw)
    return lease_obj, lease_obj.state(now)


def decide(lease_obj: Lease | None, state: str, scope: str,
           *, server_reachable: bool = True) -> Decision:
    """The offline policy, in one place.

    `server_reachable` is what the CALLER has just observed, not a guess: it
    is False only after a request has actually failed. That distinction is the
    whole point — an arbitrary network failure must not equal a licence
    failure, but neither may "I did not bother asking" become a permanent
    offline mode.
    """
    if lease_obj is None or state in (NONE, TAMPERED):
        return Decision(False, state=state, scope=scope, needs_server=True,
                        code="NO_LEASE",
                        message="Prism needs to check this with the licence "
                                "server before it can start.")

    if not lease_obj.allows(scope):
        # In date, genuinely signed — and simply does not cover this. A new
        # lease will not help unless the licence itself changes, so this is a
        # definite no rather than a reason to go to the network.
        return Decision(False, state=state, scope=scope, needs_server=False,
                        code="SCOPE_NOT_GRANTED",
                        message="That isn't part of your licence.")

    if state == FRESH:
        return Decision(True, state=state, scope=scope, lease=lease_obj)

    if state == GRACE:
        # Past expiry but inside the backend-signed offline window. Proceed,
        # and tell the caller to renew in the background — this is the state
        # that makes a flaky connection a non-event rather than an outage.
        return Decision(True, state=state, scope=scope, needs_server=True,
                        lease=lease_obj)

    # STALE. The offline window is spent. If the server is answering, the
    # caller should have refreshed before asking us; if it is not, this is
    # where offline operation stops.
    return Decision(
        False, state=state, scope=scope, needs_server=True, lease=lease_obj,
        code="LEASE_STALE",
        message=("Prism couldn't reach the licence server, and this "
                 "computer's offline allowance is used up.\n\nConnect to the "
                 "internet and try again. Everything you've already produced "
                 "is still in History.")
        if not server_reachable else
        ("Prism needs to re-check your licence before starting new work."))
