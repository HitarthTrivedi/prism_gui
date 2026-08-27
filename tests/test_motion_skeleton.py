"""
Tests for the "brand_launch" skeleton (core.motion.generate) — the fixed
HOOK/REVEAL/PROOF/SIGNOFF layer-doctrine pilot. Every check here also
proves the freeform path (skeleton=None, used by every other category) is
completely unaffected, since that's the whole point of making this opt-in.
"""
import os
import sys
import unittest

PRISM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "prism_terminal"))
if PRISM_DIR not in sys.path:
    sys.path.insert(0, PRISM_DIR)

from core.motion.schema import validate_motion_spec
from core.motion import generate as mgen
from core.motion.inspect import inspect, _layer_faults


class TestSchemaLayer(unittest.TestCase):
    def test_layer_sets_z_index_band(self):
        raw = {"scenes": [{"nodes": [
            {"type": "shape_rect", "layer": "midground"},
        ]}]}
        valid = validate_motion_spec(raw)
        node = valid["scenes"][0]["nodes"][0]
        self.assertEqual(node["layer"], "midground")
        self.assertEqual(node["z_index"], 10)

    def test_explicit_z_index_wins_over_layer_default(self):
        raw = {"scenes": [{"nodes": [
            {"type": "shape_rect", "layer": "background", "z_index": 99},
        ]}]}
        valid = validate_motion_spec(raw)
        self.assertEqual(valid["scenes"][0]["nodes"][0]["z_index"], 99)

    def test_unknown_layer_is_dropped_not_guessed(self):
        raw = {"scenes": [{"nodes": [
            {"type": "shape_rect", "layer": "sky"},
        ]}]}
        valid = validate_motion_spec(raw)
        node = valid["scenes"][0]["nodes"][0]
        self.assertNotIn("layer", node)
        self.assertEqual(node["z_index"], 0)

    def test_no_layer_behaves_exactly_as_before(self):
        raw = {"scenes": [{"nodes": [{"type": "text", "content": "hi"}]}]}
        valid = validate_motion_spec(raw)
        node = valid["scenes"][0]["nodes"][0]
        self.assertNotIn("layer", node)
        self.assertEqual(node["z_index"], 0)


class TestGeneratePrompts(unittest.TestCase):
    def test_freeform_storyboard_unchanged_without_skeleton(self):
        text = mgen.storyboard_instructions("a demo")
        self.assertIn("3-6 scenes", text)
        self.assertNotIn("HOOK", text)

    def test_brand_launch_storyboard_pins_four_roles(self):
        text = mgen.storyboard_instructions("a demo", skeleton="brand_launch")
        self.assertIn("EXACTLY 4 scenes", text)
        for role in ("HOOK", "REVEAL", "PROOF", "SIGNOFF"):
            self.assertIn(role, text)

    def test_freeform_scene_instructions_unchanged_without_skeleton(self):
        text = mgen.scene_instructions(0, 3, {"job": "open"})
        self.assertNotIn("LAYERS —", text)
        self.assertNotIn("ROLE:", text)

    def test_brand_launch_scene_instructions_carries_layer_doctrine(self):
        text = mgen.scene_instructions(0, 4, {"job": "open"}, skeleton="brand_launch")
        self.assertIn("LAYERS —", text)
        self.assertIn("ROLE: HOOK", text)
        self.assertIn('"layer"', text)

    def test_scene_role_order(self):
        self.assertEqual(mgen._scene_role(0), "HOOK")
        self.assertEqual(mgen._scene_role(1), "REVEAL")
        self.assertEqual(mgen._scene_role(2), "PROOF")
        self.assertEqual(mgen._scene_role(3), "SIGNOFF")

    def test_handoff_carried_into_next_scene_prompt(self):
        handoff = {"type": "slide_up", "fill": "#F5C453"}
        text = mgen.scene_instructions(1, 4, {"job": "reveal"},
                                       skeleton="brand_launch", handoff=handoff)
        self.assertIn("CONTINUING FROM THE LAST SCENE", text)
        self.assertIn("slide_up", text)
        self.assertIn("#F5C453", text)

    def test_no_handoff_on_first_scene(self):
        text = mgen.scene_instructions(0, 4, {"job": "hook"},
                                       skeleton="brand_launch", handoff=None)
        self.assertNotIn("CONTINUING FROM THE LAST SCENE", text)

    def test_scene_handoff_extracts_last_exiting_foreground(self):
        scene = {"nodes": [
            {"layer": "background", "animation": {"enter": {"type": "fade_in"}}},
            {"layer": "foreground", "fill": "#FFFFFF",
             "animation": {"enter": {"type": "pop_in"},
                           "exit": {"type": "slide_down", "time": 2.0}}},
        ]}
        handoff = mgen._scene_handoff(scene)
        self.assertEqual(handoff["type"], "slide_down")
        self.assertEqual(handoff["fill"], "#FFFFFF")

    def test_scene_handoff_none_when_foreground_never_exits(self):
        scene = {"nodes": [
            {"layer": "foreground", "animation": {"enter": {"type": "pop_in"}}},
        ]}
        self.assertIsNone(mgen._scene_handoff(scene))


