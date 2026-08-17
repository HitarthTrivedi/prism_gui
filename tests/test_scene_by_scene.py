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


if __name__ == "__main__":
    unittest.main()
