"""The authored spine: structure given, content written. The recreation
(core.motion.fixtures.inspo_fixture, benchmark 84) is the proof that every
recipe is satisfiable — its scenes pass their own beats."""
from __future__ import annotations

import json
import os
import sys
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import spine  # noqa: E402
from core.motion.fixtures import inspo_fixture  # noqa: E402
from core.motion.generate import build_spec, scene_instructions, storyboard_instructions  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402


class TheBeats(unittest.TestCase):
    def test_ten_scenes_get_the_whole_reference_and_fewer_drop_from_the_end(self):
        self.assertEqual(spine.beats_for(10), [b["name"] for b in spine.BEATS])
        seven = spine.beats_for(7)
        self.assertEqual((seven[0], seven[-1]), ("gather", "resolve"))
        self.assertEqual(len(seven), 7)
        self.assertNotIn("arc", seven)
        self.assertNotIn("orb", seven)
        self.assertEqual(len(spine.beats_for(4)), 4)
        self.assertEqual(len(spine.beats_for(12)), 12)
        self.assertEqual(spine.beats_for(12)[-1], "resolve")

    def test_the_recreation_passes_its_own_beats(self):
        spec = validate_motion_spec(json.loads(json.dumps(inspo_fixture())))
        for scene, name in zip(spec["scenes"], spine.beats_for(10)):
            self.assertEqual(spine.beat_faults(scene, name), [], (scene["id"], name))

    def test_a_scene_missing_its_transformation_is_named(self):
        held = {"nodes": [{"id": "f", "type": "particle_field", "count": 40, "size": 2,
                           "phases": [{"at": 0, "layout": {"kind": "scatter"}}]}]}
        faults = spine.beat_faults(held, "gather")
        self.assertTrue(any("count 40" in f for f in faults), faults)
        self.assertTrue(any("size 2" in f for f in faults), faults)
        self.assertTrue(any('no "band" phase' in f for f in faults), faults)
        self.assertTrue(any("light_field" in f for f in faults), faults)
        dark = {"nodes": [{"id": "t", "type": "text", "content": "x"}]}
        self.assertTrue(any("bright backdrop" in f for f in spine.beat_faults(dark, "sweep")))
        self.assertTrue(any("chat bubbles" in f for f in spine.beat_faults(dark, "sweep")))
        self.assertEqual(spine.beat_faults(dark, "not-a-beat"), [])


class TheSpineReachesThePrompts(unittest.TestCase):
    def test_the_storyboard_turn_lists_the_beats_for_the_scripts_scenes(self):
        script = "\n".join(f"SCENE 0{i}\nLine {i}" for i in range(1, 6))
        prompt = storyboard_instructions("a reel", skeleton="cinematic_glass", script=script)
        self.assertIn("THE SPINE", prompt)
        self.assertIn('1. "gather"', prompt)
        self.assertIn('5. "resolve"', prompt)
        self.assertNotIn('6. "', prompt)
        self.assertIn('"beat": "gather"', prompt)
        self.assertNotIn("THE SPINE", storyboard_instructions("a reel", skeleton="brand_launch"))

    def test_a_scene_prompt_carries_its_beats_recipe(self):
        prompt = scene_instructions(0, 7, {"job": "open", "seconds": 2.6, "beat": "gather"},
                                    skeleton="cinematic_glass")
        self.assertIn('THIS SCENE\'S BEAT: "gather"', prompt)
        self.assertIn("MUST travel from the scatter to the band", prompt)

    def test_build_spec_assigns_beats_and_sends_a_beatless_scene_back(self):
        prompts = []
        flat = '{"nodes":[{"id":"h","type":"text","content":"BUILT FOR AI","position":[540,900],"layer":"foreground"}]}'
        good = ('{"nodes":[{"id":"h","type":"text","content":"BUILT FOR AI","position":[540,900],"layer":"foreground"},'
                '{"id":"f","type":"particle_field","count":120,"size":30,"continuity_key":"signal",'
                '"phases":[{"at":0,"layout":{"kind":"scatter"}},{"at":0.3,"layout":{"kind":"band","y":855}}]},'
                '{"id":"l","type":"light_field","position":[540,700],"intensity":0.1}]}')
        replies = iter([flat, good, flat, flat, flat])

        def ask(prompt, expect):
            prompts.append(prompt)
            return next(replies, "")

        first = ('{"project":{"duration":4,"fps":30},"storyboard":[{"seconds":2,"job":"open","caption":"BUILT FOR AI"},'
                 '{"seconds":2,"job":"close","caption":"BUILT FOR AI"}]}')
        spec = build_spec(first, ask, skeleton="cinematic_glass", check=lambda s: [])
        self.assertIn('BEAT: "gather"', prompts[0])
        self.assertTrue(any('beat "gather"' in p and "particle_field" in p for p in prompts[1:2]), prompts[1])
        self.assertEqual(spec["scenes"][0]["nodes"][1]["type"], "particle_field")
        self.assertIn('BEAT: "resolve"', [p for p in prompts if "SCENE 2 of 2" in p][0])


if __name__ == "__main__":
    unittest.main()
