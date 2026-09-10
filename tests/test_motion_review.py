"""Phase 4 of the inspo benchmark: visual review, beats and the export gate.

  · the timing grid picks a tempo the cuts land on, or takes the
    production track's, and marks every cut, bridge, camera move and text
    entrance with its drift from the beat;
  · text must hold long enough to be read; a cinematic cut may not be
    cold; a rendered headline must keep contrast; a cut may not pop;
  · the export gate reads FFmpeg's own probe of the file;
  · production audio is a spec block that is validated, checked for
    missing files before a frame is rendered, and muxed at export;
  · render lane: the review sheet of the fixture passes every check and
    the Studio preview matches the exported frames.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest

GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import beats, review, studio  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402
from core.motion.schema import MotionValidationError, validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _render_lane() -> bool:
    if not os.environ.get("PRISM_RUN_RENDER_TESTS"):
        return False
    return importlib.import_module("core.motion.render").is_available()[0]


def _resolved(**kw):
    spec = materials_fixture(**kw) if kw else materials_fixture()
    return studio.resolved_for(spec, [])


class TheTimingGrid(unittest.TestCase):
    def test_a_tempo_is_chosen_so_the_cuts_land_on_beats(self):
        self.assertEqual(beats.choose_bpm([2.5, 5.0]), 120.0)
        self.assertEqual(beats.choose_bpm([]), 110.0)
        self.assertEqual(beats.choose_bpm([2.0, 4.0, 6.0]), 120.0)   # 90 would also fit; 120 is nearer 110

    def test_the_grid_marks_cuts_bridges_camera_and_text(self):
        grid = beats.timing_grid(_resolved())
        self.assertEqual((grid["bpm"], grid["source"]), (120.0, "cuts"))
        self.assertEqual(grid["beats"][:3], [0.0, 0.5, 1.0])
        self.assertEqual(grid["bars"][:2], [0.0, 2.0])
        kinds = {m["kind"] for m in grid["markers"]}
        self.assertEqual(kinds, {"cut", "bridge", "camera", "enter"})
        cuts = [m for m in grid["markers"] if m["kind"] == "cut"]
        self.assertEqual([m["time"] for m in cuts], [2.5, 5.0])
        self.assertTrue(all(m["on_beat"] for m in cuts))
        self.assertGreater(grid["on_beat"], 0)

    def test_the_production_tracks_tempo_wins(self):
        resolved = _resolved()
        resolved["audio"] = {"bpm": 96, "offset": 0.1}
        grid = beats.timing_grid(resolved)
        self.assertEqual((grid["bpm"], grid["offset"], grid["source"]), (96.0, 0.1, "audio"))
        self.assertAlmostEqual(grid["beats"][1] - grid["beats"][0], 0.625)
        self.assertEqual(beats.timing_grid(resolved, bpm=100)["source"], "argument")

    def test_scene_lengths_snap_to_whole_beats(self):
        spec = materials_fixture()
        spec["scenes"][0]["duration"] = 2.3
        spec["scenes"][1]["duration"] = 2.7
        snapped = beats.snap_scene_lengths(spec, 120)
        self.assertEqual([s["duration"] for s in snapped["scenes"]], [2.5, 2.5, 2.5])
        self.assertEqual(snapped["project"]["duration"], 7.5)
        self.assertEqual(spec["scenes"][0]["duration"], 2.3)      # the source is untouched


class StaticChecks(unittest.TestCase):
    def test_text_must_hold_long_enough_to_be_read(self):
        spec = {"project": {"duration": 1.5, "fps": 30}, "scenes": [{
            "id": "a", "duration": 1.5, "nodes": [
                {"id": "long", "type": "text", "position": [540, 900],
                 "content": "twelve words in a headline that nobody could read in this time",
                 "animation": {"enter": {"time": 0.3, "duration": 0.6,
                                         "tweens": [{"channel": "opacity", "from": 0, "to": 1}]}}},
                {"id": "short", "type": "text", "position": [540, 1100], "content": "Go"}]}]}
        faults = review.hold_faults(validate_motion_spec(spec))
        self.assertEqual(len(faults), 1)
        self.assertIn('"long"', faults[0])
        self.assertIn("needs", faults[0])
        self.assertEqual(review.hold_faults(_resolved()), [])

    def test_a_cold_cut_is_named_under_the_cinematic_profile(self):
        spec = materials_fixture()
        spec["scenes"][1]["duration"] = 0.05
        resolved = studio.resolved_for(spec, [])
        self.assertTrue(any("cold cut" in f for f in review.cold_cut_faults(resolved)))
        spec.pop("_motion_profile")
        self.assertEqual(review.cold_cut_faults(studio.resolved_for(spec, [])), [])

    def test_review_frames_cover_every_scene_and_handoff(self):
        frames = review.frame_times(_resolved())
        self.assertEqual(len([f for f in frames if f["kind"] == "scene"]), 12)
        handoffs = [f for f in frames if f["kind"] == "handoff"]
        self.assertEqual(len(handoffs), 6)
        self.assertEqual([f["label"] for f in handoffs[:3]], ["17%", "50%", "83%"])
        self.assertEqual(handoffs[0]["key"], "panel")


class FrameMaths(unittest.TestCase):
    def test_contrast_ratio_separates_readable_from_muddy(self):
        from PIL import Image, ImageDraw
        clear = Image.new("RGB", (120, 40), (20, 24, 40))
        ImageDraw.Draw(clear).text((4, 10), "HELLO WORLD", fill=(245, 247, 255))
        muddy = Image.new("RGB", (120, 40), (110, 112, 120))
        ImageDraw.Draw(muddy).text((4, 10), "HELLO WORLD", fill=(140, 142, 150))
        self.assertGreater(review.contrast_ratio(clear), review.MIN_CONTRAST_RATIO)
        self.assertLess(review.contrast_ratio(muddy), review.MIN_CONTRAST_RATIO)

    def test_a_pop_is_a_single_jump_far_above_the_motion_around_it(self):
        from PIL import Image
        def frame(level):
            return Image.new("RGB", (64, 64), (level, level, level))
        smooth = [frame(v) for v in (100, 104, 108, 112, 116, 120, 124)]
        self.assertFalse(review.is_pop(smooth))
        popped = [frame(v) for v in (100, 104, 108, 200, 204, 208, 212)]
        self.assertTrue(review.is_pop(popped))
        static = [frame(100)] * 7
        self.assertFalse(review.is_pop(static))

    def test_the_probe_reads_ffmpegs_own_report(self):
        text = ("Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'x.mp4':\n"
                "  Duration: 00:00:07.50, start: 0.000000, bitrate: 900 kb/s\n"
                "  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, "
                "progressive), 360x640, 850 kb/s, 12 fps, 12 tbr, 12288 tbn (default)\n")
        got = review.parse_probe(text)
        self.assertEqual(got, {"duration": 7.5, "codec": "h264", "width": 360,
                               "height": 640, "fps": 12.0})
        self.assertEqual(review.parse_probe("garbage"), {})
        self.assertEqual(review.export_gate(_resolved(), "/nonexistent.mp4"),
                         ["no file at /nonexistent.mp4"])


class ProductionAudio(unittest.TestCase):
    def test_the_audio_block_is_normalised(self):
        spec = {"project": {"duration": 2, "fps": 30}, "scenes": [{"id": "a", "duration": 2, "nodes": []}],
                "audio": {"music": " /tmp/track.wav ", "voiceover": "", "bpm": 500, "offset": "x",
                          "music_volume": 3, "junk": 1}}
        got = validate_motion_spec(spec)["audio"]
        self.assertEqual(got, {"music": "/tmp/track.wav", "bpm": 240.0, "music_volume": 1.0})
        spec["audio"] = "nope"
        self.assertNotIn("audio", validate_motion_spec(spec))
        spec["audio"] = {"junk": 1}
        self.assertNotIn("audio", validate_motion_spec(spec))

    def test_a_missing_track_stops_the_render_before_any_frame(self):
        render_module = importlib.import_module("core.motion.render")
        spec = materials_fixture(360, 640, fps=12)
        spec["audio"] = {"music": "/nonexistent/track.wav"}
        self.assertEqual(render_module.audio_faults(validate_motion_spec(spec)),
                         ["audio: the music file is not on this machine (/nonexistent/track.wav)"])
        with self.assertRaises(MotionValidationError) as ctx:
            render_module.render(spec, "/nonexistent/out.mp4")
        self.assertIn("not on this machine", str(ctx.exception))

    def test_no_audio_means_the_silent_film_is_the_deliverable(self):
        render_module = importlib.import_module("core.motion.render")
        self.assertEqual(render_module._mux_production_audio({"project": {}}, "/x.mp4"), "/x.mp4")


class TheStudioShowsTheGrid(unittest.TestCase):
    def test_preview_payload_carries_beats_and_the_timeline_draws_them(self):
        payload = studio.preview_payload(materials_fixture(), [])
        self.assertEqual(payload["beats"]["bpm"], 120.0)
        self.assertTrue(payload["beats"]["markers"])
        with open(os.path.join(RUNTIME, "studio.js"), encoding="utf-8") as fh:
            js = fh.read()
        for piece in ("ms-beat", "ms-offbeat", "beatTicks(h, tot)", "ms-beat-tag"):
            self.assertIn(piece, js, piece)


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class TheReviewSheet(unittest.TestCase):
    def test_the_fixture_passes_every_gate_and_preview_matches_export(self):
        spec = materials_fixture(360, 640, fps=12)
        with tempfile.TemporaryDirectory() as folder:
            report = review.review_sheet(spec, folder)
            self.assertTrue(os.path.isfile(report["sheet"]))
            self.assertTrue(os.path.isfile(os.path.join(folder, "review.json")))
            self.assertEqual(len(report["frames"]), 12 + 6)
            for fr in report["frames"]:
                self.assertTrue(os.path.isfile(fr["path"]), fr)
            self.assertEqual(report["faults"], [])
            self.assertEqual(report["beats"]["bpm"], 120.0)
            resolved = studio.resolved_for(spec, [])
            self.assertEqual(review.export_gate(resolved, report["mp4"], fps=12), [])
            times = [fr["time"] for fr in report["frames"] if fr["label"] in ("settled", "50%")]
            self.assertEqual(review.preview_matches_export(resolved, report["mp4"], times), [])

    def test_a_muddy_headline_is_caught_on_the_rendered_frame(self):
        spec = materials_fixture(360, 640, fps=12)
        spec["scenes"] = spec["scenes"][:1]
        spec["project"]["duration"] = 2.5
        headline = spec["scenes"][0]["nodes"][1]["children"][0]["children"][0]
        headline["fill"] = "rgba(90,95,120,0.5)"      # ink barely off the panel
        headline["mode"] = "standard"
        with tempfile.TemporaryDirectory() as folder:
            report = review.review_sheet(spec, folder)
        self.assertTrue(any("contrast" in f for f in report["faults"]), report["faults"])


if __name__ == "__main__":
    unittest.main()
