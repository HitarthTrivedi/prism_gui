"""
Prism Prospector — the "why now" layer
──────────────────────────────────────
A name in a role is presence; a company that just did something is a reason to
call. This stage fetches the dated, cited events that turn a static row into a
warm lead — and it only ever returns real, sourced signals. If no source is
configured or nothing is found, it returns nothing; the qualifier is then told
"no signal", never handed an invention. That honesty is the anti-hallucination
rule made structural: we do not fabricate a reason to call.

The default provider is Exa (the web as a live queryable database). Its key is
brought by the user — the whole product runs on the customer's own keys, so we
never resell data and the cost is theirs, flat. A machine with no Exa key still
runs end to end; it just qualifies on fit alone and says so.
"""
from __future__ import annotations

import os

from .models import Lead, Signal

EXA_SEARCH_URL = "https://api.exa.ai/search"


def exa_key(cfg: dict | None = None) -> str:
    """The user's own Exa key, from config or the environment. BYO-keys."""
    cfg = cfg or {}
    return (cfg.get("exa_api_key") or os.environ.get("EXA_API_KEY") or "").strip()


class SignalProvider:
    """Stage interface: a lead in, its dated why-now signals out."""
    name = "none"

    def fetch(self, lead: Lead, focus: str = "") -> list[Signal]:  # noqa: D401
        return []


class NullSignalProvider(SignalProvider):
    """Used when no Exa key is set. Qualifies on fit alone, honestly."""
    name = "none (no Exa key)"


# Hosts that are never a prospect's OWN news — a vendor pitch, a business
# directory or a social feed. Filtered out so a "why-now" is the company's own
# move, not a page that merely mentions it.
_BLOCK = ("linkedin.com", "facebook.com", "youtube.com", "twitter.com", "x.com",
          "instagram.com", "crunchbase.com", "zoominfo.com", "indiamart.com",
          "justdial.com", "glassdoor.com", "tofler.in", "zaubacorp.com")


class ExaSignalProvider(SignalProvider):
    name = "exa"

    def __init__(self, api_key: str, num_results: int = 5, timeout: int = 30,
                 exclude_domains: tuple = ()):
        self.api_key = api_key
        self.num_results = num_results
        self.timeout = timeout
        self.exclude_domains = tuple(
            d.lower().replace("www.", "") for d in exclude_domains if d)
        self.errored = False    # set per-fetch so a source error ≠ "no news"

    def fetch(self, lead: Lead, focus: str = "") -> list[Signal]:
        self.errored = False
        if not (self.api_key and lead.company):
            return []
        import requests  # lazy: matches how the engine defers heavy imports
        from datetime import datetime, timedelta, timezone

        # The topic is a NEWS focus, never the seller's offer. The company name
        # is quoted so the search is about THAT company's own recent moves.
        topic = focus or ("expansion, new plant, capacity investment, automation, "
                          "digital transformation, Industry 4.0, IIoT, hiring")
        query = f'"{lead.company}" news: {topic}'
        # Real recency, not a hardcoded year token: only the last ~6 months, so a
        # stale profile page can't pose as a "why-now".
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00.000Z")
        headers = {"x-api-key": self.api_key,
                   "Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        payload = {
            "query": query,
            "type": "auto",
            "numResults": self.num_results,
            "startPublishedDate": start,
            "endPublishedDate": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "contents": {"highlights": True, "text": {"maxCharacters": 800}},
        }
        if self.exclude_domains:
            payload["excludeDomains"] = list(self.exclude_domains)
        try:
            resp = requests.post(EXA_SEARCH_URL, headers=headers,
                                 json=payload, timeout=self.timeout)
        except Exception:                       # noqa: BLE001 — network is a status line, not a crash
            self.errored = True
            return []
        if resp.status_code != 200:
            self.errored = True
            return []
        try:
            results = resp.json().get("results", [])
        except ValueError:
            self.errored = True
            return []

        out = []
        for r in results:
            host = _host(r.get("url") or "")
            # Drop the seller's own site and vendor/social/directory hosts — a
            # page pitching AT this company is not the company's own why-now.
            if (any(b in host for b in _BLOCK)
                    or any(d and d in host for d in self.exclude_domains)):
                continue
            hi = r.get("highlights") or []
            snippet = " … ".join(hi)[:600] if hi else (r.get("text") or "")[:400]
            out.append(Signal(
                title=r.get("title") or "",
                snippet=snippet.strip(),
                url=r.get("url") or "",
                published=(r.get("publishedDate") or "")[:10],
                source=host,
            ))
        return out


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:                           # noqa: BLE001
        return ""


def make_provider(cfg: dict | None = None, focus: str = "",
                  exclude_domains: tuple = ()) -> SignalProvider:
    """Exa if the user has a key, otherwise the honest Null provider. Seller /
    own domains to keep out of the results are passed here (and may also be
    listed under cfg['exclude_domains'])."""
    key = exa_key(cfg)
    if not key:
        return NullSignalProvider()
    extra = list(exclude_domains) + list((cfg or {}).get("exclude_domains") or [])
    return ExaSignalProvider(key, exclude_domains=tuple(extra))
