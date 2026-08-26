"""One scene per turn — the change that stopped reels being slide decks.

The diagnosis was a measurement, not an opinion. A reel built by hand with a
coding agent carried **20,300 characters of markup and motion per scene**; a
reel Prism generated carried **278**. Same renderer, same CSS, same browser.
278 characters is a headline and a subhead — there is nothing in it to move,
so no amount of instruction about motion could ever have fixed it.

The cause was structural: the art director was asked for the whole reel in one
JSON object, and a model writing one JSON object budgets a few thousand
characters and divides them by seven. So the design stage is a conversation
now. Turn one is the look and a storyboard; every scene after that gets a
whole reply to itself.

Two things had to be built for that to be safe, and both are tested here:

  · **Scoping.** A model naming things in reply four cannot see what it called
    them in reply two. Everybody writes `.title`; everybody writes
    `@keyframes rise`. Left alone they collide and whichever scene loses the
    cascade silently inherits another scene's type size and another scene's
    motion. scope_css() confines each scene to its own layer — which is worth
    more than the collisions it prevents, because it means the prompt never
    has to ask a scene to be careful.

  · **Never returning a hole.** More turns means more chances to fail. A scene
    that will not come back is replaced by a plain one built from the script,
    so one bad turn costs one dull scene rather than the whole reel.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_web as RW  # noqa: E402


SCRIPT = json.dumps({"scenes": [
    {"role": "hook", "seconds": 4.5, "kicker": "FY 2026",
     "headline": "A season that held its promise."},
    {"role": "figure", "seconds": 5, "kicker": "Q4 sales",
     "headline": "₹66.43 Cr", "support": "Up 44.7% on last year."},
    {"role": "endcard", "seconds": 4, "headline": "Bombay Super Hybrid Seeds",
     "contact": "www.example.com"},
]})

TURN_ONE = """```json
{"design": {"name": "dusk over a field", "cut_ms": 500,
            "css": ":root{--ink:#12241a}"},
 "storyboard": [
   {"scene": 1, "job": "open", "look": "type low in the frame",
    "motion": "rises from the fold", "cut": "push"},
   {"scene": 2, "job": "the number", "look": "figure edge to edge",
    "motion": "counts up", "cut": "zoom"},
   {"scene": 3, "job": "sign off", "look": "mark centred",
    "motion": "settles", "cut": "push-up"}]}
```"""


def scene_reply(html="<p class='t'>x</p>", css=".t{font-size:90px}", **extra):
    body = {"seconds": 4, "cut": "push", "css": css, "html": html}
    body.update(extra)
    return "```json\n" + json.dumps(body) + "\n```"


class Recorder:
    """Stands in for the browser. Records what was asked and answers from a
    queue, so the whole conversation can be driven without Chromium."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked: list[str] = []

    def __call__(self, prompt, expect=None):
        self.asked.append(prompt)
        return self.replies.pop(0) if self.replies else ""


# ── scoping ─────────────────────────────────────────────────────────────────

