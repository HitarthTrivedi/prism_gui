"""Run the inspo-benchmark promotion gate on this machine.

Run from `prism_gui`:

    python examples/motion_promote.py --out ../promotion-linux-01
    python examples/motion_promote.py --out ../promotion-02 --spec ~/.prism/runs/motion_1234.json

Without `--spec`, one brand and tagline go through the authored cinematic
lab (settled and handoff previews), the Motion runtime (the materials
fixture at 1080x1920, 60 fps, rendered and gated) and the Studio page.
With `--spec`, that saved motion graphic is gated instead. Either way the
folder gets `promotion.json` and `promotion.md`: every acceptance criterion
with pass / fail / manual and its evidence, for THIS platform only. Run it
on Linux, Windows and macOS before promoting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import promotion  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="fresh output folder")
    ap.add_argument("--spec", help="a saved motion JSON to gate instead of the fixture")
    ap.add_argument("--brand", default="Prism")
    ap.add_argument("--tagline", default="Long reads, distilled.")
    ap.add_argument("--no-preview-check", action="store_true",
                    help="skip the preview-versus-export comparison")
    args = ap.parse_args()
    progress = lambda d, t: print(f"\r  {d}/{t} frames", end="")  # noqa: E731

    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        report = promotion.evaluate(spec, args.out, on_progress=progress,
                                    preview_check=not args.no_preview_check)
    else:
        result = promotion.same_prompt_everywhere(
            args.brand, args.tagline, args.out, on_progress=progress,
            preview_check=not args.no_preview_check)
        print(f"\nlab previews: {'ok' if result['lab'].get('ok') else result['lab'].get('error', 'failed')}")
        print(f"studio page: {'ok' if result['studio']['ok'] else 'failed'}")
        report = result["motion"]
    print()
    print(promotion.markdown(report))
    return 0 if report["promoted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
