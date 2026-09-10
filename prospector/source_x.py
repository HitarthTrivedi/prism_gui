"""
Prism Sales Automation — source_x: find people on X/Twitter
────────────────────────────────────────────────────────────
X is a walled garden: Exa can't see it and there's no free search API, so the
finder here goes through a *general search engine* (which does index X profile
pages, bio and all) with a `site:x.com` query, then parses the handle, name and
bio out of the results.

Pluggable + free-first, exactly like the verifier waterfall in verify.py:
a keyed provider is used when its key is present (Serper, then Brave), otherwise
it falls back to DuckDuckGo's keyless HTML endpoint — so this runs at ZERO cost
and no signup, and gets faster/cleaner the moment a key is added.

Reach stays MANUAL — this stage only builds a ranked target list with a drafted
opener; the user opens each profile and DMs/replies by hand (automating X
messaging is a fast ban, same lesson as WhatsApp).
"""
from __future__ import annotations

import html
import re
import time
import urllib.parse
from dataclasses import dataclass, field

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Handles that are X's own routes, never a person.
_BAD_HANDLES = {"i", "home", "search", "explore", "hashtag", "intent", "share",
                "messages", "notifications", "settings", "login", "signup",
                "tos", "privacy", "about", "compose", "help", "status", "en"}

# Snippet phrases that mean the person is actively courting connection — the
# single strongest reachability signal on X.
_INVITE = ("what are you building", "looking to connect", "dm me", "drop a link",
           "roll call", "show your product", "what are you working on",
           "connect with", "reply with", "pitch your")


@dataclass
class XProfile:
    handle: str
    name: str = ""
    url: str = ""
    bio: str = ""                       # the result snippet — bio or post text
    is_post: bool = False               # a /status/ link, not the profile root
    source: str = ""                    # the query that surfaced them
    fit_score: float = 0.0
    fit_reason: str = ""
    opener: str = ""

    def display(self) -> str:
        return f"@{self.handle}" + (f" — {self.name}" if self.name else "")


# ── searchers (keyed first, keyless fallback) ─────────────────────────────────

