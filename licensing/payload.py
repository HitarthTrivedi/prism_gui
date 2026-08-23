"""Server-published configuration — format and verification.

The problem this exists to solve
────────────────────────────────
Prism reads answers out of pages it does not own. ChatGPT, Claude, Perplexity
and Gamma redesign whenever they like, often to a fraction of their users at a
time, and when the markup moves the selector that reads the reply stops
matching. Before this channel existed, fixing that meant building a new binary,
signing it, and persuading every customer to download and install it — days,
with the tool broken for everyone in the meantime, and a "Windows protected
your PC" dialog at the end of it. Now it is a row in a table.

    PRSMPv1.<b64url(payload_json)>.<b64url(ed25519_sig)>

Signed, and not as ceremony
───────────────────────────
This file's contents change what the app DOES. The rule the licensing design
holds to is that nothing in ~/.prism is ever acted on unverified — every field
comes out of a verify(), never out of the JSON on disk. An unsigned payload
cache would be a file sitting next to the app that rewrites its behaviour,
which is exactly the hole that removing the loose engine sources closed.

It carries data, not code — CSS selectors, nothing executable — so the worst a
forged one could do is stop a tool working, not run something. That is a real
distinction and it is still not a reason to skip the signature: the cost is one
Ed25519 verification, and the invariant is worth more than the exception.

Its own prefix, so a payload can never be replayed as a token or a lease, and
neither can be replayed as a payload.

Verification is DELIBERATELY strict about one more thing than the token is: a
payload that fails for any reason is discarded and the built-in configuration
is used. There is no degraded mode. A tool whose selectors are stale still
works exactly as well as the build shipped — which is the whole safety property
of this channel, and the reason a bad publish cannot brick anybody.
"""
from __future__ import annotations

import json
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Shared with the token verifier deliberately: the wire encoding is the same,
# and two implementations of unpadded base64url is two chances to disagree.
from .token import b64u_decode

PREFIX = "PRSMPv1"

#: Anything larger is not a selector list, it is somebody's mistake or an
#: attempt to fill the disk. Real payloads are a few hundred bytes.
MAX_BYTES = 256 * 1024


class PayloadError(Exception):
    """A payload we will not act on. Always non-fatal — the caller falls back
    to the built-in configuration and the app carries on."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def signing_input(payload_b64: str) -> bytes:
    """The exact bytes the signature covers, prefix included.

    Both signer and verifier MUST call this, and it must match the server's
    `signing.payload_signing_input` byte for byte.
    """
    return f"{PREFIX}.{payload_b64}".encode("utf-8")


def verify(blob: str, *, public_keys: dict[str, str],
           app_version: str = "", now: int | None = None) -> dict[str, Any]:
    """Check a payload and return its claims, or raise PayloadError.

    The signature is verified against the RAW base64 segment as it arrived,
    never against a re-serialisation of the parsed JSON — same rule, and same
    reason, as token.verify(): re-serialising introduces key-ordering and
    escaping differences between signer and verifier, and the resulting bugs
    appear only on some customers' machines.
    """
    now = int(time.time()) if now is None else now

    if not blob or len(blob) > MAX_BYTES:
        raise PayloadError("size", "Payload is missing or implausibly large.")

    parts = blob.strip().split(".")
    if len(parts) != 3:
        raise PayloadError("malformed", "Payload is not in the expected format.")
    version, payload_b64, sig_b64 = parts
    if version != PREFIX:
        raise PayloadError("version", f"Unsupported payload version {version!r}.")

    # Parsed before the signature check ONLY to read `kid` — nothing from here
    # is trusted or acted on until the verification below has passed.
    try:
        claims = json.loads(b64u_decode(payload_b64))
        signature = b64u_decode(sig_b64)
    except Exception:
        raise PayloadError("malformed", "Payload could not be decoded.")
    if not isinstance(claims, dict):
        raise PayloadError("malformed", "Payload claims are not an object.")

    verified = False
    for hex_key in public_keys.values():
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key)).verify(
                signature, signing_input(payload_b64))
            verified = True
            break
        except (InvalidSignature, ValueError):
            continue
    if not verified:
        raise PayloadError("signature", "Payload signature did not verify.")

    # Only now is any of this real.
    content = claims.get("content")
    if not isinstance(content, dict):
        raise PayloadError("shape", "Payload content is not an object.")

    minimum = str(claims.get("minv") or "")
    if minimum and app_version and _older(app_version, minimum):
        # Not an error: this is the escape hatch that lets a payload describe
        # something only newer builds understand. An old client is expected to
        # decline it and keep working from its own configuration.
        raise PayloadError("too_old",
                           f"Payload needs Prism {minimum}; this is {app_version}.")
    return claims


def _older(version: str, minimum: str) -> bool:
    def parts(text: str) -> tuple[int, ...]:
        out = []
        for chunk in str(text).split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return tuple(out)
    return parts(version) < parts(minimum)


def models_for(claims: dict[str, Any]) -> list[str]:
    """The Groq model chain in a verified payload.

    Here for the same reason selectors are: a hosted model gets retired on a
    few weeks' notice and every install carries the same list, so the day it
    goes, every customer stops being able to plan anything at the same hour.
    That already happened — three of the four models shipped in the built-in
    chain were dead, leaving one, in third place.

    Shipping a new chain used to mean a release everybody installs. Now it is
    a row, and it reaches them on their next check-in.

    Plain strings only, capped. A payload may add models; it can never make
    Prism call something that is not a model name.
    """
    models = claims.get("content", {}).get("models")
    if not isinstance(models, list):
        return []
    return [m.strip() for m in models[:12]
            if isinstance(m, str) and 0 < len(m.strip()) <= 80]


def selectors_for(claims: dict[str, Any]) -> dict[str, dict[str, str]]:
    """The per-agent overrides in a verified payload, filtered to what we allow.

    An allow-list, not a pass-through. The payload channel is a delivery
    mechanism for configuration, and the narrower the set of things it can
    change, the smaller the blast radius of a bad publish or a compromised
    signing key. Selectors and wait times are what breaks when a site is
    redesigned; a URL is not, and letting a payload rewrite `url` would let one
    point Prism's browser at somewhere the customer never agreed to.
    """
    allowed = {"response_selector", "textarea_selector", "submit_selector",
               "wait_time", "page_wait"}
    out: dict[str, dict[str, str]] = {}
    for name, over in (claims.get("content", {}).get("agents") or {}).items():
        if not isinstance(name, str) or not isinstance(over, dict):
            continue
        clean = {k: v for k, v in over.items()
                 if k in allowed and isinstance(v, (str, int))}
        if clean:
            out[name] = clean
    return out
