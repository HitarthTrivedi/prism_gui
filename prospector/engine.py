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

from . import identity, sheet
from .models import Dossier, Lead
from .qualify import Qualifier
from .signals import SignalProvider, NullSignalProvider


@dataclass
class RunResult:
    dossiers: list[Dossier]
    total_in_sheet: int
    signal_source: str
    all_leads: list = field(default_factory=list)
    # Leads the run passed over before ranking — pulled in an earlier session,
    # or a repeat of someone earlier in the same list. Counted rather than
    # silently dropped, so a list that shrank can say why.
    skipped_seen: int = 0
    duplicates: int = 0


def filter_new(leads: list, skip=None, stats: dict | None = None) -> list:
    """The leads worth a slot in this run: each person once (first row wins,
    `identity.dedupe`), minus anyone `in skip` — the people earlier sessions
    already pulled. Pure, and separate from `run_leads` so a caller can ask
    again once enrich has given leads e-mails, and with them new identity keys.

    Repeats go first, so a person listed twice and also seen before is one
    duplicate and one skip, not two skips. If `stats` is a dict,
    'duplicates' and 'skipped_seen' are set on it."""
    kept, dropped = identity.dedupe(leads)
    seen_before = 0
    if skip is not None:
        fresh = [lead for lead in kept if lead not in skip]
        seen_before = len(kept) - len(fresh)
        kept = fresh
    if stats is not None:
        stats["duplicates"] = len(dropped)
        stats["skipped_seen"] = seen_before
    return kept


def run(path: str, offer: str, cfg: dict, *,
        sheet_name: str | None = None,
        limit: int = 3,
        focus: str = "",
        provider: SignalProvider | None = None,
        on_progress=None,
        roles: list | None = None,
        skip=None,
        stats: dict | None = None) -> RunResult:
    """Qualify the BEST `limit` leads of a SHEET against `offer` — among the
    people not already in `skip` (see `run_leads`)."""
    return run_leads(sheet.load(path, sheet_name), offer, cfg, limit=limit,
                     focus=focus, provider=provider, on_progress=on_progress,
                     roles=roles, skip=skip, stats=stats)


def run_leads(leads: list, offer: str, cfg: dict, *,
              limit: int = 3, focus: str = "",
              provider: SignalProvider | None = None,
              on_progress=None, roles: list | None = None,
              skip=None, stats: dict | None = None) -> RunResult:
    """Rank the WHOLE list by cheap ICP fit, then spend the expensive pass on the
    top `limit` — the shared core of both the sheet path and the ICP path. This
    replaces `leads[:limit]` ("qualify the first N") with "qualify the best N".

    The list is cut to NEW people (`filter_new`) BEFORE ranking, so `limit`
    buys the best N people not already worked; filtering after the cut would
    hand back fewer than `limit`. `total_in_sheet` still counts every lead
    passed in. The two counts land on the RunResult and are ADDED into `stats`
    when a dict is given, so one dict carried across stages keeps totals."""
    from . import triage, enrich as _enrich
    from .signals import exa_key

    total = len(leads)
    counts: dict = {}
    fresh = filter_new(leads, skip, counts)
    if stats is not None:
        for name, n in counts.items():
            stats[name] = stats.get(name, 0) + n
    ranked = triage.rank(fresh, offer, roles)           # score ALL new, best-first
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
                     signal_source=provider.name, all_leads=ranked,
                     skipped_seen=counts["skipped_seen"],
                     duplicates=counts["duplicates"])
