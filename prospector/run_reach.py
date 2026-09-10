"""
Prism Sales Automation — reach POC runner (headless)
─────────────────────────────────────────────────────
Proves the last stage: a qualified sheet becomes real, per-lead emails that
cite each prospect's own why-now — ready for a person to read and send.

    python -m prospector.run_reach "<leads.xlsx>" --limit 5 --demo \
           --from "VITRACX Sales" --out outreach.csv

It PREPARES only. Sending is a deliberate second step (`reach.send`, gated on a
configured account) and is intentionally not wired to a flag here — the POC's
job is to show the drafts, not to mail real people. Same degrade-don't-fail
contract as run_poc: no Groq key → it falls back to each dossier's grounded
opener and says so.
"""
from __future__ import annotations

import argparse
import sys

if __package__:
    from . import engine, reach, signals
    from .run_poc import DEFAULT_FOCUS, DEFAULT_OFFER, load_config
else:                                   # pragma: no cover
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from prospector import engine, reach, signals
    from prospector.run_poc import DEFAULT_FOCUS, DEFAULT_OFFER, load_config


def to_console(d: reach.Draft) -> str:
    dos, lead = d.dossier, d.dossier.lead
    head = (f"{dos.emoji()}  {lead.company} — {lead.name}  "
            f"[{dos.verdict.upper()} {dos.score}]  → {lead.email or '(no email)'}")
    lines = [head]
    if dos.signals:
        s = dos.signals[0]
        lines.append(f"    why-now: {s.title} {s.cite()}")
    lines.append(f"    SUBJECT: {d.subject}")
    lines.append("")
    lines += ["    " + ln for ln in d.body.splitlines()]
    if d.note:
        lines.append(f"    · {d.note}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prism Sales Automation — reach POC")
    ap.add_argument("path", help="Path to the leads .xlsx / .csv")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--offer", default=DEFAULT_OFFER)
    ap.add_argument("--focus", default=DEFAULT_FOCUS)
    ap.add_argument("--limit", type=int, default=5, help="How many leads to qualify")
    ap.add_argument("--from", dest="sender", default="", help="Sign-off name/org")
    ap.add_argument("--out", default=None, help="Write the outreach CSV here")
    ap.add_argument("--claims", default=None,
                    help="File of approved value claims (one per line) — the ONLY selling points the draft may make")
    ap.add_argument("--demo", action="store_true",
                    help="Use frozen Exa signals (no Exa key needed)")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.demo:
        from .poc_fixtures import FixtureSignalProvider
        provider = FixtureSignalProvider()
    else:
        provider = signals.make_provider(cfg, args.focus)
    print(f"· Groq key: {'found' if cfg.get('api_key') else 'MISSING (drafts fall back to openers)'}"
          f"  ·  signal source: {provider.name}", file=sys.stderr)

    claims = reach.load_claims(args.claims)

    res = engine.run(args.path, args.offer, cfg, sheet_name=args.sheet,
                     limit=args.limit, focus=args.focus, provider=provider,
                     on_progress=lambda i, n, l: print(f"  qualify [{i}/{n}] {l.display()} …", file=sys.stderr))

    targets = reach.reachable(res.dossiers)
    print(f"· qualified {len(res.dossiers)} of {res.total_in_sheet} · "
          f"{len(targets)} reachable (hot/warm with an email)", file=sys.stderr)
    print(f"· value claims: {len(claims)} "
          f"({'model may cite only these' if claims else 'none given — drafts will make NO numeric claim'})",
          file=sys.stderr)

    drafts = reach.draft_batch(
        res.dossiers, args.offer, cfg, sender=args.sender, claims=claims,
        on_progress=lambda i, n, l: print(f"  draft   [{i}/{n}] {l.display()} …", file=sys.stderr))

    print("\n\n".join(to_console(d) for d in drafts) or "(no reachable leads to draft)")

    if args.out:
        reach.write_outreach(drafts, args.out)
        print(f"\n· wrote {args.out} — {len(drafts)} prepared message(s), status=draft", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
