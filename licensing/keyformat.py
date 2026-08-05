"""The licence key the customer actually types.

    PRSM-4K2XA-9WQ7M-3TYRB-8HNVE

Crockford Base32 — no I, L, O or U — so nothing is ambiguous when it is read
out over the phone, which will happen. Input is normalised before checking:
uppercased, punctuation stripped, and the characters people reliably mistype
(I and L for 1, O for zero) mapped to what they meant.

The last character is a checksum, so a typo is caught in the dialog, offline,
before any network call. 95 bits of entropy remain in the other nineteen, and
the activate endpoint is rate-limited, so guessing is not a route in.
"""
from __future__ import annotations

import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIX = "PRSM"
BODY_LEN = 20                       # 19 random + 1 checksum
GROUP = 5

# What people type instead of what they meant.
_CONFUSIONS = str.maketrans({"I": "1", "L": "1", "O": "0", "U": "V"})


def normalise(text: str) -> str:
    """Anything the user could plausibly paste → the canonical form."""
    cleaned = "".join(ch for ch in (text or "").upper() if ch.isalnum())
    cleaned = cleaned.translate(_CONFUSIONS)
    # The prefix survives the confusion mapping unchanged (no I/L/O/U in
    # "PRSM"), so it is safe to strip and re-add afterwards.
    if cleaned.startswith(PREFIX):
        cleaned = cleaned[len(PREFIX):]
    return PREFIX + cleaned


def _checksum(body19: str) -> str:
    return ALPHABET[sum(ALPHABET.index(c) for c in body19) % len(ALPHABET)]


def is_well_formed(text: str) -> bool:
    """Structurally valid and self-consistent. Says nothing about whether the
    server has ever heard of it."""
    key = normalise(text)
    body = key[len(PREFIX):]
    if len(body) != BODY_LEN:
        return False
    if any(c not in ALPHABET for c in body):
        return False
    return body[-1] == _checksum(body[:-1])


def format_display(text: str) -> str:
    """Canonical form → the hyphenated shape used in emails and the UI."""
    body = normalise(text)[len(PREFIX):]
    groups = [body[i:i + GROUP] for i in range(0, len(body), GROUP)]
    return "-".join([PREFIX] + [g for g in groups if g])


def generate() -> str:
    """Mint a new key. Belongs to the server; here so the dev tools and the
    tests share one implementation with the verifier."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(BODY_LEN - 1))
    return format_display(PREFIX + body + _checksum(body))
