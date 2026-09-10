"""Render the isolated cinematic-motion experiment; does not launch the GUI."""
from __future__ import annotations

import argparse
import pathlib
import sys

GUI = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GUI / "prism_terminal"))

from core.cinematic import (CinematicTheme, build_demo_spec, render,
                            render_previews, render_transition_previews)  # noqa: E402
from core.cinematic.render import duration, save_project  # noqa: E402
from core import reel_web  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--brand", default="Conciz")
    parser.add_argument("--tagline", default="Long reads, distilled into decisions.")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--previews-only", action="store_true",
                        help="run preflight and write shot stills without encoding the MP4")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    project_file = args.out / "cinematic-lab.json"
    movie_file = args.out / "cinematic-lab.mp4"
    existing = [p for p in (project_file, movie_file) if p.exists()]
    if existing:
        raise SystemExit("Refusing to overwrite: " + ", ".join(map(str, existing)))

    spec = build_demo_spec(CinematicTheme(brand=args.brand, tagline=args.tagline), fps=args.fps)
    faults = reel_web.inspect(spec)
    if faults:
        raise SystemExit("Preflight failed: " + "; ".join(faults))
    save_project(spec, project_file)
    frames = render_previews(spec, args.out)
    if args.previews_only:
        cuts = render_transition_previews(spec, args.out)
        print(f"Preflight passed; {len(frames)} reviewed shots and {len(cuts)} cut frames; "
              f"{duration(spec):.2f}s", flush=True)
        print(args.out.resolve(), flush=True)
        return
    print(f"Preflight passed; {len(frames)} reviewed shots; {duration(spec):.2f}s", flush=True)
    render(spec, movie_file, with_audio=not args.no_audio,
           on_progress=lambda frame, total: print(f"Rendered {frame}/{total}", flush=True))
    print(movie_file.resolve(), flush=True)


if __name__ == "__main__":
    main()
