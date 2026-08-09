"""The second key: who this person is, and what job they do.

A company activates Prism with ONE company key (licensing/keyformat.py, the
PRSM-… one everybody types). That says the firm has paid. It says nothing
about which of the firm's people is sitting in front of this particular
laptop, and that is what decides which folder they can open.

So each member also gets a designation key, which we mint and send them:

    PRSD1.<b64url(payload)>.<b64url(signature)>

Same Ed25519 signing key as the licence token, same verifier helpers, same
"sign bytes, verify the same bytes" rule. Three properties matter:

  · It cannot be forged. Minting needs our private key. A member cannot
    promote themselves to Manager by editing a settings file, retyping a key,
    or reading another member's key and changing the role inside it — any of
    those breaks the signature.

  · It is useless on its own. The payload names the licence it belongs to, and
    activation refuses a designation key whose `org` does not match the
    company licence already on the machine. A key that leaks out of one
    customer does nothing at another.

  · It verifies offline. No call to us when a member starts work, which is the
    same promise the licence token makes and for the same reason.

Deliberately NOT bound to a device fingerprint, unlike the licence token. A
designation key is a person, and people change laptops; the licence is what
counts seats. Binding both would mean re-issuing someone's identity every time
IT hands them a new machine.

Payload claims
──────────────
    kid    signing key id, as in the licence token
    org    the licence id this belongs to (matches the token's `sub`)
    mid    member id — stable, and the name of their workspace folder
    role   a key from roles.ROLES
    name   the person's name, for the manager's profile switcher
    iat    issued at
"""
from __future__ import annotations

import binascii
import hmac
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .token import TokenError, b64u_decode, b64u_encode

PREFIX = "PRSD1"


def signing_input(payload_b64: str) -> bytes:
    """The exact bytes the signature covers.

    Includes the version prefix, which also means a designation key and a
    licence token can never be replayed as each other: their prefixes differ,
    so a PRSMv1 signature will not verify here and vice versa. Both the signer
    (devtools/mint.py) and this verifier must call this function.
    """
    return f"{PREFIX}.{payload_b64}".encode("utf-8")


def looks_like_one(text: str) -> bool:
    """Cheap shape check, so the dialog can tell a designation key from a
    company key before deciding which field the user pasted into."""
    return (text or "").strip().startswith(PREFIX + ".")


def verify(key: str, *, org: str, public_keys: dict[str, str]) -> dict[str, Any]:
    """Check a designation key and return its claims.

    `org` is the licence id from the company licence already activated on this
    machine. Raises TokenError on anything wrong; never returns a partially
    trusted result.
    """
    parts = (key or "").strip().split(".")
    if len(parts) != 3:
        raise TokenError("malformed",
                         "That doesn't look like a designation key.")
    version, payload_b64, sig_b64 = parts
    if version != PREFIX:
        raise TokenError("version",
                         f"Unsupported designation key version {version!r}.")

    # Parsed before the signature is checked only to find `kid`. Nothing in
    # here is trusted or acted on until the verify below passes.
    try:
        claims = json.loads(b64u_decode(payload_b64))
    except (ValueError, binascii.Error) as e:
        raise TokenError("malformed",
                         "That designation key is unreadable.") from e
    if not isinstance(claims, dict):
        raise TokenError("malformed",
                         "That designation key is not in the expected format.")

    kid = claims.get("kid")
    pub_hex = public_keys.get(kid) if isinstance(kid, str) else None
    if not pub_hex:
        raise TokenError("unknown_key",
                         "That designation key was issued for a different "
                         "version of Prism. Please update.")

    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(b64u_decode(sig_b64), signing_input(payload_b64))
    except (InvalidSignature, ValueError, binascii.Error) as e:
        raise TokenError("bad_signature",
                         "That designation key has been altered.") from e

    # Bound to the company licence. This is what stops a key from one customer
    # working at another, and what stops a member keeping their old role key
    # after the firm's licence is re-issued.
    claim_org = claims.get("org")
    if not isinstance(claim_org, str) or not hmac.compare_digest(claim_org, org):
        raise TokenError(
            "wrong_org",
            "That designation key belongs to a different company licence.")

    for field in ("mid", "role"):
        if not isinstance(claims.get(field), str) or not claims[field].strip():
            raise TokenError("malformed",
                             "That designation key is missing information.")
    return claims


def build_claims(*, org: str, mid: str, role: str, name: str,
                 kid: str, now: int) -> dict[str, Any]:
    """The payload minting signs. Here rather than in devtools/mint.py so the
    signer and the verifier agree on the field names in one place."""
    return {"kid": kid, "org": org, "mid": mid, "role": role,
            "name": name, "iat": int(now)}


def encode_payload(claims: dict[str, Any]) -> str:
    """Claims → the payload segment. Canonical JSON: sorted keys, no spaces."""
    return b64u_encode(json.dumps(claims, separators=(",", ":"),
                                  sort_keys=True).encode("utf-8"))
