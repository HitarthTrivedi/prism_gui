"""Contract tests for Prism Motion's cinematic continuity profile."""
from __future__ import annotations

import os
import sys
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import continuity
import importlib
motion_render_mod = importlib.import_module("core.motion.render")
from core.motion.generate import (build_spec, scene_instructions,
                                  storyboard_instructions)
from core.motion.resolver import resolve_motion_spec
from core.motion.schema import MotionValidationError, validate_motion_spec


class MotionContinuityTests(unittest.TestCase):
    def test_cinematic_prompts_name_visual_spine_and_key(self):
        storyboard = storyboard_instructions("An editorial product reveal",
                                             skeleton="cinematic_glass")
        scene = scene_instructions(
            1, 2, {"job": "transform the signal", "seconds": 3},
            skeleton="cinematic_glass",
            handoff={"type": "blur_swoosh", "fill": "#FF5C7A",
                     "continuity_key": "signal"})
        self.assertIn("continuous visual transformation", storyboard)
        self.assertIn('continuity_key', scene)
        self.assertIn('continuity_key "signal"', scene)
        self.assertIn("CINEMATIC GLASS", scene)

    def test_schema_normalizes_continuity_keys(self):
        spec = {"project": {"duration": 2, "fps": 30}, "scenes": [{
            "id": "one", "duration": 2, "nodes": [
                {"id": "hero", "type": "shape_rect", "position": [0, 0],
                 "continuity_key": "  signal  "},
                {"id": "bad", "type": "shape_rect", "position": [0, 0],
                 "continuity_key": "   "},
            ]}]} 
        validated = validate_motion_spec(spec)
        nodes = validated["scenes"][0]["nodes"]
        self.assertEqual(nodes[0]["continuity_key"], "signal")
        self.assertNotIn("continuity_key", nodes[1])

    def test_resolver_exposes_cross_scene_manifest(self):
        spec = {"project": {"duration": 4, "fps": 30}, "scenes": [
            {"id": "one", "duration": 2, "nodes": [{
                "id": "signal_a", "type": "shape_rect", "position": [10, 20],
                "continuity_key": "signal"}]},
            {"id": "two", "duration": 2, "nodes": [{
                "id": "signal_b", "type": "shape_rect", "position": [30, 40],
                "continuity_key": "signal"}]},
        ]}
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        thread = resolved["_continuity"]["signal"]
        self.assertEqual([item["node"] for item in thread],
                         ["signal_a", "signal_b"])
        self.assertEqual(thread[1]["scene"], "two")

    def test_build_spec_threads_profile_and_handoff(self):
        first = ('{"project":{"duration":4,"fps":30},'
                 '"storyboard":[{"seconds":2,"job":"begin"},'
                 '{"seconds":2,"job":"resolve"}]}')
        prompts = []

        def ask(prompt, expect):
            prompts.append(prompt)
            return ('{"nodes":[{"id":"signal", "type":"shape_rect",'
                    '"position":[200,300], "continuity_key":"signal",'
                    '"layer":"foreground", "animation":{"exit":'
                    '{"type":"blur_swoosh", "duration":0.4}}}]}')

        spec = build_spec(first, ask, skeleton="cinematic_glass")
        self.assertEqual(spec["_motion_profile"], "cinematic_glass")
        self.assertEqual(len(spec["scenes"]), 2)
        self.assertIn('continuity_key "signal"', prompts[1])


def _two_scene(pose_a, pose_b, *, dur=(2, 2), profile="cinematic_glass",
               extra_a=None, extra_b=None):
    """Two scenes sharing continuity_key "signal" at two poses."""
    a = {"id": "signal_a", "type": "shape_rect", "continuity_key": "signal",
         "layer": "foreground", **pose_a}
    b = {"id": "signal_b", "type": "shape_rect", "continuity_key": "signal",
         "layer": "foreground", **pose_b}
    spec = {"project": {"duration": sum(dur), "fps": 30},
            "scenes": [
                {"id": "one", "duration": dur[0], "nodes": [a] + (extra_a or [])},
                {"id": "two", "duration": dur[1], "nodes": [b] + (extra_b or [])},
            ]}
    if profile:
        spec["_motion_profile"] = profile
    return spec