def _serper(query: str, key: str, n: int = 15) -> list[dict]:
    import requests
    r = requests.post("https://google.serper.dev/search",
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": query, "num": n}, timeout=25)
    return [{"url": o.get("link", ""), "title": o.get("title", ""),
             "snippet": o.get("snippet", "")}
            for o in (r.json().get("organic") or [])]


def _brave(query: str, key: str, n: int = 15) -> list[dict]:
    import requests
    r = requests.get("https://api.search.brave.com/res/v1/web/search",
                     headers={"X-Subscription-Token": key, "Accept": "application/json"},
                     params={"q": query, "count": n}, timeout=25)
    web = (r.json().get("web") or {}).get("results") or []
    return [{"url": o.get("url", ""), "title": o.get("title", ""),
             "snippet": o.get("description", "")} for o in web]


class RateLimited(Exception):
    """DuckDuckGo served its 'anomaly' page — keyless is being throttled."""


def _parse_ddg(t: str) -> list[dict]:
    """Layout-agnostic: DDG encodes every result URL as `…uddg=<encoded>…`
    (stable across its html and lite pages), so we key on that rather than on a
    CSS class that DDG changes. Empty when the page carries no results (its
    'anomaly'/throttle page has no uddg links)."""
    # DDG links a result TWICE (title anchor + snippet anchor), both uddg-encoded
    # to the same URL, and the snippet's anchor TEXT is the bio. So collect every
    # (url, anchor-text) pair, then per URL pick the X-title-looking text as the
    # title and the longest of the rest as the bio.
    pairs = []
    for seg in re.split(r"uddg=", t)[1:]:
        m = re.match(r"([^&\"']+)", seg)
        if not m:
            continue
        url = urllib.parse.unquote(m.group(1))
        if "x.com/" not in url and "twitter.com/" not in url:
            continue
        tm = re.search(r">(.*?)</a>", seg[m.end():], re.S)
        pairs.append((url, _text(tm.group(1)) if tm else ""))
    by_url: dict = {}
    for url, text in pairs:
        by_url.setdefault(url, [])
        if text:
            by_url[url].append(text)
    out = []
    for url, texts in by_url.items():
        title = next((x for x in texts if re.search(r"\bon X\b|/\s*X\b|\(@", x)),
                     texts[0] if texts else "")
        others = [x for x in texts if x != title]
        out.append({"url": url, "title": title,
                    "snippet": max(others, key=len) if others else title})
    return out


def _ddg(query: str, n: int = 20) -> list[dict]:
    """DuckDuckGo's keyless endpoints — no API key, no signup. Tries the html
    then the lite page; raises RateLimited when both come back throttled so the
    caller can tell the user to add a key rather than silently returning none."""
    import requests
    throttled = False
    for ep in ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/"):
        try:
            t = requests.post(ep, data={"q": query},
                              headers={"User-Agent": _UA}, timeout=25).text
        except Exception:                               # noqa: BLE001
            continue
        res = _parse_ddg(t)
        if res:
            return res[:n]
        if "anomaly" in t.lower() or "uddg=" not in t:
            throttled = True
    if throttled:
        raise RateLimited()
    return []


# Provider order: a keyed engine when its key is present, else keyless DDG.
_SEARCHERS = [("serper_api_key", "Serper", _serper),
              ("brave_api_key", "Brave", _brave)]
SEARCH_KEYS = [k for k, _, _ in _SEARCHERS]


def _search(query: str, keys: dict) -> list[dict]:
    for cfg_key, _name, fn in _SEARCHERS:
        k = (keys or {}).get(cfg_key)
        if not k:
            continue
        try:
            res = fn(query, k)
            if res:
                return res
        except Exception:                               # noqa: BLE001 — try next
            pass
    return _ddg(query)                                  # $0 fallback (may RateLimited)


# ── parsing ───────────────────────────────────────────────────────────────────

def _text(h: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", h or "")).strip()


def _real_url(href: str) -> str:
    """DDG wraps links as //duckduckgo.com/l/?uddg=<encoded>. Unwrap to the real
    destination; a direct http(s) href is returned as-is."""
    if href.startswith("//"):
        href = "https:" + href
    m = re.search(r"[?&]uddg=([^&]+)", href)
    return urllib.parse.unquote(m.group(1)) if m else href


_HANDLE_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{2,30})")


def _name_from_title(title: str) -> str:
    """"Kunyi (@ikpe_kunyi) on X" / "Kunyi on X: ..." → "Kunyi"."""
    t = (title or "").strip()
    t = re.split(r"\s+(?:on|/)\s+(?:X|Twitter)\b", t)[0]        # cut " on X…" / " / X"
    t = re.split(r"\s+on X:", t)[0]
    t = re.sub(r"\s*\(@[^)]+\)\s*$", "", t)                     # drop trailing (@handle)
    return t.strip(" \"'“”/|")


def _profile_from(result: dict) -> "XProfile | None":
    url = result.get("url", "")
    m = _HANDLE_RE.match(url)
    if not m:
        return None
    handle = m.group(1)
    if handle.lower() in _BAD_HANDLES:
        return None
    return XProfile(handle=handle, name=_name_from_title(result.get("title", "")),
                    url=f"https://x.com/{handle}", bio=result.get("snippet", ""),
                    is_post="/status/" in url, source=result.get("q", ""))


# ── rank + draft ──────────────────────────────────────────────────────────────

def rank(profiles: list, terms: list) -> list:
    """Cheap, network-free fit score: bio/name overlap with the ICP terms, a
    bonus for a profile root over a single post, and a big bonus when the
    snippet shows they're openly inviting connection."""
    terms = [t.lower() for t in (terms or []) if t]
    for p in profiles:
        blob = f"{p.bio} {p.name}".lower()
        hits = sorted({t for t in terms if t in blob})
        why, score = [], 0.0
        if hits:
            score += min(len(hits), 5) * 9
            why.append("matches " + ", ".join(hits[:3]))
        if not p.is_post:
            score += 20
            why.append("profile")
        else:
            why.append("from a post")
        if any(k in p.bio.lower() for k in _INVITE):
            score += 28
            why.append("inviting connection")
        p.fit_score = round(min(100.0, score), 1)
        p.fit_reason = " · ".join(why) or "thin profile"
    return sorted(profiles, key=lambda p: p.fit_score, reverse=True)


def draft_opener(p: XProfile, offer: str) -> str:
    first = (p.name.split()[0] if p.name else "there").strip()
    hook = (p.bio[:90].rsplit(" ", 1)[0] + "…") if len(p.bio) > 90 else (p.bio or
            "your build-in-public posts")
    return (f"Hey {first} — saw \"{hook}\". I'm building {offer}. "
            f"Would love to trade notes — happy to show a 2-min run if useful.")


def default_queries(extra: str = "") -> list[str]:
    """A spread of `site:x.com` angles for the founder / indie / SaaS / dev
    audience. `extra` narrows every angle (e.g. a niche or a location)."""
    base = [
        "indie hacker bootstrapped SaaS founder building in public",
        "solo founder building SaaS what are you building",
        "developer building AI agents automation tools startup",
        "Y Combinator founder startup building",
        "developer tools founder open source automation",
        "micro SaaS AI founder ship fast startup",
    ]
    return [f"site:x.com {q} {extra}".strip() for q in base]


def find(queries: list, keys: dict | None = None, *, terms: list | None = None,
         offer: str = "an on-device AI automation engine", max_profiles: int = 40,
         delay: float = 0.6, on_progress=None) -> list:
    """Run the `site:x.com` searches, parse profiles, dedupe (preferring a
    profile root over a stray post), rank, and draft an opener each."""
    raw: list[XProfile] = []
    throttled = False
    for i, q in enumerate(queries, 1):
        try:
            results = _search(q, keys or {})
        except RateLimited:
            throttled = True
            results = []
        for r in results:
            r["q"] = q
            p = _profile_from(r)
            if p:
                raw.append(p)
        if on_progress:
            on_progress(i, len(queries), q, len(raw))
        if i < len(queries):
            time.sleep(delay)                           # gentle on the endpoint
    # A total keyless block with nothing to show is worth saying out loud, so the
    # caller can tell the user to add a (free) Serper/Brave key rather than
    # showing a mysteriously empty list.
    if throttled and not raw:
        raise RateLimited(
            "DuckDuckGo is rate-limiting the keyless finder. Add a free Serper "
            "or Brave key in Settings for a reliable, fast search.")
    best: dict = {}
    for p in raw:
        cur = best.get(p.handle.lower())
        if (cur is None or (cur.is_post and not p.is_post)
                or (p.is_post == cur.is_post and len(p.bio) > len(cur.bio))):
            best[p.handle.lower()] = p
    ranked = rank(list(best.values()), terms or [])[:max_profiles]
    for p in ranked:
        p.opener = draft_opener(p, offer)
    return ranked
