"""
Prism Sales Automation — verify: confirm (or scrap) the e-mail with Hunter
──────────────────────────────────────────────────────────────────────────
Enrich builds a PATTERN address (firstname.lastname@real-domain) and checks
only that the domain accepts mail — not that the mailbox exists. This stage,
when the seller has brought a Hunter.io key, closes that gap:

  1. Ask Hunter's Email Finder for the REAL address at the company domain — if
     Hunter knows the person, this fixes a wrong-pattern guess outright, and the
     finder already carries a verification status.
  2. If the finder draws a blank, VERIFY the pattern address we built — so even
     an unknown person's guessed address is confirmed or scrapped.

Two deliberate limits, both honest:
  · **BYO-key.** No Hunter key → this stage is skipped and nothing changes; the
    sheet keeps its free MX check.
  · **The qualified slice only.** Hunter's free tier is ~50 finder searches /
    100 verifications a month — nowhere near a 2,000-row list. So we spend it
    where a bad address costs a bounce and sender reputation: the hot/warm
    leads about to be emailed. An LLM cannot do this (it can't probe a mailbox);
    a dedicated verifier is the only honest way.
"""
from __future__ import annotations

import os
import re

from .models import HOT, WARM

FINDER = "https://api.hunter.io/v2/email-finder"
VERIFIER = "https://api.hunter.io/v2/email-verifier"

# Hunter status -> the Email-check value the leads/hotlist sheets colour-code on.
_MAP = {"valid": "valid", "invalid": "invalid", "accept_all": "catch-all",
        "webmail": "unknown", "disposable": "unknown", "unknown": "unknown"}

ZB_VALIDATE = "https://api.zerobounce.net/v2/validate"
# ZeroBounce status -> the Email-check value the sheets colour-code on.
_ZB_MAP = {"valid": "valid", "invalid": "invalid", "catch-all": "catch-all",
           "catchall": "catch-all", "unknown": "unknown", "spamtrap": "invalid",
           "abuse": "unknown", "do-not-mail": "unknown"}


