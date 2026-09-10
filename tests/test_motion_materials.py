"""Phase 2 of the inspo benchmark: material and camera primitives.

The authored fixture (core.motion.fixtures) is the reference; the model
is only shown a primitive in the catalogue once the fixture proves it.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import camera, continuity  # noqa: E402
from core.motion import inspect as motion_inspect  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402
from core.motion.generate import _NODE_CATALOGUE, parse_scene, scene_instructions  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _render_lane() -> bool:
    if not os.environ.get("PRISM_RUN_RENDER_TESTS"):
        return False
    return importlib.import_module("core.motion.render").is_available()[0]


def _one_scene(nodes, width=1080, height=1920, **scene_extra):
    return {"project": {"duration": 2, "fps": 30, "width": width, "height": height},
            "scenes": [{"id": "one", "duration": 2, "nodes": nodes, **scene_extra}]}


class MaterialSchemaTests(unittest.TestCase):
    def test_material_props_are_clamped_not_rejected(self):
        spec = _one_scene([
            {"id": "g", "type": "glass_panel", "position": [540, 900],
             "blur": 90, "transmission": 1.4, "border_light": -1,
             "specular": "lots", "inner_shadow": 0.3},
            {"id": "l", "type": "light_field", "position": [540, 900],
             "intensity": 3, "spread": 0.01, "drift": 999},
            {"id": "d", "type": "depth_layer", "depth": 9, "children": []},
            {"id": "d2", "type": "depth_layer", "children": []},
        ])
        nodes = validate_motion_spec(spec)["scenes"][0]["nodes"]
        g, l, d, d2 = nodes
        self.assertEqual(g["blur"], 40.0)
        self.assertEqual(g["transmission"], 1.0)
        self.assertEqual(g["border_light"], 0.0)
        self.assertNotIn("specular", g)
        self.assertEqual(g["inner_shadow"], 0.3)
        self.assertEqual((l["intensity"], l["spread"], l["drift"]), (1.0, 0.2, 200.0))
        self.assertEqual(d["depth"], 2.5)
        self.assertEqual(d2["depth"], 1.0)  # the default the runtime also uses

    def test_shot_is_normalized_or_dropped(self):
        spec = {"project": {"duration": 6, "fps": 30}, "scenes": [
            {"id": "a", "duration": 2, "shot": "push", "nodes": []},
            {"id": "b", "duration": 2, "shot": {"intent": "Macro ", "target": "hero",
                                                 "zoom": 9, "easing": "nope"}, "nodes": []},
            {"id": "c", "duration": 2, "shot": {"intent": "dolly"}, "nodes": []},
            {"id": "d", "duration": 2, "shot": {"intent": "orbit", "target": [10, "x"],
                                                 "easing": "sine.inOut"}, "nodes": []},
        ]}
        scenes = validate_motion_spec(spec)["scenes"]
        self.assertEqual(scenes[0]["shot"], {"intent": "push"})
        self.assertEqual(scenes[1]["shot"], {"intent": "macro", "target": "hero",
                                             "zoom": camera.ZOOM_MAX})
        self.assertNotIn("shot", scenes[2])
        self.assertEqual(scenes[3]["shot"], {"intent": "orbit", "target": [10.0, 0.0],
                                             "easing": "sine.inOut"})


class CameraCurveTests(unittest.TestCase):
    def test_shots_compile_to_one_continuous_curve(self):
        spec = validate_motion_spec(json.loads(json.dumps(materials_fixture())))
        resolved = resolve_motion_spec(spec)
        tracks = resolved["camera"]["tracks"]
        self.assertEqual([t["_shot"] for t in tracks],
                         ["open", "reveal", "push", "resolve"])
        self.assertTrue(camera.is_continuous(tracks))
        # the opening set is instant, at t=0, at the centre
        self.assertEqual((tracks[0]["time"], tracks[0]["duration"]), (0.0, 0.0))
        self.assertEqual(tracks[0]["position"], [540.0, 960.0])
        # each later track starts at its scene's start and fits inside it
        for track, scene in zip(tracks[1:], resolved["scenes"]):
            self.assertEqual(track["time"], scene["start"])
            self.assertLessEqual(track["duration"], scene["duration"] + 1e-6)
        # node targets resolve to world positions (the panel inside its
        # depth layer), push multiplies zoom, resolve returns to centre/1.0
        panel = resolved["scenes"][1]["nodes"][1]["children"][0]
        self.assertEqual(tracks[2]["position"], [float(panel["position"][0]),
                                                 float(panel["position"][1])])
        self.assertAlmostEqual(tracks[2]["zoom"], 1.18)
        self.assertEqual(tracks[3]["position"], [540.0, 960.0])
        self.assertEqual((tracks[3]["zoom"], tracks[3]["rotation"]), (1.0, 0.0))

    def test_push_and_pull_are_relative_to_where_the_camera_is(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 2, "shot": {"intent": "push"}},
            {"id": "b", "start": 2.0, "duration": 2, "shot": {"intent": "push"}},
            {"id": "c", "start": 4.0, "duration": 2, "shot": {"intent": "pull"}},
            {"id": "d", "start": 6.0, "duration": 2, "shot": {"intent": "hold"}},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        zooms = [t["zoom"] for t in tracks]
        self.assertAlmostEqual(zooms[1], 1.15, places=3)
        self.assertAlmostEqual(zooms[2], 1.15 * 1.15, places=3)
        self.assertAlmostEqual(zooms[3], 1.15, places=3)
        self.assertEqual(zooms[4], zooms[3])  # hold keeps the state
        self.assertEqual(tracks[4]["easing"], "none")
        self.assertTrue(camera.is_continuous(tracks))

    def test_orbit_alternates_and_parallax_drifts(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 2, "shot": {"intent": "orbit"}},
            {"id": "b", "start": 2.0, "duration": 2, "shot": {"intent": "orbit"}},
            {"id": "c", "start": 4.0, "duration": 2, "shot": {"intent": "parallax"}},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        self.assertEqual(tracks[1]["rotation"], 3.0)
        self.assertEqual(tracks[2]["rotation"], 0.0)
        self.assertNotEqual(tracks[3]["position"][0], tracks[2]["position"][0])
        self.assertEqual(tracks[3]["zoom"], tracks[2]["zoom"])

    def test_an_authored_camera_is_kept_when_no_scene_names_a_shot(self):
        spec = validate_motion_spec({
            "project": {"duration": 2, "fps": 30},
            "camera": {"tracks": [{"time": 0, "position": [540, 960], "zoom": 1.2}]},
            "scenes": [{"id": "a", "duration": 2, "nodes": []}]})
        resolved = resolve_motion_spec(spec)
        self.assertEqual(resolved["camera"]["tracks"][0]["zoom"], 1.2)
        self.assertNotIn("_authored_tracks", resolved["camera"])
        self.assertIsNone(camera.compile_tracks(resolved["scenes"], 1080, 1920, {}))

    def test_an_authored_camera_seeds_the_opening_state_when_shots_exist(self):
        spec = validate_motion_spec({
            "project": {"duration": 2, "fps": 30},
            "camera": {"tracks": [{"time": 0, "position": [400, 800], "zoom": 1.3}]},
            "scenes": [{"id": "a", "duration": 2, "shot": "hold", "nodes": []}]})
        resolved = resolve_motion_spec(spec)
        tracks = resolved["camera"]["tracks"]
        self.assertEqual(tracks[0]["position"], [400.0, 800.0])
        self.assertEqual(tracks[0]["zoom"], 1.3)
        self.assertEqual(tracks[1]["zoom"], 1.3)
        self.assertEqual(len(resolved["camera"]["_authored_tracks"]), 1)

    def test_resolver_is_idempotent_with_shots(self):
        once = resolve_motion_spec(validate_motion_spec(json.loads(json.dumps(materials_fixture()))))
        again = resolve_motion_spec(json.loads(json.dumps(once)))
        self.assertEqual(json.dumps(once["camera"], sort_keys=True),
                         json.dumps(again["camera"], sort_keys=True))


class SafeAreaTests(unittest.TestCase):
    def test_vertical_frames_reserve_platform_bands(self):
        zone = camera.safe_area(1080, 1920)
        self.assertTrue(zone["vertical"])
        self.assertEqual((zone["top"], zone["bottom"]), (211, 1536))
        self.assertLess(zone["title"]["bottom"], zone["action"]["bottom"])
        wide = camera.safe_area(1920, 1080)
        self.assertFalse(wide["vertical"])

    def test_inspect_flags_text_under_platform_chrome_on_9_16_only(self):
        high = _one_scene([{"id": "h", "type": "text", "content": "Hello",
                            "position": [540, 60], "font_size": 48}])
        faults = motion_inspect.inspect(validate_motion_spec(high))
        self.assertTrue(any("top" in f and "platform" in f for f in faults), faults)
        low = _one_scene([{"id": "l", "type": "text", "content": "Hello",
                           "position": [540, 1880], "font_size": 48}])
        faults = motion_inspect.inspect(validate_motion_spec(low))
        self.assertTrue(any("bottom band" in f for f in faults), faults)
        fine = _one_scene([{"id": "f", "type": "text", "content": "Hello",
                            "position": [540, 900], "font_size": 48}])
        self.assertEqual(motion_inspect.inspect(validate_motion_spec(fine)), [])
        wide = _one_scene([{"id": "w", "type": "text", "content": "Hello",
                            "position": [960, 60], "font_size": 48}],
                          width=1920, height=1080)
        self.assertFalse(any("platform" in f for f in
                             motion_inspect.inspect(validate_motion_spec(wide))))

    def test_inspect_walks_into_depth_layers_and_panels(self):
        nested = _one_scene([{"id": "d", "type": "depth_layer", "depth": 1.4,
                              "position": [0, 0], "children": [
                                  {"id": "g", "type": "glass_panel", "position": [540, 200],
                                   "width": 600, "height": 300, "children": [
                                       {"id": "t", "type": "text", "content": "Hi",
                                        "position": [0, -100], "font_size": 48}]}]}])
        faults = motion_inspect.inspect(validate_motion_spec(nested))
        self.assertTrue(any('"t"' in f and "platform" in f for f in faults), faults)

    def test_light_fields_may_bleed_past_the_frame(self):
        spec = _one_scene([{"id": "lf", "type": "light_field", "position": [-400, -400],
                            "width": 1200, "height": 1200}])
        self.assertEqual(motion_inspect.inspect(validate_motion_spec(spec)), [])


class FixtureAndCatalogueTests(unittest.TestCase):
    def test_fixture_validates_compiles_and_passes_every_gate(self):
        spec = validate_motion_spec(json.loads(json.dumps(materials_fixture())))
        for scene in spec["scenes"]:
            self.assertEqual(motion_inspect.inspect(
                {"project": spec["project"], "scenes": [scene]}), [])
        rep = continuity.report(spec)
        self.assertEqual(rep["errors"], [])
        self.assertEqual(rep["warnings"], [])
        self.assertEqual(len(rep["bridges"]), 2)
        resolved = resolve_motion_spec(spec)
        self.assertEqual(resolved["_continuity_compiled"]["errors"], [])
        for scene in resolved["scenes"][1:]:
            self.assertEqual(scene["transition_in"], "morph")

    def test_fixture_scales_with_the_frame(self):
        small = materials_fixture(360, 640)
        panel = small["scenes"][0]["nodes"][1]["children"][0]
        self.assertLess(panel["width"], 360)
        self.assertEqual(validate_motion_spec(json.loads(json.dumps(small)))["project"]["width"], 360)

    def test_runtime_defines_the_primitives_and_applies_parallax(self):
        with open(os.path.join(RUNTIME, "primitives.js"), encoding="utf-8") as fh:
            prims = fh.read()
        for cls in ("class GlassPanelNode", "class LightFieldNode", "class DepthLayerNode"):
            self.assertIn(cls, prims)
        for mapping in ('type === "glass_panel"', 'type === "light_field"',
                        'type === "depth_layer"'):
            self.assertIn(mapping, prims)
        self.assertIn("backdropFilter", prims)
        self.assertIn("applyParallax(camera, w, h)", prims)
        with open(os.path.join(RUNTIME, "runtime.js"), encoding="utf-8") as fh:
            runtime = fh.read()
        self.assertIn("layer.applyParallax(this.camera, this.width, this.height)", runtime)
        self.assertIn("_collectDepthLayers", runtime)
        with open(os.path.join(RUNTIME, "transitions.js"), encoding="utf-8") as fh:
            self.assertIn("morph:", fh.read())

    def test_catalogue_and_scene_prompt_expose_materials_and_shots(self):
        for name in ("glass_panel", "light_field", "depth_layer", "contrast_guard"):
            self.assertIn(name, _NODE_CATALOGUE)
        for intent in camera.SHOT_INTENTS:
            self.assertIn(f"  {intent}", _NODE_CATALOGUE)
        prompt = scene_instructions(0, 2, {"job": "open", "seconds": 2},
                                    skeleton="cinematic_glass")
        self.assertIn('"shot": {"intent"', prompt)
        self.assertIn("safe area", prompt)

    def test_parse_scene_keeps_the_shot(self):
        got = parse_scene('```json\n{"shot": {"intent": "push", "target": "hero"}, '
                          '"transition_in": "morph", "nodes": [{"id": "hero", '
                          '"type": "shape_rect", "position": [1, 2]}]}\n```')
        self.assertEqual(got["shot"], {"intent": "push", "target": "hero"})
        self.assertEqual(got["transition_in"], "morph")
        self.assertEqual(len(got["nodes"]), 1)


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class MaterialsRenderLane(unittest.TestCase):
    """The fixture through the real browser: the glass panel must be a
    visible surface (not the background, not opaque), the light field must
    lift the frame, and the headline on the panel must keep contrast."""

    def test_fixture_frames_show_glass_light_and_readable_copy(self):
        from PIL import Image, ImageStat
        from core import ffmpeg
        render_module = importlib.import_module("core.motion.render")
        spec = materials_fixture(360, 640, fps=12)
        with tempfile.TemporaryDirectory() as folder:
            mp4 = os.path.join(folder, "out.mp4")
            render_module.render(spec, mp4)
            frame = os.path.join(folder, "frame.png")
            subprocess.run([ffmpeg.locate(), "-y", "-loglevel", "error", "-ss", "2.0",
                            "-i", mp4, "-frames:v", "1", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            corner = img.crop((0, h - 40, 40, h))
            panel = img.crop((int(w * 0.35), int(h * 0.42), int(w * 0.65), int(h * 0.50)))
            corner_mean = sum(ImageStat.Stat(corner).mean) / 3
            panel_mean = sum(ImageStat.Stat(panel).mean) / 3
            # the panel is a lit surface, brighter than the dark corner but
            # far from a white card
            self.assertGreater(panel_mean, corner_mean + 8, (panel_mean, corner_mean))
            self.assertLess(panel_mean, 200, panel_mean)
            # the headline area has real contrast (bright ink on the panel)
            head = img.crop((int(w * 0.25), int(h * 0.36), int(w * 0.75), int(h * 0.44)))
            self.assertGreater(head.convert("L").getextrema()[1], 180)


if __name__ == "__main__":
    unittest.main()