class ASceneCannotReachAnotherScene(unittest.TestCase):

    def test_an_ordinary_selector_is_confined(self):
        self.assertEqual(RW.scope_css(".t{color:red}", 3), "#s3 .t{color:red}")

    def test_the_scenes_own_classes_attach_to_the_scene_itself(self):
        """`.leaving` IS the scene layer, not something inside it. Prefixed as
        a descendant it would silently disable every hand-written cut."""
        self.assertEqual(RW.scope_css(".leaving{opacity:0}", 2),
                         "#s2.leaving{opacity:0}")
        self.assertEqual(RW.scope_css(".scene.entering{opacity:1}", 2),
                         "#s2.scene.entering{opacity:1}")

    def test_a_descendant_of_the_leaving_scene_still_reads_correctly(self):
        self.assertEqual(RW.scope_css(".leaving .t{opacity:0}", 1),
                         "#s1.leaving .t{opacity:0}")

    def test_a_scenes_root_is_its_own_layer(self):
        for sel in (":root", "html", "body"):
            self.assertEqual(RW.scope_css(sel + "{--g:2px}", 0),
                             "#s0{--g:2px}", sel)

    def test_keyframes_are_renamed_per_scene(self):
        out = RW.scope_css("@keyframes rise{to{opacity:1}}", 4)
        self.assertIn("@keyframes s4-rise", out)

    def test_the_animation_declaration_follows_the_rename(self):
        """Renaming the keyframes and not the reference is worse than not
        renaming at all — the animation simply stops existing."""
        out = RW.scope_css(
            ".t{animation:rise 800ms cubic-bezier(.16,1,.3,1) both}"
            "@keyframes rise{to{opacity:1}}", 2)
        self.assertIn("animation:s2-rise 800ms", out)
        self.assertNotIn("animation:rise", out)

    def test_a_class_sharing_the_keyframes_name_is_left_alone(self):
        """`.rise` and `@keyframes rise` are both idiomatic and both common.
        Renaming the class would break the markup that points at it."""
        out = RW.scope_css(".rise{animation:rise 1s both}"
                           "@keyframes rise{to{opacity:1}}", 0)
        self.assertIn("#s0 .rise{", out)
        self.assertIn("animation:s0-rise", out)

    def test_a_media_query_is_scoped_inside(self):
        out = RW.scope_css("@media (min-width:100px){.t{color:red}}", 1)
        self.assertIn("@media (min-width:100px){#s1 .t{color:red}}", out)

    def test_font_faces_and_imports_stay_global(self):
        """A @font-face confined to a scene is not a font — it is nothing."""
        out = RW.scope_css("@import url(x.css);@font-face{font-family:A}", 1)
        self.assertIn("@import url(x.css);", out)
        self.assertIn("@font-face{font-family:A}", out)
        self.assertNotIn("#s1 @", out)

    def test_a_brace_inside_a_url_does_not_split_the_stylesheet(self):
        """url() contents are not CSS. A stray brace in a path or a data: URI
        used to be read as structure and cut the stylesheet in half."""
        out = RW.scope_css(".a{background:url(x{y.png)}.b{color:red}", 0)
        self.assertIn("#s0 .b{color:red}", out)

    def test_already_scoped_rules_are_not_scoped_twice(self):
        self.assertEqual(RW.scope_css("#s2 .t{color:red}", 2),
                         "#s2 .t{color:red}")

    def test_nothing_in_becomes_nothing_out(self):
        self.assertEqual(RW.scope_css("", 0), "")
        self.assertEqual(RW.scope_css(None, 0), "")

    def test_two_scenes_naming_things_the_same_do_not_collide(self):
        """The whole reason scoping exists. Verified again against a real
        browser in the render check, but this catches it in milliseconds."""
        page = RW.build_html({"design": {"css": ""}, "scenes": [
            {"seconds": 3, "css": ".t{font-size:120px}", "html": "<p class='t'>a</p>"},
            {"seconds": 3, "css": ".t{font-size:60px}", "html": "<p class='t'>b</p>"},
        ]}, 30)
        self.assertIn("#s0 .t{font-size:120px}", page)
        self.assertIn("#s1 .t{font-size:60px}", page)

    def test_a_scenes_stylesheet_reaches_the_page_at_all(self):
        page = RW.build_html({"design": {"css": ""}, "scenes": [
            {"seconds": 3, "css": ".only{color:#abcdef}", "html": "<p>x</p>"}]},
            30)
        self.assertIn("#s0 .only{color:#abcdef}", page)


# ── turn one ────────────────────────────────────────────────────────────────

class TheLookAndThePlan(unittest.TestCase):

    def test_the_design_and_the_storyboard_come_back(self):
        design, board = RW.parse_design(TURN_ONE)
        self.assertEqual(design["cut_ms"], 500)
        self.assertEqual(len(board), 3)
        self.assertEqual(board[1]["cut"], "zoom")

    def test_a_model_that_answered_the_old_way_still_gives_a_storyboard(self):
        """Some models answer the whole brief however it is put. Scenes in
        place of a storyboard are one row each, not an error."""
        _, board = RW.parse_design(
            '{"design":{"css":""},"scenes":[{"html":"a","cut":"push"},'
            '{"html":"b"}]}')
        self.assertEqual(len(board), 2)
        self.assertEqual(board[0]["cut"], "push")

    def test_no_design_at_all_is_an_error_worth_raising(self):
        with self.assertRaises(RW.ReelError):
            RW.parse_design("I have thought about this and here are my ideas.")

    def test_the_prompt_asks_for_a_storyboard_and_defers_the_scenes(self):
        text = RW.design_instructions()
        self.assertIn('"storyboard"', text)
        self.assertIn("NOT THE SCENES", text)
        self.assertIn("one at a time", text)


