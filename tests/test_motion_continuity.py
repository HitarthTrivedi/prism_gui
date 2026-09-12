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


class AFieldIsBridgedToWhereItStarts(unittest.TestCase):
    def test_a_field_that_streams_away_is_bridged_to_its_first_layout(self):
        """The composed reel's second scene keeps the band and then
        streams it into a column; the bridge from the first scene's band
        must land on the band, not slide the whole field in from the
        column's centre."""
        band = {"kind": "band", "y": 800, "rows": 6, "cell": 30, "x0": 10, "x1": 1070}
        column = {"kind": "column", "x": 800, "spread": 200, "y0": 950, "y1": 1700}
        from core.motion.schema import validate_motion_spec
        spec = validate_motion_spec({
            "project": {"width": 1080, "height": 1920, "fps": 30, "duration": 4.0},
            "scenes": [
                {"id": "a", "duration": 2.0, "nodes": [
                    {"id": "f0", "type": "particle_field", "position": [0, 0], "count": 60,
                     "continuity_key": "signal", "phases": [{"at": 0.0, "layout": band}]}]},
                {"id": "b", "duration": 2.0, "nodes": [
                    {"id": "f1", "type": "particle_field", "position": [0, 0], "count": 60,
                     "continuity_key": "signal",
                     "phases": [{"at": 0.0, "layout": band},
                                {"at": 1.2, "layout": column, "duration": 0.5}]}]},
            ]})
        rep = continuity.report(spec)
        self.assertEqual(rep["errors"], [])
        bridge = [b for b in rep["bridges"] if b["in_node"] == "f1"][0]
        self.assertAlmostEqual(bridge["dx"], 0.0, places=3)
        self.assertAlmostEqual(bridge["dy"], 0.0, places=3)


class TextThatHasLeftIsNotClipped(unittest.TestCase):
    """The settled camera cannot clip text whose node has already exited:
    the composed reel's bubbles finish leaving across a cut, off the frame."""
    def _spec(self, exit_block):
        from core.motion.schema import validate_motion_spec
        node = {"id": "leaving", "type": "shape_rect", "position": [-300, 900], "width": 700, "height": 200,
                "fill": "#FFFFFF", "children": [{"id": "leaving_t", "type": "text", "position": [0, 0],
                                                 "content": "still leaving the frame", "font_size": 52}]}
        if exit_block:
            node["animation"] = {"exit": exit_block}
        return validate_motion_spec({"project": {"width": 1080, "height": 1920, "fps": 30, "duration": 3.0},
                                     "scenes": [{"id": "a", "duration": 3.0, "shot": {"intent": "hold"},
                                                 "nodes": [node]}]})

    def test_text_off_frame_is_an_error_unless_it_has_left(self):
        kept = continuity.report(self._spec(None))["errors"]
        self.assertTrue(any("leaving_t" in e["message"] for e in kept), kept)
        gone = continuity.report(self._spec({"time": 0.0, "duration": 0.5, "tweens": [
            {"channel": "x", "from": 0, "to": -900}]}))["errors"]
        self.assertFalse(any("leaving_t" in e["message"] for e in gone), gone)
        late = continuity.report(self._spec({"time": 2.6, "duration": 0.4, "tweens": [
            {"channel": "opacity", "from": 1, "to": 0}]}))["errors"]
        self.assertTrue(any("leaving_t" in e["message"] for e in late), late)


if __name__ == "__main__":
    unittest.main()


