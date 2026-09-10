"""Render the authored material/camera fixture through the real Motion path.

Run from `prism_gui`:

    python examples/motion_materials.py --out ../materials-review-01

Writes `materials.json` (the resolved spec: compiled camera curve and
continuity bridges included), `materials.mp4`, and a `frames/` folder with
the start, midpoint, settled and exit frame of every scene for review. No
AI is involved; this is the fixture the runtime primitives are validated
against before the model is shown them.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core import ffmpeg  # noqa: E402
from core.motion import render, resolve_motion_spec, validate_motion_spec  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="fresh output folder")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--brand", default="Prism")
    ap.add_argument("--tagline", default="Long reads, distilled.")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    spec = materials_fixture(args.width, args.height, args.fps,
                             brand=args.brand, tagline=args.tagline)
    resolved = resolve_motion_spec(validate_motion_spec(json.loads(json.dumps(spec))))
    with open(os.path.join(args.out, "materials.json"), "w", encoding="utf-8") as fh:
        json.dump(resolved, fh, indent=2, ensure_ascii=False)
    compiled = resolved.get("_continuity_compiled") or {}
    print(f"camera tracks: {len(resolved.get('camera', {}).get('tracks', []))}  "
          f"bridges: {len(compiled.get('bridges', []))}  "
          f"errors: {len(compiled.get('errors', []))}")

    mp4 = os.path.join(args.out, "materials.mp4")
    render(spec, mp4, on_progress=lambda d, t: print(f"\r  {d}/{t} frames", end=""))
    print(f"\nwrote {mp4}")

    frames = os.path.join(args.out, "frames")
    os.makedirs(frames, exist_ok=True)
    ff = ffmpeg.locate()
    for scene in resolved["scenes"]:
        start, dur = float(scene["start"]), float(scene["duration"])
        for label, at in (("start", start + 0.05), ("mid", start + dur * 0.5),
                          ("settled", start + dur * 0.8), ("exit", start + dur - 0.05)):
            out = os.path.join(frames, f"{scene['id']}_{label}.png")
            subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{at:.3f}",
                            "-i", mp4, "-frames:v", "1", out], check=False)
    print(f"review frames in {frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