class ReadingTheScript(unittest.TestCase):

    def test_the_scenes_come_back_in_order(self):
        got = RW.read_script(SCRIPT)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0]["role"], "hook")

    def test_unreadable_script_is_empty_not_an_exception(self):
        self.assertEqual(RW.read_script("no json here"), [])
        self.assertEqual(RW.read_script(""), [])


# ── the conversation ────────────────────────────────────────────────────────

class OneTurnPerScene(unittest.TestCase):

    def test_every_scene_gets_its_own_turn(self):
        ask = Recorder([scene_reply() for _ in range(3)])
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertEqual(len(spec["scenes"]), 3)
        self.assertEqual(len(ask.asked), 3)

    def test_the_script_length_decides_how_many(self):
        """The script is final by the time this runs. A storyboard with more
        or fewer rows does not get to change the reel's length."""
        short = json.dumps({"scenes": [{"headline": "only one"}]})
        ask = Recorder([scene_reply()])
        spec = RW.build_spec(TURN_ONE, ask, script=short)
        self.assertEqual(len(spec["scenes"]), 1)

    def test_a_scene_prompt_carries_its_own_words_verbatim(self):
        ask = Recorder([scene_reply() for _ in range(3)])
        RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertIn("A season that held its promise.", ask.asked[0])
        self.assertIn("₹66.43 Cr", ask.asked[1])
        # …and not another scene's.
        self.assertNotIn("₹66.43 Cr", ask.asked[0])

    def test_a_scene_prompt_carries_its_own_storyboard_row(self):
        ask = Recorder([scene_reply() for _ in range(3)])
        RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertIn("rises from the fold", ask.asked[0])
        self.assertIn("counts up", ask.asked[1])

    def test_the_prompt_says_how_much_of_the_reply_to_spend(self):
        """The one line that fixes the 278-character scene. `be more detailed`
        is not actionable; a count is."""
        prompt = RW.scene_instructions(0, 3, {}, {"headline": "x"})
        self.assertIn("THIS WHOLE REPLY IS ONE SCENE", prompt)
        self.assertRegex(prompt, r"\b12 to 30 elements\b")

    def test_the_prompt_frees_the_scene_from_worrying_about_names(self):
        """Scoping is only half a win if the model still hedges. Telling it
        the CSS is confined removes a whole class of caution."""
        prompt = RW.scene_instructions(0, 3, {}, {})
        self.assertIn("SCOPED TO THIS SCENE AUTOMATICALLY", prompt)

    def test_a_scene_inherits_the_cut_its_storyboard_chose(self):
        ask = Recorder([scene_reply(cut="") for _ in range(3)])
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertEqual(spec["scenes"][1]["cut"], "zoom")

    def test_a_scene_that_names_its_own_cut_keeps_it(self):
        ask = Recorder([scene_reply(cut="squeeze") for _ in range(3)])
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertEqual(spec["scenes"][1]["cut"], "squeeze")

    def test_stopping_keeps_what_was_written(self):
        ask = Recorder([scene_reply() for _ in range(3)])
        calls = []

        def stop():
            calls.append(1)
            return len(calls) > 2          # let two scenes through
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, should_stop=stop)
        self.assertEqual(len(spec["scenes"]), 2)