class ContinuityCompilerTests(unittest.TestCase):
    def test_overlap_matches_resolver_window(self):
        self.assertEqual(continuity.handoff_overlap(2, 2), 0.5)
        self.assertAlmostEqual(continuity.handoff_overlap(0.9, 3), 0.3)
        self.assertEqual(continuity.bridge_window(2.0, 0.5), (1.5, 2.2))

    def test_bridge_is_pose_matched_and_cut_becomes_morph(self):
        spec = _two_scene({"position": [200, 300], "scale": [1, 1]},
                          {"position": [500, 700], "scale": [1.5, 1.5],
                           "rotation": 20})
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        one, two = resolved["scenes"]
        self.assertEqual(two["transition_in"], "morph")
        out_exit = one["nodes"][0]["animation"]["exit"]
        in_enter = two["nodes"][0]["animation"]["enter"]
        # same window as the scene visibility overlap, both sides
        self.assertEqual(out_exit["time"], two["transitionInStart"])
        self.assertEqual(in_enter["time"], two["transitionInStart"])
        self.assertAlmostEqual(out_exit["time"] + out_exit["duration"],
                               one["transitionOutEnd"], places=3)
        self.assertEqual(out_exit["duration"], in_enter["duration"])
        out_t = {t["channel"]: (t["from"], t["to"]) for t in out_exit["tweens"]}
        in_t = {t["channel"]: (t["from"], t["to"]) for t in in_enter["tweens"]}
        self.assertEqual(out_t["x"], (0.0, 300.0))
        self.assertEqual(in_t["x"], (-300.0, 0.0))
        self.assertEqual(out_t["y"], (0.0, 400.0))
        self.assertEqual(in_t["y"], (-400.0, 0.0))
        self.assertEqual(out_t["scaleX"], (0.0, 0.5))
        self.assertEqual(in_t["scaleX"], (-0.5, 0.0))
        self.assertEqual(out_t["rotation"], (0.0, 20.0))
        self.assertEqual(in_t["rotation"], (-20.0, 0.0))
        # the same easing on both sides is what keeps the two paths equal
        self.assertEqual({t["easing"] for t in out_exit["tweens"]
                          + in_enter["tweens"]}, {continuity.BRIDGE_EASING})
        # opacity is never bridged on the node — the morph crossfade owns it
        self.assertNotIn("opacity", out_t)
        self.assertNotIn("opacity", in_t)
        compiled = resolved["_continuity_compiled"]
        self.assertEqual(compiled["errors"], [])
        self.assertEqual(len(compiled["bridges"]), 1)
        self.assertEqual(compiled["bridges"][0]["out_node"], "signal_a")
        self.assertEqual(compiled["bridges"][0]["in_node"], "signal_b")

    def test_bridge_replaces_cold_authored_enter_and_exit(self):
        spec = _two_scene(
            {"position": [200, 300], "animation": {"exit": {
                "time": 0.2, "duration": 0.3,
                "tweens": [{"channel": "opacity", "from": 1, "to": 0}]}}},
            {"position": [260, 300], "animation": {"enter": {
                "time": 0, "duration": 0.6,
                "tweens": [{"channel": "opacity", "from": 0, "to": 1}]}}})
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        one, two = resolved["scenes"]
        self.assertTrue(one["nodes"][0]["animation"]["exit"].get("_bridge"))
        self.assertTrue(two["nodes"][0]["animation"]["enter"].get("_bridge"))
        self.assertNotIn("opacity", {t["channel"] for t in
                                     two["nodes"][0]["animation"]["enter"]["tweens"]})

    def test_resolver_is_idempotent_on_a_saved_spec(self):
        spec = _two_scene({"position": [200, 300]}, {"position": [500, 700]})
        once = resolve_motion_spec(validate_motion_spec(spec))
        import copy, json
        again = resolve_motion_spec(json.loads(json.dumps(copy.deepcopy(once))))
        self.assertEqual(json.dumps(once["scenes"], sort_keys=True),
                         json.dumps(again["scenes"], sort_keys=True))

    def test_same_pose_still_pins_both_instances(self):
        spec = _two_scene({"position": [200, 300]}, {"position": [200, 300]})
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        self.assertEqual(resolved["scenes"][1]["transition_in"], "morph")
        self.assertTrue(resolved["scenes"][1]["nodes"][0]["animation"]["enter"]["_bridge"])

    def test_nested_subject_uses_world_pose(self):
        spec = {"project": {"duration": 4, "fps": 30},
                "scenes": [
                    {"id": "one", "duration": 2, "nodes": [{
                        "id": "card", "type": "group", "position": [100, 100],
                        "children": [{"id": "s_a", "type": "shape_rect",
                                      "position": [50, 50],
                                      "continuity_key": "signal"}]}]},
                    {"id": "two", "duration": 2, "nodes": [{
                        "id": "s_b", "type": "shape_rect", "position": [250, 250],
                        "continuity_key": "signal"}]}]}
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        bridge = resolved["_continuity_compiled"]["bridges"][0]
        self.assertEqual((bridge["dx"], bridge["dy"]), (100.0, 100.0))
        inner = resolved["scenes"][0]["nodes"][0]["children"][0]
        self.assertTrue(inner["animation"]["exit"]["_bridge"])

    def test_hard_cut_between_keyed_scenes_is_a_cold_reset_error(self):
        spec = _two_scene({"position": [200, 300]}, {"position": [220, 300]},
                          dur=(2, 0.05))
        rep = continuity.report(validate_motion_spec(spec))
        self.assertEqual(len(rep["errors"]), 1)
        self.assertIn("hard cut", rep["errors"][0]["message"])
        self.assertEqual(rep["bridges"], [])

    def test_jump_and_scale_blowup_are_impossible_handoffs(self):
        jump = _two_scene({"position": [0, 0]}, {"position": [1080, 1900]},
                          dur=(0.6, 0.6))
        msgs = continuity.faults(validate_motion_spec(jump))
        self.assertEqual(len(msgs), 1)
        self.assertIn("reads as a jump", msgs[0])
        blow = _two_scene({"position": [200, 300], "scale": [1, 1]},
                          {"position": [200, 300], "scale": [12, 12]})
        msgs = continuity.faults(validate_motion_spec(blow))
        self.assertIn("scale changes", msgs[0])
        gone = _two_scene({"position": [200, 300], "opacity": 0},
                          {"position": [200, 300]})
        msgs = continuity.faults(validate_motion_spec(gone))
        self.assertIn("nothing visible", msgs[0])

    def test_duplicate_key_in_one_scene_is_ambiguous(self):
        spec = _two_scene({"position": [200, 300]}, {"position": [220, 300]},
                          extra_b=[{"id": "twin", "type": "shape_rect",
                                    "position": [900, 300],
                                    "continuity_key": "signal"}])
        msgs = continuity.faults(validate_motion_spec(spec))
        self.assertTrue(any("2 nodes" in m and '"twin"' in m for m in msgs), msgs)

    def test_thread_gap_is_a_missing_subject_warning(self):
        spec = {"project": {"duration": 6, "fps": 30},
                "_motion_profile": "cinematic_glass",
                "scenes": [
                    {"id": "one", "duration": 2, "nodes": [{
                        "id": "a", "type": "shape_rect", "position": [200, 300],
                        "continuity_key": "signal"}]},
                    {"id": "two", "duration": 2, "nodes": [{
                        "id": "filler", "type": "text", "content": "x",
                        "position": [540, 960]}]},
                    {"id": "three", "duration": 2, "nodes": [{
                        "id": "c", "type": "shape_rect", "position": [200, 300],
                        "continuity_key": "signal"}]}]}
        rep = continuity.report(validate_motion_spec(spec))
        self.assertEqual(rep["errors"], [])
        gap = [w for w in rep["warnings"] if "cold reset" in w["message"]]
        self.assertEqual(gap[0]["scene_index"], 1)
        # the cinematic profile also warns the spine is dropped in scene 2
        self.assertTrue(any("no node with a continuity_key" in w["message"]
                            for w in rep["warnings"]))

    def test_unresolved_opening_subject_is_a_warning_not_an_error(self):
        spec = {"project": {"duration": 4, "fps": 30},
                "_motion_profile": "cinematic_glass",
                "scenes": [
                    {"id": "one", "duration": 2, "nodes": [{
                        "id": "a", "type": "shape_rect", "position": [200, 300],
                        "continuity_key": "signal"}]},
                    {"id": "two", "duration": 2, "nodes": [{
                        "id": "b", "type": "shape_rect", "position": [200, 300],
                        "continuity_key": "logo"}]}]}
        rep = continuity.report(validate_motion_spec(spec))
        self.assertEqual(rep["errors"], [])
        self.assertTrue(any("does not resolve it" in w["message"]
                            for w in rep["warnings"]))
        # and without the cinematic profile nothing is said at all
        spec.pop("_motion_profile")
        self.assertEqual(continuity.report(validate_motion_spec(spec))["warnings"], [])

    def test_unkeyed_specs_are_untouched(self):
        spec = {"project": {"duration": 4, "fps": 30}, "scenes": [
            {"id": "one", "duration": 2, "nodes": [{"id": "a", "type": "text",
                                                    "content": "hi",
                                                    "position": [540, 900]}]},
            {"id": "two", "duration": 2, "nodes": [{"id": "b", "type": "text",
                                                    "content": "yo",
                                                    "position": [540, 900]}]}]}
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        self.assertNotEqual(resolved["scenes"][1]["transition_in"], "morph")
        self.assertEqual(resolved["_continuity_compiled"]["bridges"], [])
        self.assertNotIn("animation", resolved["scenes"][0]["nodes"][0])

    def test_schema_accepts_morph_transition(self):
        spec = {"project": {"duration": 4, "fps": 30}, "scenes": [
            {"id": "one", "duration": 2, "nodes": []},
            {"id": "two", "duration": 2, "transition_in": "morph", "nodes": []}]}
        self.assertEqual(validate_motion_spec(spec)["scenes"][1]["transition_in"],
                         "morph")

    def test_render_refuses_a_broken_handoff_only_when_strict(self):
        spec = _two_scene({"position": [200, 300]}, {"position": [220, 300]},
                          dur=(2, 0.05))
        spec["_strict_continuity"] = True
        with self.assertRaises(MotionValidationError) as ctx:
            motion_render_mod.render(spec, "/nonexistent/out.mp4")
        self.assertIn("continuity broken", str(ctx.exception))
        self.assertIn("hard cut", str(ctx.exception))
        # without strictness the same spec reaches the renderer (it fails
        # later only because the output folder does not exist)
        spec.pop("_strict_continuity")
        with self.assertRaises(Exception) as ctx2:
            motion_render_mod.render(spec, "/nonexistent/out.mp4")
        self.assertNotIn("continuity broken", str(ctx2.exception))