class TestInspectLayerFaults(unittest.TestCase):
    def _scene(self, nodes, duration=3.0):
        return {"duration": duration, "nodes": nodes}

    def test_no_layers_at_all_is_unaffected(self):
        scene = self._scene([{"type": "text", "content": "hi",
                               "position": [540, 960]}])
        self.assertEqual(_layer_faults(scene), [])
        self.assertEqual(inspect({"project": {}, "scenes": [scene]}), [])

    def test_background_without_secondary_motion_faults(self):
        scene = self._scene([
            {"layer": "background", "type": "shape_rect",
             "animation": {"enter": {"type": "fade_in"}}},
        ])
        faults = _layer_faults(scene)
        self.assertTrue(any("secondary_motion" in f for f in faults))

    def test_background_with_secondary_motion_passes(self):
        scene = self._scene([
            {"layer": "background", "type": "shape_rect",
             "animation": {"enter": {"type": "fade_in"},
                           "secondary_motion": {"property": "opacity",
                                                 "freq": 0.2, "amount": 0.05}}},
        ])
        self.assertEqual(_layer_faults(scene), [])

    def test_foreground_without_exit_faults(self):
        scene = self._scene([
            {"layer": "foreground", "type": "text", "content": "hi",
             "position": [540, 960],
             "animation": {"enter": {"type": "pop_in"}}},
        ])
        faults = _layer_faults(scene)
        self.assertTrue(any("real \"exit\"" in f or 'real "enter"' in f for f in faults))

    def test_foreground_with_enter_and_exit_passes(self):
        scene = self._scene([
            {"layer": "foreground", "type": "text", "content": "hi",
             "position": [540, 960],
             "animation": {"enter": {"type": "pop_in"},
                           "exit": {"type": "fade_in", "time": 2.0}}},
        ])
        self.assertEqual(_layer_faults(scene), [])

    def test_foreground_holding_with_secondary_motion_also_passes(self):
        # A closing/signoff scene settling on the logo with no exit is
        # legitimate — as long as it isn't completely inert while it holds.
        scene = self._scene([
            {"layer": "foreground", "type": "text", "content": "hi",
             "position": [540, 960],
             "animation": {"enter": {"type": "pop_in"},
                           "secondary_motion": {"property": "scale",
                                                 "freq": 0.15, "amount": 0.02}}},
        ])
        self.assertEqual(_layer_faults(scene), [])


class TestBuildSpecBrandLaunch(unittest.TestCase):
    def test_end_to_end_four_scenes_with_handoff(self):
        storyboard_reply = """```json
{
  "project": {"width": 1080, "height": 1920, "fps": 30, "duration": 10.0,
              "background": "#07091A"},
  "storyboard": [
    {"scene": 1, "seconds": 2.5, "job": "hook"},
    {"scene": 2, "seconds": 3.0, "job": "reveal"},
    {"scene": 3, "seconds": 2.5, "job": "proof"},
    {"scene": 4, "seconds": 2.5, "job": "signoff"}
  ]
}
```"""
        prompts_seen = []

        def fake_ask(prompt, expect):
            prompts_seen.append(prompt)
            idx = len(prompts_seen) - 1
            fill = "#F5C453" if idx % 2 == 0 else "#38E1C6"
            return ('```json\n{"nodes": ['
                    '{"id": "bg_%d", "type": "shape_rect", "layer": "background", '
                    ' "width": 1080, "height": 1920, "fill": "%s",'
                    ' "animation": {"enter": {"type": "fade_in", "duration": 0.3},'
                    '  "secondary_motion": {"property": "opacity", "freq": 0.2, "amount": 0.05}}},'
                    '{"id": "fg_%d", "type": "text", "content": "Scene", "layer": "foreground",'
                    ' "position": [540, 960],'
                    ' "animation": {"enter": {"type": "pop_in", "duration": 0.4},'
                    '  "exit": {"type": "slide_up", "time": 1.8, "duration": 0.4}}}'
                    ']}\n```') % (idx, fill, idx)

        spec = mgen.build_spec(storyboard_reply, fake_ask, check=inspect,
                               skeleton="brand_launch")
        self.assertEqual(len(spec["scenes"]), 4)
        # Scene 2's prompt (index 1) should reference scene 1's handoff.
        self.assertIn("CONTINUING FROM THE LAST SCENE", prompts_seen[1])
        # Scene 1's prompt (index 0) should not.
        self.assertNotIn("CONTINUING FROM THE LAST SCENE", prompts_seen[0])
        # Every scene checked clean against the layer doctrine.
        for scene in spec["scenes"]:
            self.assertEqual(inspect({"project": spec["project"],
                                      "scenes": [scene]}), [])


if __name__ == "__main__":
    unittest.main()