class AFailedTurnCostsOneSceneNotTheReel(unittest.TestCase):

    def test_prose_instead_of_json_is_asked_again(self):
        ask = Recorder(["Certainly! Here is my thinking about scene one…",
                        scene_reply(html="<p class='t'>recovered</p>"),
                        scene_reply(), scene_reply()])
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertIn("recovered", spec["scenes"][0]["html"])
        self.assertEqual(len(spec["scenes"]), 3)
        self.assertIn("JSON only", ask.asked[1])

    def test_a_scene_that_never_arrives_becomes_a_plain_one(self):
        ask = Recorder(["nope", "still nope",
                        scene_reply(), scene_reply()])
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT)
        self.assertEqual(len(spec["scenes"]), 3)
        # Built from the script, so the words are still on screen.
        self.assertIn("A season that held its promise.",
                      spec["scenes"][0]["html"])

    def test_the_plain_scene_is_legible_by_construction(self):
        """It is the fallback, so nothing checks it afterwards. Type sizes
        below the video minimum here would ship as a fault nobody caught."""
        sc = RW.fallback_scene({"headline": "H", "support": "S",
                                "kicker": "K"})
        sizes = [int(n) for n in re.findall(r"font-size:(\d+)px", sc["css"])]
        self.assertTrue(sizes)
        self.assertTrue(all(n >= RW.T_LABEL for n in sizes), sizes)

    def test_the_plain_scene_escapes_the_script(self):
        sc = RW.fallback_scene({"headline": "Bell & Sons <Ltd>"})
        self.assertIn("&amp;", sc["html"])
        self.assertNotIn("<Ltd>", sc["html"])

    def test_the_plain_scenes_motion_is_scoped_like_any_other(self):
        page = RW.build_html(
            {"design": {"css": ""},
             "scenes": [RW.fallback_scene({"headline": "a"}),
                        RW.fallback_scene({"headline": "b"})]}, 30)
        self.assertIn("@keyframes s0-fb-in", page)
        self.assertIn("@keyframes s1-fb-in", page)

    def test_an_unreadable_first_turn_raises_rather_than_guessing(self):
        with self.assertRaises(RW.ReelError):
            RW.build_spec("nothing useful", Recorder([]), script=SCRIPT)


class EachSceneIsLaidOutWhileItIsStillTheSubject(unittest.TestCase):
    """The old stage checked all seven at the end, so a fault came back as
    "scene 3's headline is off the frame" against a reply the model had long
    since moved past."""

    def test_a_layout_fault_goes_back_and_the_fix_is_kept(self):
        ask = Recorder([scene_reply(html="<p class='t'>bad</p>"),
                        scene_reply(html="<p class='t'>good</p>"),
                        scene_reply(), scene_reply()])
        seen = []

        def check(spec):
            seen.append(spec)
            return ['"bad" is outside the frame'] if "bad" in \
                spec["scenes"][0]["html"] else []
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, check=check)
        self.assertIn("good", spec["scenes"][0]["html"])
        self.assertIn("is outside the frame", ask.asked[1])

    def test_a_correction_that_is_no_better_is_rejected(self):
        """A "fix" that trades four faults for five is not a fix, and the
        first attempt at least had the composition the storyboard asked for."""
        ask = Recorder([scene_reply(html="<p class='t'>first</p>"),
                        scene_reply(html="<p class='t'>worse</p>"),
                        scene_reply(), scene_reply()])

        def check(spec):
            html = spec["scenes"][0]["html"]
            if "first" in html:
                return ["one"]
            if "worse" in html:
                return ["one", "two"]
            return []
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, check=check)
        self.assertIn("first", spec["scenes"][0]["html"])

    def test_a_checker_that_explodes_does_not_take_the_reel_with_it(self):
        ask = Recorder([scene_reply() for _ in range(3)])

        def check(spec):
            raise RuntimeError("no browser here")
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, check=check)
        self.assertEqual(len(spec["scenes"]), 3)

    def test_the_scene_is_checked_against_the_artwork_it_was_offered(self):
        """Without this the checker sees a spec with no assets, calls every
        correct reference a hole, and talks the design out of its one
        picture."""
        seen = []
        ask = Recorder([scene_reply() for _ in range(3)])
        RW.build_spec(TURN_ONE, ask, script=SCRIPT,
                      assets_table={"logo": {"path": "/tmp/x.png"}},
                      check=lambda s: seen.append(s) or [])
        self.assertIn("logo", seen[0]["_assets"])


