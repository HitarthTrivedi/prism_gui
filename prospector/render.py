"""Render a Dossier as text or Markdown — for the POC console and, later, export."""
from __future__ import annotations

from .models import Dossier


def to_markdown(d: Dossier) -> str:
    lead = d.lead
    lines = [f"### {d.emoji()} {lead.company or '(company?)'} — {lead.name}"]
    if lead.title:
        lines.append(f"*{lead.title}*")
    lines.append(f"**Verdict: {d.verdict.upper()}** · score {d.score}"
                 + (f" · {d.summary}" if d.summary else ""))
    if d.note:
        lines.append(f"> ⚠ {d.note}")
    lines.append("")
    lines.append("| Dimension | | Evidence | Source |")
    lines.append("|---|---|---|---|")
    for dim in d.dimensions:
        lines.append(f"| {dim.name} | {dim.mark()} | {dim.evidence or '—'} | {dim.source or '—'} |")
    if d.opener:
        lines.append("")
        lines.append(f"**Opener:** {d.opener}")
    if d.signals:
        lines.append("")
        lines.append("*Signals used:* " + "; ".join(
            f"{s.title} {s.cite()}".strip() for s in d.signals if s.title))
    return "\n".join(lines)


def to_console(d: Dossier) -> str:
    lead = d.lead
    out = [f"{d.emoji()}  {lead.company or '(company?)'} — {lead.name}"
           f"  [{d.verdict.upper()} {d.score}]"]
    if lead.title:
        out.append(f"    {lead.title}")
    if d.summary:
        out.append(f"    {d.summary}")
    if d.note:
        out.append(f"    ! {d.note}")
    for dim in d.dimensions:
        out.append(f"    {dim.mark()} {dim.name:<12} {dim.evidence or '—'}"
                   + (f"   [{dim.source}]" if dim.source else ""))
    if d.opener:
        out.append(f"    ✎ {d.opener}")
    return "\n".join(out)


def report(dossiers, total: int, signal_source: str) -> str:
    hot = sum(1 for d in dossiers if d.verdict == "hot")
    warm = sum(1 for d in dossiers if d.verdict == "warm")
    head = (f"# Sales Automation — POC run\n\n"
            f"{len(dossiers)} of {total} leads qualified · signal source: {signal_source} · "
            f"{hot} hot, {warm} warm\n")
    return head + "\n\n---\n\n".join(to_markdown(d) for d in dossiers)
