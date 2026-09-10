"""Contracts for the isolated cinematic-motion experiment."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core import reel_web
from core.cinematic import CinematicTheme, build_demo_spec, render_transition_previews
from core.cinematic import render as render_movie
from core.cinematic.render import _soundtrack, duration


class CinematicProject(unittest.TestCase):
    def setUp(self):
        self.spec = build_demo_spec(CinematicTheme(brand="Aperture", tagline="See the signal."), fps=24)

    def test_is_a_separate_six_shot_project_with_one_visual_arc(self):
        self.assertEqual(len(self.spec["scenes"]), 6)
        self.assertEqual(self.spec["fps"], 24)
        self.assertEqual(self.spec["_cinematic_lab"]["version"], 3)
        self.assertEqual(self.spec["_cinematic_lab"]["profile"], "continuous-glass")
        direction = self.spec["design"]["direction"]
        for idea in ("Scattered information", "structured evidence", "brand"):
            self.assertIn(idea, direction)
        self.assertNotIn("asset:", reel_web.build_html(self.spec))

    def test_brand_and_tagline_reach_the_end_frame(self):
        end = self.spec["scenes"][-1]["html"]
        self.assertIn("Aperture", end)
        self.assertIn("See the signal.", end)

    def test_glass_profile_uses_nested_optical_surfaces(self):
        html = reel_web.build_html(self.spec)
        css = self.spec["design"]["css"]
        for class_name in (
            "source-shell", "intake-shell", "question-shell", "answer-shell",
            "knowledge-shell", "memory-shell", "final-orb-shell",
        ):
            self.assertIn(class_name, html)
        self.assertIn("backdrop-filter:blur", css)
        self.assertIn("inset 0 1px", css)
        self.assertNotIn("'Inter'", css)

    def test_adjacent_shots_share_a_visual_handoff(self):
        scenes = self.spec["scenes"]
        self.assertTrue(all(scene["cut"] == "flow" for scene in scenes))
        self.assertGreaterEqual(self.spec["design"]["cut_ms"], 900)
        self.assertIn("particles-scatter-band", scenes[0]["html"])
        self.assertIn("particles-band-core", scenes[1]["html"])
        self.assertIn("particles-core-graph", scenes[2]["html"])
        self.assertIn("handoff-light", scenes[2]["html"])
        self.assertIn("particles-final-orbit", scenes[5]["html"])

    def test_every_animation_has_deterministic_fill_mode(self):
        css = self.spec["design"]["css"]
        declarations = [part.split("}", 1)[0] for part in css.split("animation:")[1:]]
        self.assertTrue(declarations)
        for declaration in declarations:
            self.assertIn("both", declaration)

    def test_project_passes_static_structure_checks(self):
        self.assertEqual(reel_web.structural_faults(self.spec), [])
        self.assertGreater(duration(self.spec), 20)
        self.assertLess(duration(self.spec), 30)

    def test_audio_mux_is_optional_and_reuses_studio_capture(self):
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(reel_web, "render", return_value="silent.mp4") as capture:
            output = os.path.join(folder, "silent.mp4")
            self.assertEqual(render_movie(self.spec, output, with_audio=False), "silent.mp4")
            capture.assert_called_once_with(
                self.spec, output, on_progress=None, capture_quality=98, crf=16)

    def test_transition_review_captures_three_frames_per_cut(self):
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(reel_web, "still", return_value="frame.png") as still:
            paths = render_transition_previews(self.spec, folder)
        self.assertEqual(len(paths), 15)
        self.assertEqual(still.call_count, 15)
        self.assertTrue(paths[0].endswith("cut-1-before.png"))
        self.assertTrue(paths[-1].endswith("cut-5-after.png"))


def _ffmpeg_ready():
    try:
        return bool(reel_web.ffmpeg_path())
    except reel_web.ReelError:
        return False


@unittest.skipUnless(_ffmpeg_ready(), "needs ffmpeg")
class CinematicSound(unittest.TestCase):
    def test_procedural_reference_track_is_real_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "score.m4a")
            _soundtrack(path, 1.2, [.4, .8])
            self.assertGreater(os.path.getsize(path), 1000)


if __name__ == "__main__":
    unittest.main()
