"""Authorisation lease — format, signing input, and verification.

The licence token (token.py) answers one question:

    "Is this Prism installation licensed?"

This answers a different one:

    "Is this licensed Prism client authorised to perform protected
     operations *right now*?"

They are deliberately separate. A licence token lives for hours or days and is
what keeps the app open and its padlocks honest. A lease lives for about half
an hour, names the exact scopes the backend granted, and is what a protected
operation is checked against. Conflating them was the original design's real
weakness: the only way to get a live answer was a blocking round trip on every
single plan, so "live authorisation" and "instant" were mutually exclusive.

Format — same shape as the licence token, different prefix:

    PRSMLv1.<b64url(payload_json)>.<b64url(ed25519_sig)>

Not JWT, for the same reason token.py is not: no `alg` header means no
algorithm-confusion attack surface. This verifier does Ed25519 and nothing else.

Why a signed lease rather than a cached boolean
───────────────────────────────────────────────
The server used to answer `{"allowed": true}`. That is a *claim*, not a
*proof* — a modified client can synthesise it in one line, and so can anything
that replaces licensing/client.py. A lease is signed with a private key that
exists only on the backend, so a client can cache it, read it, and check it,
but cannot manufacture one. The signature is the security boundary; the cache
is only a performance decision.

Payload claims
──────────────
    kid    signing key id, as in the licence token
    lid    licence id this lease was issued for
    dev    device fingerprint — a lease is useless on another machine
    scope  list of granted scopes: "core", "workflow", add-on features, "grok"
    feat   the AUTHORITATIVE entitlement list. plans.py is presentation only;
           this is what the backend actually sold them.
    mtr    true when this licence is metered, so the client must ask the
           server for a quota'd action rather than spending the lease
    iat    issued at
    nbf    not before
    exp    expiry — normal validity ends here
    off    offline grace, in seconds AFTER exp. Signed rather than configured
           locally, so a customer cannot widen their own offline window by
           editing a file.
    jti    unique lease id, for server-side revocation and audit
    ver    payload version, so this can grow without breaking old clients

This module covers only "is this lease genuine, intact, and ours". Whether it
is still in date is authorization.py's job — exactly the split token.py and
status.py already use, and for the same reason: expiry is a normal condition
the UI must handle gracefully, while a bad signature is an attack.
"""
from __future__ import annotations

import binascii
import hmac
import json
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .token import TokenError, b64u_decode, b64u_encode  # noqa: F401

PREFIX = "PRSMLv1"

# Payload version this build understands. A lease claiming a HIGHER version is
# refused rather than partially honoured: a future backend that adds a
# restricting claim (a usage cap, a narrower scope grammar) must not have that
# claim silently ignored by an old client, which is precisely how a
# "compatible" change becomes a bypass.
VERSION = 1

# Same tolerance as the licence token, for the same reason: machine clocks are
# routinely a few seconds out and an NTP correction must not read as an attack.
NBF_SKEW = 300


def signing_input(payload_b64: str) -> bytes:
    """The exact bytes the signature covers.

    Includes the version prefix, which is what stops a lease and a licence
    token being replayed as each other — their prefixes differ, so a PRSMv1
    signature will never verify here and a PRSMLv1 signature will never verify
    as a licence token. Both the signer (the backend) and this verifier MUST
    call this.
    """
    return f"{PREFIX}.{payload_b64}".encode("utf-8")


def looks_like_one(text: str) -> bool:
    """Cheap shape check, before spending a signature verification on it."""
    return (text or "").strip().startswith(PREFIX + ".")


def encode_payload(claims: dict[str, Any]) -> str:
    """Claims → payload segment. Canonical JSON: sorted keys, no spaces.

    Here rather than only on the backend so the signer and the verifier agree
    on the encoding in one committed place — the same arrangement
    designation.py uses, and the reason its signer and verifier have never
    drifted.
    """
    return b64u_encode(json.dumps(claims, separators=(",", ":"),
                                  sort_keys=True).encode("utf-8"))