class ContinuityRepairTests(unittest.TestCase):
    FIRST = ('{"project":{"duration":4,"fps":30},'
             '"storyboard":[{"seconds":2,"job":"begin"},'
             '{"seconds":2,"job":"resolve"}]}')

    @staticmethod
    def _node(nid, pos, key="signal", extra=""):
        return (f'{{"id":"{nid}","type":"shape_rect","position":{pos},'
                f'"continuity_key":"{key}","layer":"foreground"{extra}}}')

    def test_handoff_prompt_names_the_pose_to_pick_up(self):
        prompts = []

        def ask(prompt, expect):
            prompts.append(prompt)
            return '{"nodes":[' + self._node("s", "[200,300]") + ']}'

        build_spec(self.FIRST, ask, skeleton="cinematic_glass")
        self.assertIn("settled at position [200, 300]", prompts[1])
        self.assertIn("morph between the two poses", prompts[1])

    def test_broken_scene_is_sent_back_with_neighbour_poses(self):
        prompts = []
        replies = iter([
            '{"nodes":[' + self._node("s1", "[200,300]") + ']}',
            # scene 2: the key on two nodes — ambiguous
            '{"nodes":[' + self._node("s2", "[240,300]") + ','
            + self._node("twin", "[900,300]") + ']}',
            # the repair: one keyed node
            '{"nodes":[' + self._node("s2", "[240,300]") + ']}',
        ])

        def ask(prompt, expect):
            prompts.append(prompt)
            return next(replies, "")

        spec = build_spec(self.FIRST, ask, skeleton="cinematic_glass")
        repair = prompts[2]
        self.assertIn("breaks the continuity contract", repair)
        self.assertIn('"twin"', repair)
        self.assertIn('The scene before (scene 1) carries continuity_key "signal"', repair)
        nodes = spec["scenes"][1]["nodes"]
        self.assertEqual([n["id"] for n in nodes], ["s2"])
        self.assertEqual(continuity.faults(validate_motion_spec(spec)), [])

    def test_a_worse_repair_is_not_kept(self):
        replies = iter([
            '{"nodes":[' + self._node("s1", "[200,300]") + ']}',
            '{"nodes":[' + self._node("s2", "[240,300]") + ','
            + self._node("twin", "[900,300]") + ']}',
            # "repair" that adds a third keyed node
            '{"nodes":[' + self._node("s2", "[240,300]") + ','
            + self._node("twin", "[900,300]") + ','
            + self._node("third", "[500,300]") + ']}',
        ])
        spec = build_spec(self.FIRST, lambda p, e: next(replies, ""),
                          skeleton="cinematic_glass")
        self.assertEqual(len(spec["scenes"][1]["nodes"]), 2)

    def test_non_cinematic_profiles_skip_the_repair_pass(self):
        prompts = []
        replies = iter([
            '{"nodes":[' + self._node("s1", "[200,300]") + ']}',
            '{"nodes":[' + self._node("s2", "[240,300]") + ','
            + self._node("twin", "[900,300]") + ']}',
        ])

        def ask(prompt, expect):
            prompts.append(prompt)
            return next(replies, "")

        build_spec(self.FIRST, ask, skeleton="brand_launch")
        self.assertEqual(len(prompts), 2)


if __name__ == "__main__":
    unittest.main()
