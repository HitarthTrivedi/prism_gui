"""
Automated unit tests for Prism Motion Graphics Engine (`core.motion`).
"""
import os
import sys
import unittest

PRISM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "prism_terminal"))
if PRISM_DIR not in sys.path:
    sys.path.insert(0, PRISM_DIR)

from core.motion.schema import validate_motion_spec, MotionValidationError, MotionProject
from core.motion.resolver import resolve_motion_spec
from core.motion.prompts import parse_motion_reply


class TestMotionEngine(unittest.TestCase):
    def test_schema_valid_defaults(self):
        raw = {
            "scenes": [
                {
                    "nodes": [
                        {"type": "text", "content": "Live Demo", "position": [540, 960]}
                    ]
                }
            ]
        }
        validated = validate_motion_spec(raw)
        self.assertEqual(validated["project"]["width"], 1080)
        self.assertEqual(validated["project"]["height"], 1920)
        self.assertEqual(validated["project"]["fps"], 30)
        self.assertEqual(validated["project"]["duration"], 10.0)
        self.assertEqual(len(validated["scenes"][0]["nodes"]), 1)

    def test_schema_rejects_invalid_dimension(self):
        raw = {
            "project": {"width": 100},
            "scenes": [{"nodes": []}]
        }
        with self.assertRaises(MotionValidationError):
            validate_motion_spec(raw)

    def test_semantic_resolver_indexes_nodes(self):
        raw = {
            "scenes": [
                {
                    "nodes": [
                        {"id": "card_1", "type": "shape_rect", "position": [200, 300]},
                        {"id": "card_2", "type": "shape_rect", "position": [500, 700]}
                    ]
                }
            ]
        }
        valid = validate_motion_spec(raw)
        resolved = resolve_motion_spec(valid)
        self.assertEqual(len(resolved["scenes"][0]["nodes"]), 2)

    def test_camera_focus_target_resolution(self):
        raw = {
            "camera": {
                "tracks": [
                    {"time": 0.0, "zoom": 1.0, "position": [540, 960]},
                    {"time": 2.0, "focus_target": "target_box", "zoom": 1.5}
                ]
            },
            "scenes": [
                {
                    "nodes": [
                        {"id": "target_box", "type": "shape_rect", "position": [400, 800]}
                    ]
                }
            ]
        }
        valid = validate_motion_spec(raw)
        resolved = resolve_motion_spec(valid)
        cam_track = resolved["camera"]["tracks"][1]
        self.assertIn("position", cam_track)
        self.assertEqual(cam_track["position"], [400.0, 800.0])

    def test_parse_motion_reply_from_llm(self):
        llm_output = """Here is the motion design you requested:
```json
{
  "project": { "duration": 8.0 },
  "scenes": [
    {
      "nodes": [
        { "type": "shape_rect", "width": 400, "height": 200 }
      ]
    }
  ]
}
```
Hope this helps!"""
        parsed = parse_motion_reply(llm_output)
        self.assertEqual(parsed["project"]["duration"], 8.0)
        self.assertEqual(parsed["scenes"][0]["nodes"][0]["type"], "shape_rect")

    def test_audio_muxing_noop_when_no_audio(self):
        from core.motion.audio import mux_audio_and_video
        res = mux_audio_and_video("dummy_video.mp4", None, "out.mp4", bgm_path=None)
        self.assertEqual(res, "dummy_video.mp4")


if __name__ == "__main__":
    unittest.main()
