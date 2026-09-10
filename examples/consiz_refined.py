"""Reproducible Studio art-direction study, using the existing Consiz script.

Run from prism_gui: python examples/consiz_refined.py --out PATH [--render]
Uses bundled, embedded Barlow fonts; no web-font or image-service dependency.
This is an authored reference, not a claim about unreviewed model output.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys

GUI = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GUI / "prism_terminal"))
from core import reel_edit, reel_web  # noqa: E402


def font_css():
    faces = []
    for name, file, weight in (
        ("Consiz Display", "BarlowCondensed-SemiBold.ttf", 600),
        ("Consiz Text", "Barlow-Regular.ttf", 400),
        ("Consiz Text", "Barlow-Medium.ttf", 500),
    ):
        encoded = base64.b64encode((GUI / "assets/fonts" / file).read_bytes()).decode()
        faces.append(f"@font-face{{font-family:'{name}';font-weight:{weight};"
                     f"src:url(data:font/ttf;base64,{encoded}) format('truetype')}}")
    return "".join(faces)


CSS = """
:root{--paper:#f3f0e8;--ink:#232320;--accent:#ce4939;--quiet:#64615a}
.scene{background:var(--paper);color:var(--ink);font-family:'Consiz Text';}
.masthead{position:absolute;left:136px;top:194px;font:500 34px 'Consiz Text';letter-spacing:5px}
.copy{position:absolute;left:130px;top:435px;width:820px;z-index:50}
.eyebrow{margin:0 0 46px;font:500 34px 'Consiz Text';color:var(--quiet)}
h1{margin:0;font:600 166px/.98 'Consiz Display';letter-spacing:-3px}
h1 span{display:block;animation:arrive 700ms cubic-bezier(.22,1,.36,1) both}
h1 span+span{animation-delay:120ms}
.accent{color:var(--accent)}
.support{position:absolute;left:136px;top:1400px;width:785px;margin:0;
font:400 44px/1.25 'Consiz Text';color:var(--quiet);
animation:arrive 600ms cubic-bezier(.22,1,.36,1) 350ms both;z-index:50}
.signal{position:absolute;left:136px;top:1010px;width:808px;height:280px;overflow:visible}
.signal path{fill:none;stroke:var(--ink);stroke-width:2;stroke-linecap:round}
.signal .core{stroke:var(--accent);stroke-width:5;stroke-dasharray:1100;
stroke-dashoffset:0;animation:trace 1000ms cubic-bezier(.22,1,.36,1) both}
@keyframes arrive{from{opacity:0;transform:translateY(40px)}to{opacity:1;transform:translateY(0)}}
@keyframes trace{from{stroke-dashoffset:1100}to{stroke-dashoffset:0}}
"""


def signal(mode):
    """One motif: interference resolves into a clear signal, not random ornaments."""
    paths = []
    if mode == "noise":
        for n in range(9):
            y = 35 + n * 26
            paths.append(f"<path opacity='.25' d='M0 {y} C150 {y-70} 205 {y+95} "
                         f"330 {y} S550 {y-95} 670 {y} S750 {y+30} 808 {y}'/>")
    if mode == "focus":
        paths.append("<path opacity='.23' d='M0 140 H240 M568 140 H808'/>")
        paths.append("<path class='core' d='M240 140 H568'/>")
    elif mode == "arrow":
        paths.append("<path class='core' d='M0 140 H760 M670 50 L760 140 L670 230'/>")
    else:
        paths.append("<path class='core' d='M0 140 H808'/>")
    return "<svg class='signal' viewBox='0 0 808 280' aria-hidden='true'>" + "".join(paths) + "</svg>"


def build_project():
    beats = [
        (4.5, "Too much noise?", "Cut through", "the noise.", "", "noise", ""),
        (3.5, "Reset", "Keep it", "simple.", "Less clutter. More clarity.", "line", "h1{font-size:194px}"),
        (3.5, "Next", "Find what", "matters.", "Move with confidence.", "focus", ""),
        (3.5, "Meet", "Consiz", "", "A name worth discovering.", "line", "h1{font-size:276px;letter-spacing:-5px}.copy{top:530px}"),
        (3, "Your turn", "Ready to", "discover?", "", "arrow", ""),
        (4, "", "Discover", "Consiz.", "See what Consiz is all about.", "line", "h1{font-size:194px}.copy{top:490px}"),
    ]
    scenes = []
    for seconds, kicker, first, second, supporting, motif, css in beats:
        headline = f"<span>{first}</span>" + (f"<span class='accent'>{second}</span>" if second else "")
        body = ("<div class='masthead'>CONSIZ</div><div class='copy'>"
                + (f"<p class='eyebrow'>{kicker}</p>" if kicker else "")
                + f"<h1>{headline}</h1></div>" + signal(motif)
                + (f"<p class='support'>{supporting}</p>" if supporting else ""))
        scenes.append({"seconds": seconds, "html": body, "css": css})
    project = {"fps": 30, "design": {"name": "Consiz — from noise to signal",
        "direction": "Warm paper, narrow expressive type, one coral signal. Interference resolves "
                     "to a line, isolates a point of focus, then becomes a directional invitation. "
                     "Brief entrances, long reading holds, consistent alignment, no decorative counters.",
        "css": font_css() + CSS, "cut_ms": 220}, "scenes": scenes}
    reel_edit.ensure_stable_ids(project)
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    project = build_project()
    project_path = args.out / "consiz-refined.json"
    if project_path.exists():
        raise SystemExit(f"Refusing to overwrite {project_path}; choose a new output directory.")
    project_path.write_text(json.dumps(project, indent=2), encoding="utf-8")
    faults = reel_web.inspect(project)
    if faults:
        raise SystemExit("Preflight failed: " + "; ".join(faults))
    plan, total = reel_web._plan(project, project["fps"])
    for i, scene in enumerate(plan, 1):
        frame = round((scene["start"] + scene["dur"] * .60) * project["fps"] / 1000)
        reel_web.still(project, frame, str(args.out / f"scene-{i}.png"))
    print(f"Preflight passed; {len(plan)} reference frames; {total / project['fps']:.2f}s", flush=True)
    if args.render:
        reel_web.render(project, str(args.out / "consiz-refined.mp4"),
                        on_progress=lambda frame, count: print(f"Rendered {frame}/{count}", flush=True))
    print(args.out.resolve(), flush=True)


if __name__ == "__main__":
    main()
