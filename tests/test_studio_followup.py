"""A change to a filmed reel goes back to the chat that designed it.

The design conversation holds the look, the storyboard and every scene as
written, so a change asked there costs one turn and comes back in the reel's
own idiom. Before this, a reel follow-up went through the general classifier
and landed on the local renderer (a file for a link, no chat to resume) or on
the writer in a fresh tab — and nothing could change a scene either way.

Nothing here opens a browser: `ask` is a script of replies and `check` a
stub, the same way test_scene_by_scene exercises build_spec.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_web as RW  # noqa: E402


def scene(n, words="words", extra=""):
    return {"type": f"s{n}", "seconds": 4.0, "cut": "push",
            "css": f".a{n}{{color:red}}",
            "html": f"<div class='a{n}'><p>{words}</p>{extra}</div>"}


SPEC = {
    "design": {"name": "paper", "css": ":root{--accent:#5A8B50}"},
    "scenes": [scene(1, "A system, not a style."), scene(2, "Brand, clearly defined."),
               scene(3, "Colour. Typography.")],
    "_assets": {"logo": {"path": "/x/logo.png", "w": 10, "h": 10, "alpha": True,
                         "kind": "logo"}},
    "edits": [{"scene": 0, "path": [0, 0], "dx": 5, "dy": 0, "scale": 1},
              {"scene": 1, "path": [0, 0], "dx": 0, "dy": 9, "scale": 1},
              {"scene": 2, "path": [0], "dx": 0, "dy": 0, "scale": 1.2}],
}


def reply(scenes=None, remove=None, design_css=None):
    got = {"scenes": scenes or []}
    if remove:
        got["remove"] = remove
    if design_css:
        got["design_css"] = design_css
    return "```json\n" + json.dumps(got) + "\n```"


class TheQuestionPutToTheDesignChat(unittest.TestCase):

    def test_it_quotes_the_change_and_numbers_the_scenes(self):
        said = RW.followup_instructions("make scene 2 warmer", SPEC)
        self.assertIn("make scene 2 warmer", said)
        self.assertIn("3 scene(s)", said)
        self.assertIn("2. s2 — Brand, clearly defined.", said)
        self.assertIn("1 to 3", said)

    def test_it_asks_for_complete_scenes_and_only_the_changed_ones(self):
        said = RW.followup_instructions("x", SPEC)
        self.assertIn("COMPLETE", said)
        self.assertIn("replaces the scene outright", said)
        self.assertIn("design_css", said)
        self.assertIn("asset:logo", said)

    def test_new_artwork_is_offered_by_name(self):
        said = RW.followup_instructions("use the new photo", SPEC,
                                        new_assets="  asset:new1 — 800x600, OPAQUE")
        self.assertIn("NEW ARTWORK", said)
        self.assertIn("asset:new1", said)
        self.assertNotIn("NEW ARTWORK", RW.followup_instructions("x", SPEC))


class ReadingTheReply(unittest.TestCase):

    def test_numbered_scenes_come_back_zero_based(self):
        got = RW.parse_followup(reply([{"scene": 2, "seconds": 5, "cut": "zoom",
                                        "css": ".b{}", "html": "<p>new</p>"}]), 3)
        self.assertEqual(list(got["scenes"]), [1])
        self.assertEqual(got["scenes"][1]["html"], "<p>new</p>")
        self.assertEqual(got["scenes"][1]["seconds"], 5.0)
        self.assertEqual(got["scenes"][1]["cut"], "zoom")

    def test_remove_and_design_css_are_read(self):
        got = RW.parse_followup(reply(remove=[3, 9, "x"], design_css=":root{--accent:#000}"), 3)
        self.assertEqual(got["remove"], [2])
        self.assertEqual(got["design_css"], ":root{--accent:#000}")

    def test_a_scene_without_markup_or_a_number_is_ignored(self):
        self.assertIsNone(RW.parse_followup(reply([{"scene": 1, "css": ".x{}"}]), 3))
        self.assertIsNone(RW.parse_followup(reply([{"html": "<p>no number</p>"}]), 3))
        self.assertIsNone(RW.parse_followup("I changed scene two for you.", 3))

    def test_a_design_block_with_css_counts_as_design_css(self):
        got = RW.parse_followup('```json\n{"design": {"css": "body{}"}, "scenes": []}\n```', 3)
        self.assertEqual(got["design_css"], "body{}")


class ApplyingTheChange(unittest.TestCase):

    def test_a_replaced_scene_keeps_its_timing_and_cut_when_not_resent(self):
        new = RW.apply_followup(SPEC, {"scenes": {1: {"html": "<p>new</p>"}},
                                       "remove": [], "design_css": None})
        self.assertEqual(new["scenes"][1]["html"], "<p>new</p>")
        self.assertEqual(new["scenes"][1]["seconds"], 4.0)
        self.assertEqual(new["scenes"][1]["cut"], "push")
        self.assertEqual(new["scenes"][1]["type"], "s2")
        self.assertEqual(SPEC["scenes"][1]["html"], scene(2, "Brand, clearly defined.")["html"],
                         "the filmed spec is not mutated")

    def test_a_number_past_the_end_appends(self):
        new = RW.apply_followup(SPEC, {"scenes": {7: {"html": "<p>x</p>"}},
                                       "remove": [], "design_css": None})
        self.assertEqual(len(new["scenes"]), 4)
        self.assertEqual(new["scenes"][3]["cut"], "push")

    def test_remove_drops_the_scene(self):
        new = RW.apply_followup(SPEC, {"scenes": {}, "remove": [0], "design_css": None})
        self.assertEqual([s["type"] for s in new["scenes"]], ["s2", "s3"])

    def test_design_css_replaces_the_shared_stylesheet(self):
        new = RW.apply_followup(SPEC, {"scenes": {}, "remove": [],
                                       "design_css": ":root{--accent:#111}"})
        self.assertEqual(new["design"]["css"], ":root{--accent:#111}")
        self.assertEqual(new["design"]["name"], "paper")

    def test_hand_edits_survive_only_on_untouched_scenes(self):
        new = RW.apply_followup(SPEC, {"scenes": {1: {"html": "<p>new</p>"}},
                                       "remove": [], "design_css": None})
        self.assertEqual(sorted(e["scene"] for e in new["edits"]), [0, 2])

    def test_a_removal_drops_the_edits_from_that_scene_onward(self):
        new = RW.apply_followup(SPEC, {"scenes": {}, "remove": [1], "design_css": None})
        self.assertEqual([e["scene"] for e in new["edits"]], [0])

    def test_no_edits_left_means_no_edits_key(self):
        new = RW.apply_followup(SPEC, {"scenes": {}, "remove": [0], "design_css": None})
        self.assertNotIn("edits", new)


class TheWholeTurn(unittest.TestCase):

    def test_one_turn_changes_the_scene_and_says_so(self):
        prompts = []

        def ask(prompt, expect=""):
            prompts.append(prompt)
            return reply([{"scene": 2, "css": ".b{}", "html": "<p>warmer</p>"}])

        new, notes = RW.refine_spec(SPEC, "make scene 2 warmer", ask)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(new["scenes"][1]["html"], "<p>warmer</p>")
        self.assertEqual(notes, ["changed scene 2"])

    def test_prose_is_asked_again_once(self):
        replies = iter(["Sure, I've warmed it up.",
                        reply([{"scene": 2, "html": "<p>warmer</p>"}])])
        new, _ = RW.refine_spec(SPEC, "warmer", lambda p, e="": next(replies))
        self.assertEqual(new["scenes"][1]["html"], "<p>warmer</p>")

    def test_nothing_filmable_leaves_the_reel_alone(self):
        with self.assertRaises(RW.ReelError):
            RW.refine_spec(SPEC, "warmer", lambda p, e="": "no.")

    def test_a_layout_fault_is_sent_back_and_a_cleaner_scene_kept(self):
        prompts = []
        replies = iter([reply([{"scene": 1, "html": "<p>bad</p>"}]),
                        reply([{"scene": 1, "html": "<p>good</p>"}])])

        def ask(prompt, expect=""):
            prompts.append(prompt)
            return next(replies)

        def check(spec_):
            return [] if "good" in spec_["scenes"][0]["html"] else ['"bad" overlaps "x"']

        new, _ = RW.refine_spec(SPEC, "x", ask, check=check)
        self.assertEqual(new["scenes"][0]["html"], "<p>good</p>")
        self.assertIn("overlaps", prompts[1])
        self.assertIn("corrected scene 1", prompts[1])

    def test_a_correction_no_better_keeps_the_first(self):
        replies = iter([reply([{"scene": 1, "html": "<p>bad</p>"}]),
                        reply([{"scene": 1, "html": "<p>still bad</p>"}])])
        new, _ = RW.refine_spec(SPEC, "x", lambda p, e="": next(replies),
                                check=lambda s: ["one fault"])
        self.assertEqual(new["scenes"][0]["html"], "<p>bad</p>")

    def test_the_note_names_everything_that_changed(self):
        _, notes = RW.refine_spec(
            SPEC, "x", lambda p, e="": reply(
                [{"scene": 1, "html": "<p>a</p>"}, {"scene": 3, "html": "<p>c</p>"}],
                remove=[2], design_css="body{}"))
        self.assertEqual(notes, ["changed scenes 1, 3; removed 2; the shared stylesheet"])


if __name__ == "__main__":
    unittest.main()