class TheStoryContract(unittest.TestCase):
    """The Alphakore run (10 Sep 2026) had seven scenes and no story: the
    copy stage's script never reached the motion writer, turn one answered
    whole scenes instead of a storyboard, and every scene prompt said
    'carry the argument forward' with no argument. The contract: the
    script is the story, each row carries its caption, a scene must carry
    its caption, and a scenes-instead-of-storyboard reply is asked again."""

    SCRIPT = "SCENE 01\nBUILT FOR THE NEXT\nGENERATION OF AI\nSCENE 02\nMORE COMPUTE. LESS FRICTION."

    def test_the_storyboard_turn_carries_the_script_and_asks_for_captions(self):
        from core.motion.generate import storyboard_instructions
        prompt = storyboard_instructions("a reel for Alphakore", skeleton="cinematic_glass",
                                         script=self.SCRIPT)
        self.assertIn("THE SCRIPT", prompt)
        self.assertIn("MORE COMPUTE. LESS FRICTION.", prompt)
        self.assertIn('"caption"', prompt)
        self.assertIn('"subject"', prompt)
        self.assertNotIn("THE SCRIPT", storyboard_instructions("x", skeleton="cinematic_glass"))

    def test_a_scene_prompt_states_its_caption_and_subject(self):
        prompt = scene_instructions(1, 3, {"job": "prove it", "seconds": 3,
                                           "caption": "MORE COMPUTE. LESS FRICTION.",
                                           "subject": "the band, now a column"},
                                    skeleton="cinematic_glass")
        self.assertIn('ITS CAPTION: "MORE COMPUTE. LESS FRICTION."', prompt)
        self.assertIn("ITS SUBJECT: the band, now a column", prompt)

    def test_caption_faults_compare_words_not_punctuation(self):
        from core.motion.generate import caption_faults
        row = {"caption": "MORE COMPUTE.\nLESS FRICTION."}
        ok = {"nodes": [{"type": "glass_panel", "children": [
            {"type": "text", "content": "More compute,\nless friction"}]}]}
        self.assertEqual(caption_faults(ok, row), [])
        wrong = {"nodes": [{"type": "text", "content": "SYSTEM / SIGNAL / SCALE"}]}
        self.assertIn("no text node carries it", caption_faults(wrong, row)[0])
        partial = {"nodes": [{"type": "text", "content": "More compute"}]}
        self.assertIn("only partly matches", caption_faults(partial, row)[0])
        self.assertEqual(caption_faults(wrong, {"job": "x"}), [])

    def test_scenes_instead_of_a_storyboard_are_asked_again(self):
        prompts = []
        replies = iter([
            # the real storyboard, on the re-ask
            '{"project":{"duration":4,"fps":30},"storyboard":[{"seconds":2,"job":"open",'
            '"caption":"BUILT FOR AI"},{"seconds":2,"job":"close","caption":"MOVE FAST"}]}',
            '{"nodes":[{"id":"h1","type":"text","content":"BUILT FOR AI","position":[540,900],'
            '"continuity_key":"k","layer":"foreground"}]}',
            '{"nodes":[{"id":"h2","type":"text","content":"MOVE FAST","position":[540,900],'
            '"continuity_key":"k","layer":"foreground"}]}',
        ])

        def ask(prompt, expect):
            prompts.append(prompt)
            return next(replies, "")

        whole = ('{"project":{"duration":4,"fps":30},"scenes":[{"duration":2,"nodes":[]},'
                 '{"duration":2,"nodes":[]}]}')
        spec = build_spec(whole, ask, skeleton="cinematic_glass")
        self.assertIn("send the STORYBOARD only", prompts[0])
        self.assertIn('ITS CAPTION: "BUILT FOR AI"', prompts[1])
        self.assertEqual(spec["scenes"][1]["nodes"][0]["content"], "MOVE FAST")

    def test_a_scene_that_drops_its_caption_is_sent_back(self):
        prompts = []
        replies = iter([
            '{"nodes":[{"id":"h1","type":"text","content":"SOMETHING ELSE","position":[540,900],'
            '"continuity_key":"k","layer":"foreground"}]}',
            # the correction carries the caption
            '{"nodes":[{"id":"h1","type":"text","content":"BUILT FOR AI","position":[540,900],'
            '"continuity_key":"k","layer":"foreground"}]}',
        ])

        def ask(prompt, expect):
            prompts.append(prompt)
            return next(replies, "")

        first = ('{"project":{"duration":2,"fps":30},"storyboard":[{"seconds":2,"job":"open",'
                 '"caption":"BUILT FOR AI"}]}')
        spec = build_spec(first, ask, skeleton="cinematic_glass", check=lambda s: [])
        self.assertTrue(any("caption is" in p for p in prompts), prompts)
        self.assertEqual(spec["scenes"][0]["nodes"][0]["content"], "BUILT FOR AI")


class TheScriptReachesTheMotionWriter(unittest.TestCase):
    def test_the_first_turn_is_rebuilt_with_the_copy_stages_script(self):
        from core import automation
        responses = {"brains": ["a plan"], "content": ["SCENE 01\nBUILT FOR THE NEXT\nGENERATION OF AI"]}
        prompt = automation.motion_turn_one("make a reel for Alphakore", "cinematic_glass", responses)
        self.assertIn("THE SCRIPT", prompt)
        self.assertIn("GENERATION OF AI", prompt)
        self.assertIn("make a reel for Alphakore", prompt)
        self.assertEqual(automation.motion_turn_one("x", "cinematic_glass", {"brains": ["plan"]}), "")
        self.assertEqual(automation.motion_script({"content": ["  "]}), "")


