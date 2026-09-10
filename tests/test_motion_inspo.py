"""The inspo benchmark: the reference recreation and the measuring tool.

  · the recreation validates, bridges every cut and keeps one camera curve;
  · content-animation times (text reveals, draw-ons, field phases) are
    scene-local in the spec and shifted onto the global timeline — the
    defect the reference exposed: every scene after the first used to show
    its text already revealed and its lines already drawn;
  · the four reference primitives exist in the runtime and the catalogue;
  · the benchmark finds the 9:16 ad inside a phone recording, scores an
    identical pair near 100 and a different pair well below it;
  · render lane: two scenes of the recreation render and the tile field is
    actually on the frame.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import benchmark, camera, continuity  # noqa: E402
from core.motion import inspect as motion_inspect  # noqa: E402
from core.motion.fixtures import inspo_fixture  # noqa: E402
from core.motion.generate import _NODE_CATALOGUE  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _render_lane() -> bool:
    if not os.environ.get("PRISM_RUN_RENDER_TESTS"):
        return False
    return importlib.import_module("core.motion.render").is_available()[0]


class TheRecreation(unittest.TestCase):
    def test_it_validates_bridges_every_cut_and_keeps_one_camera(self):
        spec = validate_motion_spec(json.loads(json.dumps(inspo_fixture())))
        self.assertAlmostEqual(spec["project"]["duration"], 29.15)
        self.assertEqual(len(spec["scenes"]), 10)
        rep = continuity.report(spec)
        self.assertEqual(rep["errors"], [])
        self.assertEqual(rep["warnings"], [])
        self.assertEqual(len(rep["bridges"]), 9)
        resolved = resolve_motion_spec(spec)
        self.assertTrue(camera.is_continuous(resolved["camera"]["tracks"]))
        self.assertTrue(all(s["transition_in"] == "morph" for s in resolved["scenes"][1:]))

    def test_it_scales_with_the_frame(self):
        small = validate_motion_spec(inspo_fixture(360, 640, fps=12))
        orb = [n for n in small["scenes"][8]["nodes"] if n["id"] == "orb"][0]
        self.assertAlmostEqual(orb["radius"], 170 / 3, places=1)
        self.assertEqual(orb["position"], [166.0, 205.3])


class ContentTimesAreSceneLocal(unittest.TestCase):
    def test_reveal_draw_and_phase_times_shift_with_the_scene(self):
        spec = validate_motion_spec({"project": {"duration": 4, "fps": 30}, "scenes": [
            {"id": "a", "duration": 2, "nodes": []},
            {"id": "b", "duration": 2, "nodes": [
                {"id": "t", "type": "text", "content": "hi", "position": [540, 900]},
                {"id": "t2", "type": "text", "content": "hi", "position": [540, 1000], "reveal_start": 0.4},
                {"id": "arrow", "type": "shape_arrow", "from": [0, 0], "to": [100, 0], "draw_start": 0.5},
                {"id": "tree", "type": "spline_tree", "hub": [0, 0], "leaves": [[10, 10]]},
                {"id": "field", "type": "particle_field", "phases": [
                    {"at": 0, "layout": {"kind": "scatter"}}, {"at": 1.0, "layout": {"kind": "band"}}]},
                {"id": "rect", "type": "shape_rect", "position": [0, 0]}]}]})
        resolved = resolve_motion_spec(spec)
        nodes = {n["id"]: n for n in resolved["scenes"][1]["nodes"]}
        self.assertEqual(nodes["t"]["reveal_start"], 2.0)      # absent meant "at scene start"
        self.assertEqual(nodes["t2"]["reveal_start"], 2.4)
        self.assertEqual(nodes["arrow"]["draw_start"], 2.5)
        self.assertEqual(nodes["tree"]["draw_start"], 2.0)
        self.assertEqual([p["at"] for p in nodes["field"]["phases"]], [2.0, 3.0])
        self.assertNotIn("reveal_start", nodes["rect"])
        again = resolve_motion_spec(json.loads(json.dumps(resolved)))
        self.assertEqual(again["scenes"][1]["nodes"][1]["reveal_start"], 2.4)  # idempotent


class ThePrimitives(unittest.TestCase):
    def test_runtime_and_catalogue_carry_them(self):
        with open(os.path.join(RUNTIME, "primitives.js"), encoding="utf-8") as fh:
            js = fh.read()
        for cls in ("class IconNode", "class OrbNode", "class SplineTreeNode", "class ParticleFieldNode"):
            self.assertIn(cls, js)
        for mapping in ('type === "icon"', 'type === "orb"', 'type === "spline_tree"',
                        'type === "particle_field"'):
            self.assertIn(mapping, js)
        for name in ("particle_field", "spline_tree", "orb", "icon"):
            self.assertIn(f"  {name} ", _NODE_CATALOGUE)

    def test_the_field_random_is_unsigned_and_exits_never_render_early(self):
        """Two runtime defects the recreation exposed: the seeded random
        went negative after its XOR steps (half the tiles landed off the
        top-left of the frame), and an exit tween rendered its from-value
        at creation, so a node with a delayed entrance showed at full
        opacity before it entered."""
        with open(os.path.join(RUNTIME, "primitives.js"), encoding="utf-8") as fh:
            prims = fh.read()
        self.assertIn("h = (h ^ (h >>> 13)) >>> 0", prims)
        self.assertIn("h = (h ^ (h >>> 15)) >>> 0", prims)
        with open(os.path.join(RUNTIME, "runtime.js"), encoding="utf-8") as fh:
            runtime = fh.read()
        self.assertIn('const immediate = blockName === "enter"', runtime)
        self.assertIn("immediateRender: immediate", runtime)
        self.assertIn("if (immediate !== false) apply(from)", runtime)

    def test_inspect_knows_their_boxes(self):
        spec = validate_motion_spec({"project": {"duration": 2, "fps": 30}, "scenes": [{
            "id": "a", "duration": 2, "nodes": [
                {"id": "field", "type": "particle_field", "position": [0, 0]},
                {"id": "tree", "type": "spline_tree", "position": [0, 0], "hub": [0, 0], "leaves": []},
                {"id": "big", "type": "shape_circle", "position": [540, 960], "radius": 900,
                 "fill": "none", "stroke": "#fff"},
                {"id": "ico", "type": "icon", "position": [540, 900], "size": 96},
                {"id": "ball", "type": "orb", "position": [540, 1200], "radius": 100}]}]})
        self.assertEqual(motion_inspect.inspect(spec), [])
        bounds = motion_inspect._node_bounds({"type": "orb", "position": [540, 1200], "radius": 100,
                                              "anchor": [0.5, 0.5]}, 1080, 1920)
        self.assertEqual(bounds, (440.0, 1100.0, 640.0, 1300.0))


class TheBenchmark(unittest.TestCase):
    def test_the_ad_is_found_inside_a_phone_recording(self):
        self.assertEqual(benchmark.ad_region(384, 848), (0, 82, 384, 765))
        self.assertEqual(benchmark.ad_region(1080, 1920), (0, 0, 1080, 1920))
        l, t, r, b = benchmark.band_box(384, 848)
        self.assertEqual((l, r), (0, 384))
        self.assertGreater(t, 82)
        self.assertLess(b, 765 - 200)

    def test_identical_frames_score_high_and_different_ones_low(self):
        from PIL import Image, ImageDraw
        a = Image.new("RGB", (108, 192), (8, 10, 18))
        ImageDraw.Draw(a).rectangle((10, 60, 98, 100), fill=(90, 120, 255))
        b = Image.new("RGB", (108, 192), (240, 240, 250))
        same = benchmark.frame_metrics(a, a)
        self.assertEqual(same["luminance"], 0.0)
        self.assertGreater(same["structure"], 0.99)
        self.assertGreater(benchmark.score([same], 1.0), 95)
        diff = benchmark.frame_metrics(a, b)
        self.assertGreater(diff["luminance"], 150)
        self.assertLess(benchmark.score([diff], -0.5), 30)


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class OnTheFrame(unittest.TestCase):
    def test_the_tile_band_and_the_orb_are_painted(self):
        from PIL import Image, ImageStat
        from core import ffmpeg
        render_module = importlib.import_module("core.motion.render")
        spec = inspo_fixture(360, 640, fps=12)
        spec["scenes"] = [spec["scenes"][1], spec["scenes"][8]]     # the band, the orb
        spec["project"]["duration"] = spec["scenes"][0]["duration"] + spec["scenes"][1]["duration"]
        with tempfile.TemporaryDirectory() as folder:
            mp4 = os.path.join(folder, "out.mp4")
            render_module.render(spec, mp4)
            for t, box, name in ((0.9, (0, 250, 360, 300), "band"), (4.5, (120, 150, 210, 260), "orb")):
                frame = os.path.join(folder, f"{name}.png")
                subprocess.run([ffmpeg.locate(), "-y", "-loglevel", "error", "-ss", str(t), "-i", mp4,
                                "-frames:v", "1", frame], check=True)
                img = Image.open(frame).convert("RGB")
                region = sum(ImageStat.Stat(img.crop(box)).mean) / 3
                corner = sum(ImageStat.Stat(img.crop((0, 600, 40, 640))).mean) / 3
                self.assertGreater(region, corner + 12, (name, region, corner))


if __name__ == "__main__":
    unittest.main()
