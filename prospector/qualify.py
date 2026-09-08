"""
Prism Prospector — qualification as a case file, not a score
────────────────────────────────────────────────────────────
The core, and the one layer the giants don't sell. Standard tools hand you a
number you're asked to trust. This stage hands back an argument you can read:
six named dimensions, each marked ✓/⚠/✗ with the evidence and the source that
proves it — qualified against *the client's own offer*, not a generic ICP.

Two rules the prompt enforces, because they are the whole point:

  · **No invention.** Every claim must rest on a provided signal or a lead
    field. Where there is no evidence, the dimension is `unknown` — never
    dressed up as a pass. A drafted opener may only reference a signal that is
    actually present.
  · **It runs on the small fast model in JSON mode.** groq_chat(json_mode=True)
    constrains the reply to one JSON object, so a parser downstream gets valid
    JSON or a clean error — not prose, not a refusal, not a trailing-off.
"""
from __future__ import annotations

import json
import re

from .models import (COLD, HOT, WARM, Dimension, Dossier, Lead, Signal,
                     FAIL, PASS, UNKNOWN, WARN, OK, QUALIFY_ERROR, NON_JSON,
                     NO_MODEL)

DIMENSIONS = ["Fit", "Need", "Timing", "Authority", "Budget", "Competition"]
_VALID = {PASS, WARN, FAIL, UNKNOWN}
_MUST_CITE = {"Need", "Timing", "Competition"}
_WEIGHT = {"Fit": 20, "Need": 25, "Timing": 25, "Authority": 15, "Budget": 8,
           "Competition": 7}
_VAL = {PASS: 1.0, WARN: 0.5, FAIL: 0.0, UNKNOWN: 0.15}
# A company doing one of these is in trouble, not in a live buying window.
_NEGATIVE = ("layoff", "lay off", "laid off", "job cut", "insolven", "bankrupt",
             "shutdown", "shuts down", "shut down", "closure", "wind down",
             "loss", "losses", "downturn", "fraud", "scam", "steps down",
             "stepping down", "resign")


def _cites_real_signal(source: str, n_signals: int) -> bool:
    """The source must name an S-tag (S1..Sn) that actually exists in what we
    handed the model — a citation to a signal that isn't there is a
    hallucination, not evidence."""
    for m in re.findall(r"[sS](\d+)", source or ""):
        if 1 <= int(m) <= n_signals:
            return True
    return False


def _derive_score(dims: list) -> int:
    """Score FROM the six dimensions (Need + Timing weighted highest), never the
    model's freehand number — the calibration warning made structural."""
    total = sum(_WEIGHT.values())
    s = sum(_WEIGHT[d.name] * _VAL.get(d.verdict, 0.15) for d in dims)
    return int(round(100 * s / total))


def _negative(signals: list) -> str:
    for s in signals:
        blob = f"{s.title} {s.snippet}".lower()
        for w in _NEGATIVE:
            if w in blob:
                return (s.title or w)[:120]
    return ""


def _signals_block(signals: list[Signal]) -> str:
    if not signals:
        return "NONE FOUND — qualify on fit only; mark Need/Timing/Competition unknown unless a lead field proves them.\n"
    lines = []
    for i, s in enumerate(signals, 1):
        cite = " ".join(x for x in (s.source, s.published) if x)
        lines.append(f"[S{i}] {s.title} ({cite})\n     {s.snippet}\n     {s.url}")
    return "\n".join(lines)


def build_prompt(lead: Lead, signals: list[Signal], offer: str) -> str:
    other = lead.extra.get("other_emails")
    contact = ", ".join(x for x in (lead.email, lead.phone) if x) or "none on file"
    return f"""You qualify B2B sales leads into an evidence-backed case file. Reply with ONLY a JSON object.

WHAT THE SELLER SELLS (qualify against THIS, not a generic profile):
{offer}

THE LEAD (from the seller's own list):
- Name: {lead.name}
- Title: {lead.title or "unknown"}
- Company: {lead.company or "unknown"}
- Industry: {lead.industry or "unknown"}
- Contact on file: {contact}

LIVE "WHY-NOW" SIGNALS about the company (dated, sourced — the ONLY facts you may cite for Need/Timing/Competition):
{_signals_block(signals)}

Qualify on six dimensions. For each: a verdict of "pass" / "warn" / "fail" / "unknown", one line of evidence, and the source it rests on.
- Fit: does the company/person match a buyer of what the seller sells? (may use lead fields)
- Need: is there an ACTIVE problem the seller solves? (must cite a signal, else "unknown")
- Timing: is there a live window now — a recent, dated event? (must cite a signal, else "unknown")
- Authority: does this person plausibly own or influence that budget? (use the title)
- Budget: can they afford it — scale/capex evidence? (cite a signal or firmographic, else "unknown")
- Competition: incumbent or displacement angle visible in a signal? (else "unknown")

HARD RULES:
- Never invent a fact. If no signal or field supports a dimension, verdict = "unknown", source = "".
- "source" must quote a signal tag like "S1" plus its citation, or a lead field name. Never fabricate a URL or date.
- The opener must be one or two sentences, reference a REAL signal if any exist, and read like a person wrote it — no "Dear Sir".
- verdict (overall): "hot" only if Need AND Timing pass; "warm" if fit+some signal; "cold" if only fit.

JSON shape:
{{"verdict":"hot|warm|cold","score":0-100,"summary":"one line",
"dimensions":[{{"name":"Fit","verdict":"pass|warn|fail|unknown","evidence":"...","source":"..."}}, ... all six in order],
"opener":"..."}}"""