class TheSubjectMustChangeState(unittest.TestCase):
    def _spec(self, poses):
        return validate_motion_spec({
            "project": {"duration": 2 * len(poses), "fps": 30},
            "_motion_profile": "cinematic_glass",
            "scenes": [{"id": f"s{i}", "duration": 2, "nodes": [
                {"id": f"logo_{i}", "type": "image", "src": "asset:logo", "position": list(p),
                 "width": 300, "height": 200, "continuity_key": "mark"}]}
                for i, p in enumerate(poses)]})

    def test_the_same_pose_for_three_scenes_is_a_warning(self):
        rep = continuity.report(self._spec([(540, 900), (540, 900), (540, 900), (540, 900)]))
        sat = [w for w in rep["warnings"] if "never changes state" in w["message"]]
        self.assertEqual(len(sat), 1, rep["warnings"])
        self.assertEqual(sat[0]["scene_index"], 2)

    def test_a_subject_that_moves_or_rescales_is_not(self):
        rep = continuity.report(self._spec([(540, 900), (540, 900), (300, 600), (300, 600)]))
        self.assertFalse(any("never changes state" in w["message"] for w in rep["warnings"]))
        spec = self._spec([(540, 900), (540, 900), (540, 900)])
        spec["scenes"][2]["nodes"][0]["scale"] = [1.4, 1.4]
        rep = continuity.report(spec)
        self.assertFalse(any("never changes state" in w["message"] for w in rep["warnings"]))


class AFieldHandsOffFromWhereItsTilesAre(unittest.TestCase):
    def test_the_pose_is_the_last_visible_layouts_centre(self):
        field = {"id": "f", "type": "particle_field", "position": [0, 0], "continuity_key": "k",
                 "phases": [{"at": 0, "layout": {"kind": "scatter", "box": [0, 0, 1000, 400]}},
                            {"at": 1, "layout": {"kind": "band", "y": 855, "x0": 10, "x1": 1070}},
                            {"at": 2, "layout": {"kind": "hidden"}}]}
        rep = continuity.report(validate_motion_spec({"project": {"duration": 2, "fps": 30},
                                                      "scenes": [{"id": "a", "duration": 2, "nodes": [field]}]}))
        pose = rep["threads"]["k"][0]["pose"]
        self.assertEqual((pose["x"], pose["y"]), (540.0, 855.0))


class RepairHasASecondGuidedRound(unittest.TestCase):
    FIRST = ('{"project":{"duration":2,"fps":30},"storyboard":[{"seconds":2,"job":"open",'
             '"caption":"BUILT FOR AI"}]}')

    def test_the_second_round_names_the_change_and_is_kept_when_cleaner(self):
        from core.motion.generate import repair_prompt
        prompts = []
        still = ('{"nodes":[{"id":"h","type":"text","content":"BUILT FOR AI","position":[540,900],'
                 '"layer":"foreground","continuity_key":"k"}]}')
        moving = ('{"nodes":[{"id":"h","type":"text","content":"BUILT FOR AI","position":[540,900],'
                  '"layer":"foreground","continuity_key":"k","shot":1,'
                  '"animation":{"enter":{"time":0,"duration":0.4,"tweens":[{"channel":"opacity","from":0,"to":1}]},'
                  '"exit":{"time":1.4,"duration":0.4,"tweens":[{"channel":"opacity","from":1,"to":0}]}}}],'
                  '"shot":{"intent":"hold"}}')
        replies = iter([still, still, moving])

        def ask(prompt, expect):
            prompts.append(prompt)
            return next(replies, "")

        def check(one):
            node = one["scenes"][0]["nodes"][0]
            return [] if node.get("animation", {}).get("exit") else [
                'no "foreground" layer node has a real "enter" paired with either an "exit" '
                'or "secondary_motion" — it appears once and then sits completely still until the cut']

        spec = build_spec(self.FIRST, ask, skeleton="cinematic_glass", check=check)
        self.assertEqual(len(prompts), 3)
        self.assertIn("still has these problems", prompts[2])
        self.assertIn('give the foreground node an "exit" block', prompts[2])
        self.assertIn("Keep every node that was not named", prompts[2])
        self.assertIn("exit", spec["scenes"][0]["nodes"][0]["animation"])
        self.assertIn("→", repair_prompt(0, ['the scene names no "shot" — add one'], 1))
        self.assertNotIn("→", repair_prompt(0, ['the scene names no "shot" — add one'], 0))