def verify(lease: str, *, device_fp: str, public_keys: dict[str, str],
           license_id: str = "", now: int | None = None) -> dict[str, Any]:
    """Check a lease's integrity and return its claims.

    Raises TokenError on anything suspicious. Does NOT check `exp` — see the
    module docstring.

    The signature is verified against the RAW base64 segment as it arrived,
    never against a re-serialisation of the parsed JSON. Re-serialising
    introduces key-ordering and escaping differences between signer and
    verifier, and the resulting bugs appear only on some customers' machines.
    """
    now = int(time.time()) if now is None else now

    # 1-2. Shape and version prefix.
    parts = (lease or "").strip().split(".")
    if len(parts) != 3:
        raise TokenError("malformed",
                         "Authorisation lease is not in the expected format.")
    version, payload_b64, sig_b64 = parts
    if version != PREFIX:
        raise TokenError("version",
                         f"Unsupported authorisation lease version {version!r}.")

    # 3. Decode. Parsed before the signature check only to find `kid` — nothing
    #    in here is trusted or acted on until step 5 passes.
    try:
        claims = json.loads(b64u_decode(payload_b64))
    except (ValueError, binascii.Error) as e:
        raise TokenError("malformed",
                         "Authorisation lease payload is unreadable.") from e
    if not isinstance(claims, dict):
        raise TokenError("malformed",
                         "Authorisation lease payload is not an object.")

    # 4. Key lookup. An unknown kid means a lease signed with a key this build
    #    does not know — a forgery, or a build too old for a rotated key.
    kid = claims.get("kid")
    pub_hex = public_keys.get(kid) if isinstance(kid, str) else None
    if not pub_hex:
        raise TokenError("unknown_key",
                         "This authorisation was issued for a different "
                         "version of Prism. Please update.")

    # 5. The signature itself. Everything below this line is now trustworthy.
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(b64u_decode(sig_b64), signing_input(payload_b64))
    except (InvalidSignature, ValueError, binascii.Error) as e:
        raise TokenError("bad_signature",
                         "This authorisation has been altered.") from e

    # 6. Payload version. Refuse anything newer than we understand — see the
    #    note on VERSION.
    ver = claims.get("ver")
    if not isinstance(ver, int) or ver > VERSION:
        raise TokenError("version",
                         "This authorisation needs a newer version of Prism.")

    # 7. Bound to this machine. A lease copied to another laptop is worthless,
    #    which is what stops one paid seat authorising an office.
    dev = claims.get("dev")
    if not isinstance(dev, str) or not hmac.compare_digest(dev, device_fp):
        raise TokenError("wrong_device",
                         "This authorisation belongs to a different computer.")

    # 8. Bound to the licence currently on this machine, when we know it. Stops
    #    a lease surviving a licence being replaced — re-activating on a
    #    different licence must not inherit the old one's authorisation.
    lid = claims.get("lid")
    if not isinstance(lid, str) or not lid:
        raise TokenError("malformed",
                         "Authorisation lease is missing its licence id.")
    if license_id and not hmac.compare_digest(lid, license_id):
        raise TokenError("wrong_licence",
                         "This authorisation belongs to a different licence.")

    # 9. Not-before. A lease from the future means a badly wrong clock, or one
    #    wound back to stretch an offline window.
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and now < nbf - NBF_SKEW:
        raise TokenError("not_yet_valid",
                         "This computer's clock appears to be wrong.")

    # 10. Structural fields the caller will read without re-checking.
    if not isinstance(claims.get("exp"), (int, float)):
        raise TokenError("malformed",
                         "Authorisation lease has no expiry.")
    if not isinstance(claims.get("jti"), str) or not claims["jti"]:
        raise TokenError("malformed",
                         "Authorisation lease is missing its identifier.")

    return claims


def build_claims(*, kid: str, license_id: str, device_fp: str,
                 scope: list[str], features: list[str], metered: bool,
                 jti: str, now: int, ttl: int, offline: int) -> dict[str, Any]:
    """The payload the backend signs.

    Lives here, in the client, for the same reason designation.build_claims
    does: one committed definition of the field names that both sides import,
    so a rename cannot land on one side only. The backend mirrors this
    function — it does NOT import it — because the two are separate deployables.
    """
    return {
        "kid": kid,
        "lid": license_id,
        "dev": device_fp,
        "scope": sorted(set(scope)),
        "feat": sorted(set(features)),
        "mtr": bool(metered),
        "iat": int(now),
        "nbf": int(now),
        "exp": int(now) + int(ttl),
        "off": int(offline),
        "jti": jti,
        "ver": VERSION,
    }