def hunter_key(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    return (cfg.get("hunter_api_key") or os.environ.get("HUNTER_API_KEY") or "").strip()


def zerobounce_key(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    return (cfg.get("zerobounce_api_key")
            or os.environ.get("ZEROBOUNCE_API_KEY") or "").strip()


def _name_parts(name: str):
    p = re.sub(r"[^A-Za-z ]", "", name or "").split()
    return (p[0], p[-1]) if len(p) >= 2 else ("", "")


def _domain_of(lead) -> str:
    return ((lead.extra or {}).get("company_domain")
            or (lead.email.split("@")[-1] if "@" in (lead.email or "") else ""))


def _get(url: str, params: dict, timeout: int = 40) -> dict:
    import requests
    try:
        return requests.get(url, params=params, timeout=timeout).json() or {}
    except Exception:                                   # noqa: BLE001
        return {}


def _zb_validate(email: str, key: str) -> str:
    j = _get(ZB_VALIDATE, {"api_key": key, "email": email, "ip_address": ""})
    return _ZB_MAP.get((j.get("status") or "").lower().replace("_", "-"), "")


def _reoon_validate(email: str, key: str) -> str:
    j = _get("https://emailverifier.reoon.com/api/v1/verify",
             {"email": email, "key": key, "mode": "power"})
    s = (j.get("status") or "").lower()
    if j.get("is_disposable") or s in ("disposable", "spamtrap"):
        return "invalid"                         # throwaway/trap → never send
    if j.get("is_catch_all") or "catch" in s:    return "catch-all"
    if s in ("valid", "safe"):                   return "valid"
    if s in ("invalid", "disabled"):             return "invalid"
    return "unknown" if s else ""                # "" = out of credits / no answer


def _abstract_validate(email: str, key: str) -> str:
    j = _get("https://emailvalidation.abstractapi.com/v1/",
             {"api_key": key, "email": email})
    if (j.get("is_catchall_email") or {}).get("value"):
        return "catch-all"
    return {"DELIVERABLE": "valid", "UNDELIVERABLE": "invalid",
            "UNKNOWN": "unknown"}.get((j.get("deliverability") or "").upper(), "")


def _kickbox_validate(email: str, key: str) -> str:
    j = _get("https://api.kickbox.com/v2/verify", {"email": email, "apikey": key})
    return {"deliverable": "valid", "undeliverable": "invalid",
            "risky": "catch-all", "unknown": "unknown"}.get(
                (j.get("result") or "").lower(), "")


def _verifalia_validate(email: str, key: str) -> str:
    # `key` is a Verifalia browser-app credential pair "username:password".
    if ":" not in (key or ""):
        return ""
    import requests
    user, pw = key.split(":", 1)
    try:
        r = requests.post("https://api.verifalia.com/v2.4/email-validations",
                          params={"waitTime": 30000}, auth=(user, pw),
                          json={"entries": [{"inputData": email}]}, timeout=45)
        if r.status_code not in (200, 202):
            return ""
        data = ((r.json().get("entries") or {}).get("data") or [])
        c = (data[0].get("classification") or "").lower() if data else ""
        return {"deliverable": "valid", "undeliverable": "invalid",
                "risky": "catch-all", "unknown": "unknown"}.get(c, "")
    except Exception:                                   # noqa: BLE001
        return ""


# The free-first waterfall: providers with a recurring FREE tier, biggest first —
# and the DAILY-resetting Verifalia first of all, so its use-or-lose credits are
# spent before the monthly pools. Each is BYO-key (skipped without one) and
# fault-tolerant (a bad/empty reply → next). Paid keys act only as the fallback.
_VERIFIERS = [
    ("verifalia_api_key",   "Verifalia",   _verifalia_validate),# ~25/day free
    ("reoon_api_key",       "Reoon",       _reoon_validate),    # ~600/mo free
    ("zerobounce_api_key",  "ZeroBounce",  _zb_validate),       # 100/mo free
    ("abstractapi_api_key", "AbstractAPI", _abstract_validate), # 100/mo free
    ("kickbox_api_key",     "Kickbox",     _kickbox_validate),  # 50/mo free
]
def _tomba_find(lead, key: str):
    """Tomba email FINDER (name + domain -> the real address). `key` is the pair
    'X-Tomba-Key:X-Tomba-Secret'. Returns (email, verification_status)."""
    if ":" not in (key or ""):
        return "", ""
    tkey, tsecret = key.split(":", 1)
    first, last = _name_parts(lead.name)
    dom = _domain_of(lead)
    if not (first and last and dom):
        return "", ""
    import requests
    try:
        r = requests.get(f"https://api.tomba.io/v1/email-finder/{dom}",
                         params={"first_name": first, "last_name": last},
                         headers={"X-Tomba-Key": tkey, "X-Tomba-Secret": tsecret},
                         timeout=30)
        d = (r.json().get("data") or {})
        return (d.get("email") or ""), ((d.get("verification") or {}).get("status") or "")
    except Exception:                                   # noqa: BLE001
        return "", ""


def _hunter_find(lead, key: str):
    """Hunter Email FINDER only (name + domain -> the real address). NO verify
    call — so ALL of Hunter's ~50 monthly credits go to finding, and the free
    verifiers do the confirming. Returns (email, verification_status)."""
    first, last = _name_parts(lead.name)
    dom = _domain_of(lead)
    if not (first and last and dom):
        return "", ""
    import requests
    try:
        d = (requests.get(FINDER, params={
            "domain": dom, "first_name": first, "last_name": last,
            "api_key": key}, timeout=30).json().get("data") or {})
        email = d.get("email") or ""
        if email and d.get("linkedin_url") and not (lead.extra or {}).get("linkedin"):
            lead.extra["linkedin"] = d["linkedin_url"]
        return email, ((d.get("verification") or {}).get("status") or "")
    except Exception:                                   # noqa: BLE001
        return "", ""


# Dedicated FINDERS (name + domain -> the real address, replacing a pattern
# guess), tried BEFORE verification, free-first. Hunter is a FINDER ONLY now —
# every credit goes to finding; confirmation is left to the free verifiers.
_FINDERS = [
    ("tomba_key",      "Tomba",  _tomba_find),          # ~25/mo free
    ("hunter_api_key", "Hunter", _hunter_find),         # ~50/mo, FIND only
]
# Every finder/verifier config key — collected from config/env by collect_keys.
VERIFIER_KEYS = [k for k, _, _ in _FINDERS] + [k for k, _, _ in _VERIFIERS]


def collect_keys(cfg: dict | None = None) -> dict:
    """{cfg_key: value} for every verifier key present in config or env."""
    cfg = cfg or {}
    out = {}
    for k in VERIFIER_KEYS:
        v = (cfg.get(k) or os.environ.get(k.upper()) or "").strip()
        if v:
            out[k] = v
    return out


def verify_email(email: str, keys: dict | None = None) -> str:
    """Verify a plain address through the free-first verifier waterfall (no
    finding step) — for checking a ready-made list before a send. Returns
    valid / invalid / catch-all / unknown, or '' when no key is set or none is
    confident. A verifier asks the mail server directly, so it catches the
    'live domain but the mailbox doesn't exist' guesses that hard-bounce (550)."""
    keys = keys or {}
    email = (email or "").strip()
    if not email:
        return ""
    for cfg_key, _name, fn in _VERIFIERS:
        k = keys.get(cfg_key)
        if not k:
            continue
        s = fn(email, k)
        if s:
            return s
    return ""


def find_and_verify(lead, keys: dict | None = None) -> None:
    """VERIFY-first, FIND-on-failure for ONE lead — the credit-thrifty order:
      1) VERIFIERS (Verifalia → Reoon → ZeroBounce → AbstractAPI → Kickbox) —
         confirm the address we ALREADY have (a pattern guess), most-free-first.
         A guess that comes back 'valid' is deliverable and costs nothing.
      2) FINDERS (Tomba, Hunter) — ONLY when there's no address, or the free
         check couldn't confirm it (invalid/unknown) — fetch the person's REAL
         address, then verify that too. A confirmed or catch-all guess never
         triggers a finder, so a paid credit is spent only where it can help.
    Hunter is FIND-ONLY throughout, so its ~50 credits go purely to recovery.
    BYO-key; a missing key is skipped, errors are ignored."""
    keys = keys or {}

    def _verify(addr: str) -> str:
        """Run the free verifier waterfall over one address; record and return
        the resulting status ('valid' short-circuits)."""
        for cfg_key, _name, fn in _VERIFIERS:
            k = keys.get(cfg_key)
            if not k:
                continue
            status = fn(addr, k)
            if status:
                lead.extra["email_check"] = status
                if status == "valid":
                    return "valid"
        return (lead.extra or {}).get("email_check", "")

    # 1) VERIFY the address we already have — FREE. A confirmed guess is done.
    email = (lead.email or "").strip()
    if email and _verify(email) == "valid":
        return
    # 2) Not confirmed (no address, or invalid/unknown) — FIND the real one (a
    #    finder credit), then verify what came back. 'catch-all' can't be
    #    confirmed either way, so we don't spend a credit chasing it.
    check = (lead.extra or {}).get("email_check", "")
    if (lead.name or "") and _domain_of(lead) and check not in ("valid", "catch-all"):
        for cfg_key, _name, fn in _FINDERS:
            k = keys.get(cfg_key)
            if not k:
                continue
            found, _status = fn(lead, k)
            if found and found.strip().lower() != email.lower():
                lead.email = found
                _verify(found)          # confirm the freshly found address, free
                break


def verify_reachable(dossiers, keys: dict | None = None, limit: int = 25,
                     on_progress=None) -> int:
    """FIND + VERIFY the hot/warm slice: finders (Tomba, Hunter) recover the
    real address, then the FREE verifier waterfall (Verifalia → Reoon →
    ZeroBounce → AbstractAPI → Kickbox) confirms it. Runs only on the people
    about to be emailed, staying inside the free tiers. Sequential on purpose —
    free tiers are rate-limited and this list is short. With no keys it is
    skipped and the sheet keeps its free MX check."""
    keys = keys or {}
    if not any(keys.values()):
        return 0
    targets = [d for d in dossiers if d.verdict in (HOT, WARM) and d.lead.name][:limit]
    for i, d in enumerate(targets, 1):
        if on_progress:
            on_progress(i, len(targets), d.lead)
        find_and_verify(d.lead, keys)
    return len(targets)
