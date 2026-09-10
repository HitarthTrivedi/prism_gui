"""Measure a Prism render against the reference film.

Run from `prism_gui`:

    python examples/inspo_compare.py --candidate ../render.mp4 --out ../inspo-compare-01
    python examples/inspo_compare.py --render --out ../inspo-compare-02

`--render` first renders the built-in recreation (core.motion.fixtures
.inspo_fixture) through the real Motion pipeline at 1080x1920, 60 fps.
Writes `benchmark_sheet.png` (reference row over Prism row, metrics under
each column) and `benchmark.json` with the score, the motion correlation
and the five worst-matching times — the place to look first.
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

from core.motion import benchmark, render  # noqa: E402
from core.motion.fixtures import inspo_fixture  # noqa: E402

DEFAULT_REFERENCE = os.path.join(os.path.dirname(GUI), "inspo.mp4")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference", default=DEFAULT_REFERENCE)
    ap.add_argument("--candidate", help="an MP4 to measure")
    ap.add_argument("--render", action="store_true", help="render the recreation first")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--step", type=float, default=0.5)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    candidate = args.candidate
    if args.render or not candidate:
        spec = inspo_fixture(args.width, args.height, fps=args.fps)
        with open(os.path.join(args.out, "inspo_spec.json"), "w", encoding="utf-8") as fh:
            json.dump(spec, fh, indent=2)
        candidate = render(spec, os.path.join(args.out, "inspo_prism.mp4"),
                           on_progress=lambda d, t: print(f"\r  {d}/{t} frames", end=""))
        print()
    report = benchmark.compare(args.reference, candidate, args.out, step=args.step)
    print(f"score {report['score']}  motion corr {report['motion_correlation']}  "
          f"mean L{report['mean']['luminance']} C{report['mean']['colour']} "
          f"S{report['mean']['structure']}")
    print(f"worst times: {report['worst_times']}")
    print(f"sheet: {report['sheet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
