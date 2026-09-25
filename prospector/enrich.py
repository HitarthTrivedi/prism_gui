"""
Prism Sales Automation — enrich: a company's real domain, and never a guess
────────────────────────────────────────────────────────────────────────────
The owner, 24-Sep-2026: "the emails shouldn't be guessed any day — it's gonna
be usage of hunter + apollo only to find mails." Prism used to build
firstname.lastname@<the company's website> for anyone without an address.
Those read like findings in the exported sheet and were often plainly wrong:
ABB's website is new.abb.com, its mail is abb.com, and a sheet of 52 such
addresses went out with not one confirmed. An address now comes only from the
person's own sheet, or from a finder that knows them — Hunter or Apollo
(verify.find_and_verify) — and is checked after.

What is left here:
  · `enrich` — each company's real website domain (Exa, one lookup per unique
    company, a blocklist keeping directories and socials out), kept on the lead
    as company_domain for the finders to ask with. It never writes an address.
  · `is_guess` / `forget_guess` — an address an older build GUESSED is taken off
    the lead (kept aside as guessed_email), so no guess is shown, sent or
    exported again.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

EXA_SEARCH_URL = "https://api.exa.ai/search"

# Never a company's own homepage — directories, socials, news, aggregators.
_BLOCK = ("linkedin", "facebook", "wikipedia", "zoominfo", "instagram", "youtube",
          "twitter", "x.com", "crunchbase", "indiamart", "justdial", "bloomberg",
          "tofler", "zaubacorp", "glassdoor", "google.", "moneycontrol",
          "economictimes", "timesofindia", "business-standard", "yahoo",
          "reddit", "quora",
          # B2B directories / aggregators — a company's people are NOT reachable
          # at these, so an address built on one (e.g. name@dial4trade.com) is
          # always wrong. Seen leaking into real runs.
          "dial4trade", "hoursfinder", "exportersindia", "tradeindia",
          "go4worldbusiness", "made-in-china", "alibaba", "europages", "kompass",
          "yellowpages", "yelp", "ambitionbox", "sulekha", "manta",
          "opencorporates", "dnb.", "thomasnet", "ec21", "tradewheel",
          "clutch.co", "goodfirms", "trustpilot", "mapquest", "bizapedia",
          # data aggregators / registries / job boards that keep surfacing as a
          # company's "domain" (wrong — the person isn't reachable there)
          "tracxn", "volza", "processregister", "indiabiz", "goldenpages",
          "thecompanycheck", "yelu", "cii.", "sulekha", "yellowpages",
          "ambitionbox", "ypo.org", "storebuxa", "rocketreach", "apollo.io",
          "seamless", "uplead", "signalhire", "datanyze", "owler", "slintel",
          "fundoodata", "jimtrade", "whitepages", "naukri", "foundit")
_SUFFIX = re.compile(r"\b(limited|ltd|pvt|private|india|industries|manufacturing|"
                     r"corporation|company|group|the|inc|llp)\b", re.I)


def _first_real_host(results) -> str:
    """The first result whose host is a company's own site, not a directory,
    social feed or aggregator (_BLOCK)."""
    for res in results or []:
        host = urlparse((res or {}).get("url", "")).netloc.lower().replace("www.", "")
        if host and not any(b in host for b in _BLOCK):
            return host
    return ""


def _real_domain(company: str, api_key: str, timeout: int = 30) -> str:
    from . import gateway
    if gateway.is_pool(api_key):
        # Pooled: the licence server asks Exa (its key, the customer's credits)
        # and sends back only each result's address and title; choosing a real
        # company site among them stays here, with the blocklist.
        return _first_real_host(gateway.website_rows(company))
    import requests
    try:
        r = requests.post(
            EXA_SEARCH_URL,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": f"{company} official company website homepage",
                  "type": "auto", "numResults": 5}, timeout=timeout)
        if r.status_code != 200:
            return ""
        return _first_real_host(r.json().get("results", []))
    except Exception:                                   # noqa: BLE001
        return ""


def _slug_domain(company: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", _SUFFIX.sub(" ", company.lower()))
    return f"{slug}.com" if 2 < len(slug) < 22 else ""


def _pattern_email(name: str, domain: str) -> str:
    """The address older builds GUESSED — kept only so is_guess can recognise
    one. Nothing writes it any more."""
    parts = re.sub(r"[^A-Za-z ]", "", name).split()
    return (f"{parts[0].lower()}.{parts[-1].lower()}@{domain}"
            if domain and len(parts) >= 2 else "")


def enrich(leads, api_key: str = "", on_progress=None):
    """The real website domain of every company whose people have no address
    and no domain yet, as company_domain — one Exa lookup per unique company
    (threaded). Nothing when the lookup finds no real site: a domain made up
    from the company's name is a guess too. It NEVER writes an address; the
    finders do that (verify.find_and_verify)."""
    need = [l for l in leads if not (l.email or "").strip()
            and not (l.extra or {}).get("company_domain")]
    companies = sorted({l.company for l in need if l.company})
    if on_progress:
        on_progress(0, len(companies))
    dom_map: dict = {}
    if companies and api_key:
        with ThreadPoolExecutor(max_workers=24) as ex:
            dom_map = dict(zip(companies,
                               ex.map(lambda c: _real_domain(c, api_key), companies)))
    for l in need:
        dom = dom_map.get(l.company)
        if dom:
            l.extra["company_domain"] = dom
    return leads


def is_guess(lead) -> bool:
    """Whether the address on `lead` is one an older build GUESSED: exactly the
    working pattern on the company_domain enrich looked up (or made up from the
    name), with no finder, sheet or Apollo recorded as its source. Only enrich
    ever set company_domain on a lead without an address — Apollo sets it with
    email_source — so a real address from a sheet can never read as a guess."""
    extra = getattr(lead, "extra", None) or {}
    email = (getattr(lead, "email", "") or "").strip().lower()
    domain = (extra.get("company_domain") or "").strip().lower()
    if not (email and domain) or extra.get("email_source"):
        return False
    return email == _pattern_email(getattr(lead, "name", "") or "", domain).lower()


def forget_guess(lead) -> bool:
    """Take a guessed address off `lead` (is_guess), kept aside as
    extra["guessed_email"] with the check once run on it, so the lead reads as
    having no address — the finders' job. True when one was taken."""
    if not is_guess(lead):
        return False
    lead.extra["guessed_email"] = lead.email
    check = lead.extra.pop("email_check", None)
    if check:
        lead.extra["guessed_email_check"] = check
    lead.email = ""
    return True