class NobodyEverLookedAtTheClientsOwnPictures(unittest.TestCase):
    """What a customer types is "make a reel, here are two screenshots" — and
    that has to be enough, because a product that needs a 400-word brief is a
    product for somebody else.

    So the two things a careful brief would have said are now the pipeline's
    job. One is mechanical and lives in the asset manifest: a landscape
    picture in a portrait frame has to be CROPPED, not shrunk. The other needs
    eyes, and the imagery stage is the only stage in a reel that has them.
    """

    def test_a_wide_picture_is_told_to_be_cropped(self):
        from core import assets as A
        said = A.manifest({"art1": {"kind": "art", "w": 1470, "h": 943,
                                    "alpha": False, "made": False}})
        self.assertIn("CROP INSTEAD OF SHRINKING", said)
        self.assertIn("asset:art1", said.split("WIDER THAN")[1])

    def test_a_portrait_picture_is_left_alone(self):
        from core import assets as A
        said = A.manifest({"art1": {"kind": "art", "w": 800, "h": 1200,
                                    "alpha": False, "made": False}})
        self.assertNotIn("CROP INSTEAD", said)

    def test_a_wide_logo_is_left_alone(self):
        """A wordmark is wider than it is tall by nature, and cropping one in
        half is worse than any amount of shrinking."""
        from core import assets as A
        said = A.manifest({"logo": {"kind": "logo", "w": 900, "h": 200,
                                    "alpha": True, "made": False}})
        self.assertNotIn("CROP INSTEAD", said)

    def test_what_the_imagery_stage_saw_is_read_back(self):
        got = RW.read_pictures([
            "A green circuit board.\n"
            "PICTURE art1: a home screen — crop to the Add folder row\n"
            "PICTURE art2: a seven-step plan — crop to the rows only\n"])
        self.assertEqual(len(got), 2)
        self.assertIn("Add folder", got["art1"])

    def test_a_picture_it_could_not_see_is_not_invented(self):
        """It was told to write NONE rather than guess. A wrong description is
        worse than none — the art director builds a scene around it."""
        got = RW.read_pictures(["PICTURE art1: NONE\nPICTURE art2: a plan"])
        self.assertNotIn("art1", got)
        self.assertIn("art2", got)

    def test_the_example_echoed_back_is_not_a_description(self):
        got = RW.read_pictures(
            ["PICTURE art1: <what is in it, in a few words> — <the ONE part>"])
        self.assertEqual(got, {})

    def test_the_descriptions_reach_the_asset_list(self):
        listing = ("  asset:logo — 512x512, transparent PNG — theirs\n"
                   "  asset:art1 — 1470x943, opaque — artwork the client supplied")
        out = RW.describe_pictures(listing, {"art1": "a seven-step plan"})
        self.assertIn("↳ a seven-step plan", out)
        # …attached to the right line, and no other.
        self.assertEqual(out.count("↳"), 1)
        self.assertIn("asset:logo — 512x512, transparent PNG — theirs\n  asset:",
                      out)

    def test_nothing_seen_leaves_the_list_exactly_as_it_was(self):
        listing = "  asset:art1 — 1x1, opaque — artwork the client supplied"
        self.assertEqual(RW.describe_pictures(listing, {}), listing)

    def test_the_imagery_stage_is_asked_only_when_there_is_something_to_see(self):
        self.assertNotIn("PICTURE", RW.imagery_instructions("x", True))
        asked = RW.imagery_instructions("x", True, attached=["art1", "art2"])
        self.assertIn("PICTURE art1:", asked)
        self.assertIn("PICTURE art2:", asked)

    def test_generated_images_are_requested_as_reusable_assets_not_frames(self):
        asked = RW.imagery_instructions("x")
        self.assertIn("raw visual ingredients, NOT finished reel frames", asked)
        self.assertIn("storyboard, contact sheet, carousel, poster", asked)
        self.assertIn("contain no baked-in copy", asked)

    def test_studio_design_requires_a_readable_layer_contract(self):
        asked = RW.design_instructions(request="make a reel", assets="asset:art1")
        self.assertIn("THE LAYER CONTRACT", asked)
        self.assertIn("required script words 50", asked)
        self.assertIn("A panel may sit behind copy, never across it", asked)

    def test_each_scene_is_told_to_keep_copy_above_artwork(self):
        asked = RW.scene_instructions(
            0, 1, {"job": "hook", "look": "dark", "motion": "rise"},
            {"role": "hook", "headline": "Make it clear", "seconds": 4},
            "asset:art1")
        self.assertIn("Required copy must be the top readable layer", asked)
        self.assertIn("explicit z-index", asked)

    def test_it_is_told_what_to_write_when_it_cannot_see_one(self):
        asked = RW.imagery_instructions("x", True, attached=["art1"])
        self.assertIn("write NONE", asked)


if __name__ == "__main__":
    unittest.main()


