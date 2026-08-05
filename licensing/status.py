"""What the app is allowed to do right now.

Step 8 of verification — the temporal part — plus the shape the rest of the app
reads. Kept separate from token.py because expiry is a normal, expected
condition that the UI has to handle kindly, while a bad signature is an attack.

The five states:

    none      no licence at all            → activation screen, nothing else
    valid     verified and in date         → full access to `features`
    grace     past exp, inside grace       → full access + countdown banner
    expired   past exp + grace             → read-only: History and Setup only
    tampered  forged, wrong machine,
              or a wound-back clock        → read-only until an online refresh

Read-only means the app still opens and the customer can still reach every
piece of work they have already produced. Only new runs and add-ons stop. A
customer locked out of their own past BOQ output does not renew — they file a
complaint, and they are right to.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

NONE = "none"
VALID = "valid"
GRACE = "grace"
EXPIRED = "expired"
TAMPERED = "tampered"

DAY = 86400

# How far the clock may run backwards before we stop believing it. Generous on
# purpose: timezone changes, DST, a dead CMOS battery on a new site machine and
# a first boot before NTP are all real and innocent. Falsely accusing a paying
# customer of tampering is far worse than missing a rollback — and the rollback
# gains little anyway, because tokens only live seven days.
CLOCK_TOLERANCE = DAY


@dataclass(frozen=True)
class LicenseState:
    status: str = NONE
    plan: str = ""
    customer: str = ""
    kind: str = ""
    features: frozenset[str] = field(default_factory=frozenset)
    seats: int = 0
    license_id: str = ""
    # The date the customer was promised. ALWAYS the one shown in the UI.
    license_ends: int = 0
    # When this particular token dies. Internal — never shown. A customer told
    # "expires in 4 days" on day 3 of a 10-day trial will telephone you.
    token_expires: int = 0
    grace_days: int = 0
    payload_key: str = ""
    payload_etag: str = ""
    message: str = ""

    @property
    def usable(self) -> bool:
        """May the customer start new work?"""
        return self.status in (VALID, GRACE)

    @property
    def days_left(self) -> int:
        """Days until the licence ends, rounded UP. Negative once it has.

        Rounding up, not down: a 7-day trial is 7 days minus a few seconds the
        instant it is activated, and flooring that shows "6 days left" on a
        licence we just told the customer was seven. Rounding up means the
        count matches the number in our email on day one and still reads
        "1 day left" through the whole final day.
        """
        if not self.license_ends:
            return 0
        return math.ceil((self.license_ends - time.time()) / DAY)

    def has(self, feature: str) -> bool:
        return self.usable and feature in self.features


def resolve(claims: dict[str, Any], *, now: int | None = None) -> LicenseState:
    """Turn verified claims into a state. Assumes token.verify() has passed."""
    now = int(time.time()) if now is None else now

    exp = int(claims.get("exp") or 0)
    grace_days = int(claims.get("grace") or 0)
    # A trial is issued with grace 0, so this collapses to a hard stop on the
    # day the customer was told — which is the whole point of the field.
    grace_until = exp + grace_days * DAY

    if now < exp:
        status = VALID
    elif now < grace_until:
        status = GRACE
    else:
        status = EXPIRED

    feats = claims.get("feat") or []
    return LicenseState(
        status=status,
        plan=str(claims.get("plan") or ""),
        customer=str(claims.get("cust") or ""),
        kind=str(claims.get("kind") or ""),
        features=frozenset(f for f in feats if isinstance(f, str)),
        seats=int(claims.get("seats") or 0),
        license_id=str(claims.get("sub") or ""),
        # `lend` is the licence end; fall back to the token's own expiry for
        # tokens minted before that claim existed.
        license_ends=int(claims.get("lend") or exp),
        token_expires=exp,
        grace_days=grace_days,
        payload_key=str(claims.get("pk") or ""),
        payload_etag=str(claims.get("petag") or ""),
    )


def none(message: str = "") -> LicenseState:
    return LicenseState(status=NONE, message=message)


def tampered(message: str) -> LicenseState:
    return LicenseState(status=TAMPERED, message=message)


def clock_rolled_back(last_seen: int, now: int | None = None) -> bool:
    """Has the system clock moved backwards past what we have already seen?

    A speed bump, not a control: license.json is user-writable and always will
    be. The real limit on backdating is that a token is only good for seven
    days, so a rollback buys nothing without also blocking the refresh that
    would replace it.
    """
    now = int(time.time()) if now is None else now
    return bool(last_seen) and now < last_seen - CLOCK_TOLERANCE
