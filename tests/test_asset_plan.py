"""Where each picture goes is decided once, in the storyboard, and held to.

Scenes are written one turn at a time, and a scene cannot see what the
others did with the artwork. On the 2026-09-07 reel one of three generated
images reached the film as a strip of confetti, and nothing noticed — not
the model, not the check — because nothing had ever said which scene that
picture belonged in. Now the storyboard row names its assets, the scene
prompt repeats them, and a scene that comes back without one is sent back,
with or without a browser.

The same turn-by-turn blindness produced page counters reading "/ 10" on
scenes 1-4 and "/ 06" on 5-6, and a typeface change on scene 5; the scene
prompt now states the count and the continuity rule outright.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import assets as AS  # noqa: E402
from core import reel_web as RW  # noqa: E402

LISTING = ("  asset:logo — 1104x703, transparent PNG, soft edges — a mark\n"
           "  asset:art1 — 1019x1308, transparent PNG, soft edges — imagery\n")

SCRIPT = json.dumps({"scenes": [
    {"role": "hook", "seconds": 4, "headline": "A system, not a style."},
    {"role": "endcard", "seconds": 4, "headline": "Brand", "contact": "brand.example"},
]})

TURN_ONE = json.dumps({
    "design": {"name": "paper and ink", "cut_ms": 500, "css": ":root{--ink:#111}"},
    "storyboard": [
        {"scene": 1, "job": "open", "look": "type", "motion": "rises",
         "cut": "push", "assets": ["art1"]},
        {"scene": 2, "job": "sign off", "look": "mark", "motion": "settles",
         "cut": "push", "assets": ["asset:logo"]},
    ]})


def scene_with(*names):
    imgs = "".join(f"<img src='asset:{n}' alt=''>" for n in names)
    return json.dumps({"seconds": 4, "cut": "push", "css": ".w{color:red}",
                       "html": f"<div class='w'>{imgs}<p>words</p></div>"})


class TheStoryboardNamesTheArtwork(unittest.TestCase):

    def test_the_design_prompt_asks_for_an_asset_plan_when_there_is_art(self):
        said = RW.design_instructions({}, "a reel", LISTING)
        self.assertIn("THE ASSET PLAN", said)
        self.assertIn('"assets": ["logo"]', said)

    def test_but_not_when_there_is_none(self):
        said = RW.design_instructions({}, "a reel", AS.NO_ARTWORK)
        self.assertNotIn("THE ASSET PLAN", said)

    def test_names_are_read_off_the_row_in_any_of_the_shapes_a_model_writes(self):
        self.assertEqual(RW.planned_assets({"assets": ["art1", "asset:logo"]}, LISTING),
                         ["art1", "logo"])
        self.assertEqual(RW.planned_assets({"artwork": "asset:logo and art1"}, LISTING),
                         ["logo", "art1"])
        self.assertEqual(RW.planned_assets({"assets": ["photo", "bg"]}, LISTING), [])
        self.assertEqual(RW.planned_assets({}, LISTING), [])

    def test_the_no_artwork_notice_never_yields_a_name(self):
        self.assertEqual(RW._asset_names(AS.NO_ARTWORK), [])
        self.assertEqual(RW.planned_assets({"assets": ["anything"]}, AS.NO_ARTWORK), [])


class TheScenePromptHoldsTheSceneToIt(unittest.TestCase):

    def test_it_names_what_this_scene_carries(self):
        said = RW.scene_instructions(0, 2, {"assets": ["art1"]}, {"headline": "x"},
                                     LISTING)
        self.assertIn("ARTWORK THIS SCENE CARRIES", said)
        self.assertIn("asset:art1", said)
        self.assertIn("must appear", said)

    def test_and_says_nothing_of_the_sort_when_none_was_planned(self):
        said = RW.scene_instructions(0, 2, {}, {"headline": "x"}, LISTING)
        self.assertNotIn("ARTWORK THIS SCENE CARRIES", said)

    def test_the_counter_and_the_continuity_rule_are_stated(self):
        said = RW.scene_instructions(1, 6, {}, {"headline": "x"})
        self.assertIn("THIS IS SCENE 2 OF 6", said)
        self.assertIn("reads 2 / 6", said)
        self.assertIn("switches typeface family", said)

    def test_the_overlap_rule_is_stated(self):
        said = RW.scene_instructions(0, 2, {}, {"headline": "x"})
        self.assertIn("No two texts may overlap", said)
        self.assertIn("two texts whose boxes overlap",
                      RW.design_instructions({}, "a reel", LISTING))


class ASceneWithoutItsPictureIsSentBack(unittest.TestCase):

    def test_missing_planned_names_the_asset_and_how_to_place_it(self):
        got = RW.missing_planned({"html": "<p>x</p>", "css": ""}, ["logo"])
        self.assertEqual(len(got), 1)
        self.assertIn("asset:logo was planned", got[0])
        self.assertIn("url(asset:logo)", got[0])
        self.assertEqual(RW.missing_planned({"html": "url(asset:logo)"}, ["logo"]), [])

    def test_without_a_browser_the_plan_is_still_enforced(self):
        """check=None: the layout check is off, the asset plan is not."""
        prompts = []
        replies = iter([scene_with(), scene_with("art1"),   # scene 1: bare, then fixed
                        scene_with("logo")])                # scene 2: right first time

        def ask(prompt, expect=""):
            prompts.append(prompt)
            return next(replies)

        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, assets=LISTING)
        self.assertEqual(len(prompts), 3)
        self.assertIn("asset:art1 was planned for this scene", prompts[1])
        self.assertIn("asset:art1", spec["scenes"][0]["html"])
        self.assertIn("asset:logo", spec["scenes"][1]["html"])

    def test_a_correction_that_still_lacks_it_does_not_replace_the_first(self):
        replies = iter([scene_with(), scene_with(), scene_with("logo")])
        spec = RW.build_spec(TURN_ONE, lambda p, e="": next(replies),
                             script=SCRIPT, assets=LISTING)
        self.assertEqual(len(spec["scenes"]), 2)

    def test_the_plan_and_the_layout_faults_travel_together(self):
        prompts = []
        # Scene 1 comes back bare and is corrected; scene 2 is faulted by the
        # layout check both times, so its first attempt is kept.
        replies = iter([scene_with(), scene_with("art1"),
                        scene_with("logo"), scene_with("logo")])

        def ask(prompt, expect=""):
            prompts.append(prompt)
            return next(replies)

        def check(_spec):
            return ['"words" is outside the frame']

        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, assets=LISTING,
                             check=check)
        self.assertEqual(len(spec["scenes"]), 2)
        self.assertIn("asset:art1 was planned", prompts[1])
        self.assertIn("outside the frame", prompts[1])


if __name__ == "__main__":
    unittest.main()
