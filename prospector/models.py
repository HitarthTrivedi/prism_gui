"""
Prism Prospector — the shapes everything passes around
──────────────────────────────────────────────────────
One lead in, one dossier out. These dataclasses are the contract between the
four stages (ingest → signal → qualify → present) so each stage can be built,
tested and swapped on its own.

The dossier is deliberately not a score. A score is a number you are asked to
trust; a dossier is an argument you can read. Every qualifying claim carries
its own evidence and the source that proves it — see `Dimension`. That is the
whole product thesis in a dataclass: proof, not a black box.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── the raw prospect, as it came off the sheet or a search ───────────────────

@dataclass
class Lead:
    name: str = ""
    title: str = ""            # "Designation" on the client's sheet
    company: str = ""
    email: str = ""
    phone: str = ""
    industry: str = ""
    # Everything the source row carried that we did not map, kept verbatim so
    # nothing the owner typed is lost (same forgiving rule as the inquiry
    # register — unknown columns are preserved, never dropped).
    extra: dict = field(default_factory=dict)
    # Production triage + observability, set before the expensive qualify pass.
    fit_score: float = 0.0      # cheap ICP fit rank 0-100 (see triage.py)
    fit_reason: str = ""        # one line: why that score
    drops: list = field(default_factory=list)  # reason codes if the lead fell out

    def display(self) -> str:
        who = self.name or "(no name)"
        where = f" — {self.title}" if self.title else ""
        at = f" @ {self.company}" if self.company else ""
        return f"{who}{where}{at}"


# ── a why-now signal, always with a source and a date (never an inference) ───

@dataclass
class Signal:
    title: str = ""
    snippet: str = ""
    url: str = ""
    published: str = ""        # ISO date string when the source gives one
    source: str = ""           # host / publication

    def cite(self) -> str:
        bits = [b for b in (self.source or self.url, self.published) if b]
        return f"[{', '.join(bits)}]" if bits else ""


# ── one qualification criterion, proven or honestly marked unknown ───────────

# Verdicts are strings, not booleans, because "we could not find evidence" is a
# real and different answer from "no" — and never gets dressed up as "yes".
PASS, WARN, FAIL, UNKNOWN = "pass", "warn", "fail", "unknown"
_MARK = {PASS: "✓", WARN: "⚠", FAIL: "✗", UNKNOWN: "?"}


@dataclass
class Dimension:
    name: str                  # Fit / Need / Timing / Authority / Budget / Competition
    verdict: str = UNKNOWN     # one of PASS/WARN/FAIL/UNKNOWN
    evidence: str = ""         # the reasoning, in one line
    source: str = ""           # the citation that backs it, or "" if unknown

    def mark(self) -> str:
        return _MARK.get(self.verdict, "?")


# ── the finished case file for one lead ──────────────────────────────────────

HOT, WARM, COLD = "hot", "warm", "cold"

# Dossier.status — an outcome that is NOT a real verdict, so a rate-limited or
# failed lead is never mistaken for a genuinely cold one.
OK, QUALIFY_ERROR, NON_JSON, NO_MODEL = "ok", "qualify_error", "non_json", "no_model"
# Dossier.signal_status — did the why-now search find, come up empty, or error?
SIG_FOUND, SIG_NONE, SIG_ERROR = "found", "none", "source_error"


@dataclass
class Dossier:
    lead: Lead
    verdict: str = COLD                     # hot / warm / cold
    score: int = 0                          # 0-100, DERIVED from the dimensions
    dimensions: list[Dimension] = field(default_factory=list)
    opener: str = ""                        # drafted, evidence-grounded first message
    signals: list[Signal] = field(default_factory=list)
    summary: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    # Set when a stage could not run (no signal source, LLM error, …). A dossier
    # that failed a stage says so out loud rather than pretending it qualified.
    note: str = ""
    # Observability: whether qualify actually ran, how grounded the case is, and
    # whether a why-now signal existed — so the UI can say WHY a lead is weak.
    status: str = OK            # ok | qualify_error | non_json | no_model
    confidence: float = 0.0     # 0-1: how much of the why-now story is real
    signal_status: str = SIG_NONE   # found | none | source_error

    def emoji(self) -> str:
        return {HOT: "🔥", WARM: "🟡", COLD: "⚪"}.get(self.verdict, "⚪")
