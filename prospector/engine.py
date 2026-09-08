"""
Prism Sales Automation — the POC orchestrator
─────────────────────────────────────────────
Ties the four domain modules into the one thing worth proving: a flat sheet in,
qualified case files out.

    sheet.load ─► (triage) ─► signals.fetch ─► qualify ─► Dossier

Triage is a stub for the POC: we take the first N rows so a run is cheap and
fast to eyeball. Real triage (a cheap signal scan over the whole sheet, then
deep-qualify only the hot slice) is the next stage — the shape is already here,
it just needs a scorer in front of the `leads[:limit]` line.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import sheet
from .models import Dossier, Lead
from .qualify import Qualifier
from .signals import SignalProvider, NullSignalProvider


@dataclass
class RunResult:
    dossiers: list[Dossier]
    total_in_sheet: int
    signal_source: str
    all_leads: list = field(default_factory=list)


def run(path: str, offer: str, cfg: dict, *,
        sheet_name: str | None = None,
        limit: int = 3,
        focus: str = "",
        provider: SignalProvider | None = None,
        on_progress=None,
        roles: list | None = None) -> RunResult:
    """Qualify the BEST `limit` leads of a SHEET against `offer`."""
    return run_leads(sheet.load(path, sheet_name), offer, cfg, limit=limit,
                     focus=focus, provider=provider, on_progress=on_progress,
                     roles=roles)


def run_leads(leads: list, offer: str, cfg: dict, *,
              limit: int = 3, focus: str = "",
              provider: SignalProvider | None = None,
              on_progress=None, roles: list | None = None) -> RunResult:
    """Rank the WHOLE list by cheap ICP fit, then spend the expensive pass on the
    top `limit` — the shared core of both the sheet path and the ICP path. This
    replaces `leads[:limit]` ("qualify the first N") with "qualify the best N"."""
    from . import triage, enrich as _enrich
    from .signals import exa_key

    total = len(leads)
    ranked = triage.rank(list(leads), offer, roles)     # score ALL, best-first
    picked = ranked[: max(0, limit)]

    # Enrich blank-email picked leads — covers the SHEET path (which otherwise
    # never gets addresses); a no-op on the ICP path that already enriched.
    key = exa_key(cfg)
    need = [l for l in picked if not (l.email or "").strip()]
    if need and key:
        try:
            _enrich.enrich(need, key)
        except Exception:                               # noqa: BLE001 — never sink a run on enrich
            pass

    provider = provider or NullSignalProvider()
    qual = Qualifier.from_config(cfg)

    out: list[Dossier] = []
    for i, lead in enumerate(picked, 1):
        if on_progress:
            on_progress(i, len(picked), lead)
        # focus is a NEWS topic, NEVER the seller's own offer.
        signals = provider.fetch(lead, focus=focus)
        sig_status = ("found" if signals else
                      ("source_error" if getattr(provider, "errored", False) else "none"))
        dossier = qual.qualify(lead, signals, offer)
        dossier.signal_status = sig_status
        out.append(dossier)
        if i < len(picked):
            time.sleep(0.4)      # gentle pacing — free Groq/Exa keys rate-limit on bursts

    # Real verdicts first (hot→warm→cold by score); leads that FAILED to qualify
    # (status != ok) sink to the bottom but stay in the list — visible and
    # retryable, never silently collapsed into "cold".
    order = {"hot": 0, "warm": 1, "cold": 2}
    out.sort(key=lambda d: (0 if d.status == "ok" else 1,
                            order.get(d.verdict, 3), -d.score))
    return RunResult(dossiers=out, total_in_sheet=total,
                     signal_source=provider.name, all_leads=ranked)