def _dossier_from_json(data: dict, lead: Lead, signals: list[Signal]) -> Dossier:
    n = len(signals)
    by_name = {str(d.get("name", "")).strip().lower(): d
               for d in (data.get("dimensions") or []) if isinstance(d, dict)}
    dims, grounded = [], 0
    for name in DIMENSIONS:
        d = by_name.get(name.lower(), {})
        v = str(d.get("verdict", UNKNOWN)).strip().lower()
        v = v if v in _VALID else UNKNOWN
        src = str(d.get("source", "")).strip()
        # Grounding guard: a must-cite dimension (Need/Timing/Competition) whose
        # source doesn't reference a REAL signal is forced to unknown — no
        # phantom "Need = pass" with a citation to a signal that wasn't there.
        if name in _MUST_CITE and v != UNKNOWN and not _cites_real_signal(src, n):
            v, src = UNKNOWN, ""
        if name in _MUST_CITE and v != UNKNOWN:
            grounded += 1
        dims.append(Dimension(name=name, verdict=v,
                              evidence=str(d.get("evidence", "")).strip(),
                              source=src))
    by = {d.name: d for d in dims}

    # A negative signal (layoffs, loss, insolvency, a leader stepping down)
    # DISQUALIFIES on timing rather than warming a dead lead.
    neg = _negative(signals)
    if neg:
        by["Timing"].verdict = FAIL
        by["Timing"].evidence = (by["Timing"].evidence or f"Negative signal: {neg}")[:200]

    # The rubric is enforced HERE, not trusted from the model: hot needs Need
    # AND Timing = pass; warm needs fit plus at least one real pass; else cold.
    # A hallucinated "hot" with all-unknown dimensions can no longer ship.
    need_ok = by["Need"].verdict == PASS
    timing_ok = by["Timing"].verdict == PASS
    fit_ok = by["Fit"].verdict in (PASS, WARN)
    if need_ok and timing_ok:
        verdict = HOT
    elif fit_ok and any(x.verdict == PASS for x in dims):
        verdict = WARM
    else:
        verdict = COLD

    return Dossier(
        lead=lead, verdict=verdict, score=_derive_score(dims), dimensions=dims,
        opener=str(data.get("opener", "")).strip(),
        summary=str(data.get("summary", "")).strip(),
        signals=signals, status=OK,
        confidence=round(min(1.0, grounded / len(_MUST_CITE)), 2),
    )


class Qualifier:
    """Lead + signals + offer → Dossier, via Prism's own Groq router."""

    def __init__(self, api_key: str, model: str = "", temperature: float = 0.2):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    @classmethod
    def from_config(cls, cfg: dict) -> "Qualifier":
        return cls(api_key=cfg.get("api_key", ""), model=cfg.get("model", ""))

    def qualify(self, lead: Lead, signals: list[Signal], offer: str) -> Dossier:
        if not self.api_key:
            return Dossier(lead=lead, signals=signals, status=NO_MODEL,
                           note="No Groq API key configured — set it in Prism Setup.")
        import core_bridge as CB           # lazy: wires the engine + submodule
        prompt = build_prompt(lead, signals, offer)
        try:
            raw = CB.router.groq_chat(self.api_key, self.model, prompt,
                                      temperature=self.temperature,
                                      json_mode=True, retries=3)
        except Exception as e:              # noqa: BLE001 — surface, don't crash a batch
            # A rate-limited/unreachable lead is status=qualify_error — NOT a
            # default COLD verdict indistinguishable from a genuinely cold lead.
            return Dossier(lead=lead, signals=signals, status=QUALIFY_ERROR,
                           note=f"Qualifier could not reach the model: {e}")
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return Dossier(lead=lead, signals=signals, status=NON_JSON,
                           note="Qualifier returned output that was not valid JSON.")
        return _dossier_from_json(data, lead, signals)
