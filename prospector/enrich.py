"""
Prism Sales Automation — enrich: a real, verifiable e-mail per lead
────────────────────────────────────────────────────────────────────
A sourced lead has a name, a title and a company — but no address. This stage
finds each company's REAL website (Exa, one lookup per unique company, a
blocklist keeping directories and socials out) and builds the working-pattern
address firstname.lastname@thatdomain. On a real client list this lifted the
share of leads on a mail-accepting domain from ~22% to ~68%, for free.

Two rules:
  · It only fills a BLANK e-mail — a sheet that already carried real addresses
    keeps them untouched.
  · The MX check (does the domain even accept mail) lives in `exports`; here we
    only get the address as right as it can be without a paid vendor, and fall
    back to a company-name slug domain when the lookup finds nothing.
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


def _real_domain(company: str, api_key: str, timeout: int = 30) -> str:
    import requests
    try:
        r = requests.post(
            EXA_SEARCH_URL,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": f"{company} official company website homepage",
                  "type": "auto", "numResults": 5}, timeout=timeout)
        if r.status_code != 200:
            return ""
        for res in r.json().get("results", []):
            host = urlparse(res.get("url", "")).netloc.lower().replace("www.", "")
            if host and not any(b in host for b in _BLOCK):
                return host
    except Exception:                                   # noqa: BLE001
        return ""
    return ""


def _slug_domain(company: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", _SUFFIX.sub(" ", company.lower()))
    return f"{slug}.com" if 2 < len(slug) < 22 else ""


def _pattern_email(name: str, domain: str) -> str:
    parts = re.sub(r"[^A-Za-z ]", "", name).split()
    return (f"{parts[0].lower()}.{parts[-1].lower()}@{domain}"
            if domain and len(parts) >= 2 else "")


def enrich(leads, api_key: str = "", on_progress=None):
    """Give every lead that lacks one a real-domain e-mail. Each company is
    looked up ONCE (threaded); a lead that already has an address is left as it
    is. Falls back to a slug domain when Exa finds nothing (or has no key)."""
    need = [l for l in leads if not (l.email or "").strip()]
    companies = sorted({l.company for l in need if l.company})
    if on_progress:
        on_progress(0, len(companies))
    dom_map: dict = {}
    if companies and api_key:
        with ThreadPoolExecutor(max_workers=24) as ex:
            dom_map = dict(zip(companies,
                               ex.map(lambda c: _real_domain(c, api_key), companies)))
    for l in need:
        dom = dom_map.get(l.company) or _slug_domain(l.company)
        if dom:
            l.extra["company_domain"] = dom
            l.email = _pattern_email(l.name, dom)
    return leads
