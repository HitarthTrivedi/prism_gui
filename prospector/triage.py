"""
Prism Sales Automation — triage: score the WHOLE list, qualify the best
────────────────────────────────────────────────────────────────────────
The expensive pass (Exa signals + Groq dossier + Hunter verify) must run on the
BEST leads, not the first ones off the sheet. This is the cheap, deterministic,
network-free fit score that ranks every lead so `engine` can spend the costly
pass on the top slice — the single biggest quality lift over `leads[:limit]`.

No model, no network: it reads fields already on the lead (title seniority,
title/industry overlap with the offer + ICP roles, contact completeness), so it
is instant and free over thousands of rows and can never hallucinate.
"""
from __future__ import annotations

import re

# How much a title suggests someone who owns or influences a budget.
_SENIORITY = {
    "chief": 30, "cxo": 30, "ceo": 30, "cto": 30, "cio": 30, "coo": 30,
    "founder": 30, "owner": 30, "president": 28, "svp": 28, "evp": 28,
    "vice president": 26, "vp": 26, "director": 22, "head": 22,
    "general manager": 20, "gm ": 20, "agm": 16, "principal": 14, "lead": 14,
    "manager": 12, "senior": 6,
}
_STOP = {"the", "and", "for", "of", "at", "to", "in", "on", "with", "our",
         "your", "their", "services", "service", "large", "company", "companies",
         "manufacturers", "manufacturer", "industry", "industries", "solutions",
         "solution", "platform", "new", "that", "who"}


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


def _seniority(title: str) -> tuple[int, str]:
    t = f" {(title or '').lower()} "
    best, word = 0, ""
    for k, v in _SENIORITY.items():
        if k in t and v > best:
            best, word = v, k.strip()
    return best, word


def score_lead(lead, offer: str, roles: list | None = None) -> tuple[float, str]:
    """0-100 fit score + a one-line reason. Higher = worth the expensive pass."""
    reasons, score = [], 0.0

    # 1) Authority — does the title read like a budget owner? (max ~30)
    sen, word = _seniority(lead.title)
    if sen:
        score += sen
        reasons.append(f"{word.title()}-level")

    # 2) Fit — overlap of title+industry with what the seller sells + the ICP
    #    roles. (max ~45)
    want = _tokens(offer) | _tokens(" ".join(roles or []))
    have = _tokens(lead.title) | _tokens(lead.industry)
    overlap = want & have
    if want:
        score += min(len(overlap), 6) * 7.5
        if overlap:
            reasons.append("matches " + ", ".join(sorted(overlap)[:3]))

    # 3) Reachability / completeness (max ~25)
    if (lead.email or "").strip():
        score += 15
    else:
        reasons.append("no email")
    if (lead.company or "").strip():
        score += 6
    if (lead.extra or {}).get("location"):
        score += 4

    return round(max(0.0, min(100.0, score)), 1), (" · ".join(reasons) or "thin profile")


def rank(leads: list, offer: str, roles: list | None = None) -> list:
    """Score every lead in place (fit_score + fit_reason) and return them
    sorted best-first, so the caller can deep-qualify just the top slice."""
    for lead in leads:
        lead.fit_score, lead.fit_reason = score_lead(lead, offer, roles)
    return sorted(leads, key=lambda l: l.fit_score, reverse=True)
