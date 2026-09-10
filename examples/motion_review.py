"""Review a motion graphic the way the acceptance criteria do.

Run from `prism_gui`:

    python examples/motion_review.py --out ../motion-review-01
    python examples/motion_review.py --out ../motion-review-02 --spec ~/.prism/runs/motion_1234.json

Renders the spec (the authored materials fixture by default), pulls the
start / midpoint / settled / exit frame of every scene and the 17 / 50 /
83 % frame of every continuity handoff onto `review_sheet.png`, runs the
hold-time, cold-cut, contrast, one-frame-pop and export checks, prints the
beat grid, and writes `review.json`. Add `--preview-check` to also compare
the Studio's runtime preview with the exported frames at every review
time (needs Playwright's Chromium).
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

from core.motion import beats, review  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402
from core.motion.studio import EDITS_KEY, resolved_for  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="fresh output folder")
    ap.add_argument("--spec", help="a saved motion JSON (default: the materials fixture)")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--preview-check", action="store_true")
    args = ap.parse_args()

    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    else:
        spec = materials_fixture(args.width, args.height, args.fps)

    report = review.review_sheet(
        spec, args.out, on_progress=lambda d, t: print(f"\r  {d}/{t} frames", end=""))
    print(f"\nsheet: {report['sheet']}")
    print(f"beats: {report['beats']['bpm']:g} bpm ({report['beats']['source']}), "
          f"{report['beats']['on_beat']} marker(s) on the beat, "
          f"{report['beats']['off_beat']} off")
    for line in report["warnings"]:
        print(f"  warning: {line}")
    for line in report["faults"]:
        print(f"  FAULT: {line}")
    if args.preview_check:
        resolved = resolved_for(spec, spec.get(EDITS_KEY))
        times = [fr["time"] for fr in report["frames"]]
        diffs = review.preview_matches_export(resolved, report["mp4"], times)
        for line in diffs:
            print(f"  FAULT: {line}")
        report["faults"].extend(diffs)
    grid = beats.timing_grid(resolved_for(spec, spec.get(EDITS_KEY)))
    for m in grid["markers"]:
        mark = "on beat" if m["on_beat"] else f"{m['drift'] * 1000:+.0f}ms"
        print(f"  {m['time']:6.2f}s  {m['kind']:<7} {m['label']}  ({mark})")
    print("PASS" if not report["faults"] else f"{len(report['faults'])} fault(s)")
    return 0 if not report["faults"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
