"""Licence token — format, signing input, and verification.

The token is the whole licensing design: the server signs a small claims blob,
the app verifies it offline against a public key baked into the build. That is
what lets Prism keep working on a site with no signal, and what stops our
server going down from bricking every customer at once.

Format (see docs/licensing/01-token-and-crypto.md):

    PRSMv1.<b64url(payload_json)>.<b64url(ed25519_sig)>

Deliberately NOT JWT. JWT carries an `alg` header, which exists to support
algorithm flexibility we do not want and has a long history of confusion
attacks ("alg": "none", RS256/HS256 swaps). This verifier does exactly one
thing — Ed25519 — and there is no field an attacker can use to ask for
anything else.

This module covers steps 1-7 of the verification algorithm: is the token
*genuine, intact and ours*. Whether it is still in date (step 8) is
`state.resolve()`'s job, because "expired" is a normal, expected condition that
the UI must handle gracefully, while everything here is either fine or an
attack.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PREFIX = "PRSMv1"

# Tolerance on `nbf`, in seconds. Machine clocks are routinely a few seconds
# out and NTP corrections land unpredictably; rejecting a token because the
# server was 4 seconds ahead would be a support ticket with no cause.
NBF_SKEW = 300


class TokenError(Exception):
    """A token that is malformed, forged, or for a different machine.

    Carries a stable `code` so callers can distinguish "this is not our token"
    from "this token is not for this computer" without parsing messages.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ── base64url, unpadded (RFC 4648 §5) ──────────────────────────────────────
def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    # Python's decoder demands correct padding; the wire format omits it.
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def signing_input(payload_b64: str) -> bytes:
    """The exact bytes the signature covers.

    The version prefix is included so a token can never be replayed under a
    future format version: a PRSMv1 signature will not verify as PRSMv2 even if
    the payload segment is byte-identical.

    Both the signer and the verifier MUST call this. That is the entire point
    of it being a function — see the warning on verify().
    """
    return f"{PREFIX}.{payload_b64}".encode("utf-8")


def verify(token: str, *, device_fp: str, public_keys: dict[str, str],
           now: int | None = None) -> dict[str, Any]:
    """Check a token's integrity and return its claims.

    Raises TokenError on anything suspicious. Does NOT check expiry — see the
    module docstring.

    ┌─────────────────────────────────────────────────────────────────────┐
    │ The signature is verified against the RAW base64 segment as it       │
    │ arrived on the wire, never against a re-serialisation of the parsed  │
    │ JSON. Re-serialising introduces key ordering, whitespace and unicode │
    │ escaping differences between signer and verifier; the resulting bugs │
    │ are intermittent, platform-dependent, and show up only on some       │
    │ customers' machines. Sign bytes, verify the same bytes.              │
    └─────────────────────────────────────────────────────────────────────┘
    """
    now = int(time.time()) if now is None else now

    # 1-2. Shape and version.
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise TokenError("malformed", "Licence token is not in the expected format.")
    version, payload_b64, sig_b64 = parts
    if version != PREFIX:
        raise TokenError("version", f"Unsupported licence token version {version!r}.")

    # 3. Decode and parse the claims. Done before signature verification only
    #    because we need `kid` to know which key to verify with — nothing from
    #    the payload is trusted or acted on until step 5 passes.
    try:
        claims = json.loads(b64u_decode(payload_b64))
    except (ValueError, binascii.Error) as e:
        raise TokenError("malformed", "Licence token payload is unreadable.") from e
    if not isinstance(claims, dict):
        raise TokenError("malformed", "Licence token payload is not an object.")

    # 4. Key lookup. An unknown kid means a token signed with a key this build
    #    does not know — a forgery, or a build too old for a rotated key.
    kid = claims.get("kid")
    pub_hex = public_keys.get(kid) if isinstance(kid, str) else None
    if not pub_hex:
        raise TokenError("unknown_key", "This licence was issued for a different "
                                        "version of Prism. Please update.")

    # 5. The signature itself.
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(b64u_decode(sig_b64), signing_input(payload_b64))
    except (InvalidSignature, ValueError, binascii.Error) as e:
        raise TokenError("bad_signature", "This licence file has been altered.") from e

    # 6. Bound to this machine. compare_digest rather than == out of habit
    #    rather than necessity — nothing here is a timing oracle, but licence
    #    identifiers are exactly the kind of thing that later grows a
    #    comparison that would be.
    tok_dev = claims.get("dev")
    if not isinstance(tok_dev, str) or not hmac.compare_digest(tok_dev, device_fp):
        raise TokenError("wrong_device", "This licence belongs to a different computer.")

    # 7. Not-before. A token from the future means either a badly wrong clock
    #    or someone winding one back to stretch a trial.
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and now < nbf - NBF_SKEW:
        raise TokenError("not_yet_valid", "This computer's clock appears to be wrong.")

    return claims