class WhatMadeOneReelWorkAndAnotherNot(unittest.TestCase):
    """Both had the same words. The one that worked put the CUSTOMER'S OWN
    MATERIAL on screen — the real filenames out of a Gerber folder, the seven
    real drill sizes, one dot for each of 238 holes. The flat one described
    the same facts in a sentence.

    Written into the prompt across several trades on purpose, so it does not
    read as advice about circuit boards.
    """

    def test_it_asks_for_the_customers_own_material(self):
        prompt = RW.scene_instructions(0, 5, {}, {"headline": "x"})
        self.assertIn("CUSTOMER'S OWN MATERIAL", prompt)
        self.assertIn("not from adjectives", prompt)

    def test_the_examples_are_not_all_one_industry(self):
        """A single worked example gets copied — that is exactly how the
        template renderer's prompt went wrong."""
        prompt = RW.scene_instructions(0, 5, {}, {})
        for trade in ("fabricator", "seed company", "workshop"):
            self.assertIn(trade, prompt, trade)

    def test_it_asks_for_depth_rather_than_a_centred_block(self):
        prompt = RW.scene_instructions(0, 5, {}, {})
        self.assertIn("LAYERS", prompt)
        self.assertIn("Three depths", prompt)

    def test_a_count_may_be_drawn_rather_than_printed(self):
        """238 dots read as 238 holes. The number alone reads as a number."""
        self.assertIn("DRAWING that", RW.scene_instructions(0, 5, {}, {}))


class TheLogoReachesTheSceneThatPlacesIt(unittest.TestCase):
    """This guidance used to live in the art-direction prompt, which wrote
    every scene. That prompt now writes none of them, and the instruction went
    with it — so a reel with a perfectly good logo attached ended on a mark
    drawn out of CSS boxes.
    """

    HAVE = "  asset:logo — 512x512, transparent PNG — the client's own mark"

    def test_the_last_scene_is_told_to_place_it(self):
        last = RW.scene_instructions(4, 5, {}, {}, assets=self.HAVE)
        self.assertIn("THE CLIENT'S OWN MARK IS AVAILABLE", last)
        self.assertIn("this is the last scene", last.lower())

    def test_an_earlier_scene_is_told_not_to_need_it(self):
        """A logo in every scene is a watermark, not a brand."""
        early = RW.scene_instructions(1, 5, {}, {}, assets=self.HAVE)
        self.assertNotIn("THE CLIENT'S OWN MARK IS AVAILABLE", early)
        self.assertIn("does not need to appear in every scene", early)

    def test_it_forbids_redrawing_a_mark_that_exists(self):
        last = RW.scene_instructions(4, 5, {}, {}, assets=self.HAVE)
        self.assertIn("Never redraw", last)
        self.assertIn("CSS shapes", last)

    def test_no_logo_means_no_mention_of_one(self):
        """Told about a mark that does not exist, a scene leaves a hole where
        it planned to put one."""
        art_only = "  asset:art1 — 900x600, opaque — artwork the client supplied"
        said = RW.scene_instructions(4, 5, {}, {}, assets=art_only)
        self.assertNotIn("asset:logo", said)

    def test_a_reel_with_no_artwork_at_all_says_nothing_about_assets(self):
        self.assertNotIn("asset:", RW.scene_instructions(4, 5, {}, {}))


class TheWindowSaysWhichSceneItIsOn(unittest.TestCase):
    """This loop takes minutes — one turn per scene. A dialog that says
    "writing the words…" for all of them is indistinguishable from one that
    has hung, and on a customer's laptop that reads as a crash."""

    def test_every_scene_is_announced_before_it_is_asked_for(self):
        ask = Recorder([scene_reply() for _ in range(3)])
        seen = []
        RW.build_spec(TURN_ONE, ask, script=SCRIPT,
                      on_scene=lambda i, n: seen.append((i, n)))
        self.assertEqual(seen, [(0, 3), (1, 3), (2, 3)])

    def test_a_listener_that_throws_does_not_fail_the_run(self):
        """It is a progress bar. It must never be able to lose the reel."""
        ask = Recorder([scene_reply() for _ in range(3)])

        def boom(i, n):
            raise RuntimeError("the window went away")
        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, on_scene=boom)
        self.assertEqual(len(spec["scenes"]), 3)

    def test_the_run_works_with_no_listener_at_all(self):
        ask = Recorder([scene_reply() for _ in range(3)])
        self.assertEqual(
            len(RW.build_spec(TURN_ONE, ask, script=SCRIPT)["scenes"]), 3)
