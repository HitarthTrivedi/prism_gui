"""
Prism Sales Automation — POC runner (headless)
──────────────────────────────────────────────
Proves the whole value chain on a real sheet, before any UI:

    python -m prospector.run_poc "<path to xlsx>" --sheet Steel --limit 3

Reads ~/.prism/config.json for the Groq key (qualifier) and, if present, the
Exa key (live why-now signals). No Exa key → it still runs, qualifying on fit
alone and saying so. No Groq key → it ingests and reports what it *would*
qualify, and tells you to set the key. Honest at every degradation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running both as `python -m prospector.run_poc` and `python run_poc.py`.
if __package__:
    from . import engine, render, signals
else:                                   # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from prospector import engine, render, signals

DEFAULT_OFFER = ("industrial automation / MES-IIoT integration / "
                 "digital-manufacturing services for large manufacturers")
DEFAULT_FOCUS = ("factory automation, Industry 4.0, IIoT, digital "
                 "transformation, new plant or capacity investment")


def load_config() -> dict:
    p = os.path.join(os.path.expanduser("~"), ".prism", "config.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                   # noqa: BLE001 — missing/broken config is fine
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prism Sales Automation POC")
    ap.add_argument("path", help="Path to the leads .xlsx / .csv")
    ap.add_argument("--sheet", default=None, help="One sheet only (e.g. Steel)")
    ap.add_argument("--offer", default=DEFAULT_OFFER, help="What the seller sells")
    ap.add_argument("--focus", default=DEFAULT_FOCUS, help="Signal search focus")
    ap.add_argument("--limit", type=int, default=3, help="How many leads to qualify")
    ap.add_argument("--out", default=None, help="Write the Markdown report here")
    ap.add_argument("--demo", action="store_true",
                    help="Use frozen Exa signals (POC, no Exa key needed)")
    args = ap.parse_args(argv)

    cfg = load_config()
    have_groq = bool(cfg.get("api_key"))
    if args.demo:
        from .poc_fixtures import FixtureSignalProvider
        provider = FixtureSignalProvider()
    else:
        provider = signals.make_provider(cfg, args.focus)
    print(f"· Groq key: {'found' if have_groq else 'MISSING (qualifier will no-op)'}"
          f"  ·  signal source: {provider.name}", file=sys.stderr)

    def prog(i, n, lead):
        print(f"  [{i}/{n}] {lead.display()} …", file=sys.stderr)

    res = engine.run(args.path, args.offer, cfg, sheet_name=args.sheet,
                     limit=args.limit, focus=args.focus, provider=provider,
                     on_progress=prog)

    print(f"· ingested {res.total_in_sheet} leads from the sheet", file=sys.stderr)

    md = render.report(res.dossiers, res.total_in_sheet, res.signal_source)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"· wrote {args.out}", file=sys.stderr)
    print("\n".join(render.to_console(d) for d in res.dossiers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
