"""Scene transitions: two real bugs, and the library that replaced guesswork.

Both bugs were found by rendering rather than by reading, and both made every
reel look cheap in a way that read as a design fault:

  · **Every exit snapped.** The seeker set EVERY animation's currentTime to
    scene-local time, including one on the scene element itself. A 900ms exit
    animation seeked to 2500ms is long past its end, so
    `.leaving{animation:slideOut 900ms both}` jumped straight to its final
    frame the instant the class landed. Nothing slid out of anything, ever.

  · **The last scene popped in.** `inLen` was the overlap with the NEXT scene
    rather than the previous one — invisible everywhere except the final
    scene, which has no next and so got zero. The endcard, which is the brand
    moment, was the one hard cut in the film.

The library is the other half. Named transitions the design asks for by name,
adapted from HyperFrames' catalogue (Apache 2.0, see NOTICE) and rewritten as
pure functions of --x and --e — correct at every frame by construction, where
an @keyframes transition has to have its duration matched to the cut by hand.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_web as RW  # noqa: E402


def plan(n: int, cut_ms: int = 500, secs: float = 3.0):
    spec = {"design": {"cut_ms": cut_ms},
            "scenes": [{"seconds": secs} for _ in range(n)]}
    return RW._plan(spec, 30)[0]


class EverySceneGetsBothHalvesOfItsCut(unittest.TestCase):

    def test_the_last_scene_arrives_on_something(self):
        """It had inLen 0, so the endcard — the brand moment — was the one
        hard pop in the film."""
        self.assertGreater(plan(3)[-1]["inLen"], 0)

    def test_a_scene_enters_over_the_gap_it_shares_with_the_one_before(self):
        """Not the gap with the one AFTER it, which is what it used to read
        and which is only right when every gap happens to be equal."""
        scenes = plan(3, cut_ms=500, secs=3.0)
        for i in range(1, len(scenes)):
            self.assertEqual(scenes[i]["inLen"], scenes[i - 1]["outLen"])

    def test_the_first_scene_still_opens_on_a_move(self):
        """Nothing behind it to hand over from, but opening on a move rather
        than a jump is worth having and costs nothing."""
        self.assertGreater(plan(3)[0]["inLen"], 0)

    def test_the_last_scene_never_leaves(self):
        self.assertIsNone(plan(3)[-1]["outFrom"])

    def test_a_single_scene_reel_is_coherent(self):
        only = plan(1)[0]
        self.assertIsNone(only["outFrom"])
        self.assertEqual(only["outLen"], 0)

    def test_short_scenes_shrink_the_gap_on_both_sides(self):
        """A cut may never eat more than a third of either neighbour, and the
        two sides of one gap must still agree after that clamp."""
        spec = {"design": {"cut_ms": 900},
                "scenes": [{"seconds": 6}, {"seconds": 1.5}, {"seconds": 6}]}
        scenes = RW._plan(spec, 30)[0]
        for i in range(1, len(scenes)):
            self.assertEqual(scenes[i]["inLen"], scenes[i - 1]["outLen"])


class TheExitClockIsSeparate(unittest.TestCase):
    """A transition on the scene element runs on the CUT's clock, not the
    scene's. Conflating them is what made every exit snap."""

    def _seeker(self) -> str:
        return RW._HARNESS_JS

    def test_a_leaving_scene_rewinds_its_own_animation_to_the_cut(self):
        js = self._seeker()
        self.assertIn("local - s.outFrom", js)

    def test_the_scenes_own_animations_are_found_separately(self):
        """`getAnimations()` without subtree is the scene's own; with subtree
        is everything inside it. The distinction IS the fix."""
        js = self._seeker()
        self.assertIn("el.getAnimations()", js)
        self.assertIn("subtree: true", js)

    def test_content_is_not_placed_twice(self):
        """The subtree pass must skip what the own-animation pass already
        placed, or a leaving scene's content is rewound with it."""
        self.assertIn("ownSet.has(a)", self._seeker())


class TheCutLibrary(unittest.TestCase):

    def css(self) -> str:
        return RW._HARNESS_CSS

    def test_the_named_cuts_exist(self):
        for name in ("cut-push", "cut-push-up", "cut-squeeze", "cut-zoom"):
            self.assertIn(f".{name}.leaving", self.css(), name)
            self.assertIn(f".{name}.entering", self.css(), name)

    def test_they_are_driven_by_the_progress_variables(self):
        """Not @keyframes. A keyframe transition is placed on the scene's
        clock and has to have its duration matched to the cut by hand; these
        are a function of --x and --e and are correct at any frame."""
        block = self.css()[self.css().index(".cut-push.leaving"):]
        self.assertIn("var(--ease)", block)
        self.assertNotIn("@keyframes", block)

    def test_push_moves_both_frames_the_same_way(self):
        """A push where the two halves disagree is two slides in a trench
        coat. Outgoing goes negative, incoming comes from positive, same
        axis."""
        css = self.css()
        self.assertIn("translateX(calc(var(--ease) * -100%))", css)
        self.assertIn("translateX(calc((1 - var(--ease)) * 100%))", css)

    def test_squeeze_compresses_and_opens_from_opposite_edges(self):
        css = self.css()
        self.assertIn("transform-origin: left center", css)
        self.assertIn("transform-origin: right center", css)

    def test_a_scene_can_name_its_cut(self):
        html = RW.build_html({"design": {"css": ""},
                              "scenes": [{"seconds": 3, "cut": "squeeze",
                                          "html": "<p>x</p>"}]}, 30)
        self.assertIn('class="scene cut-squeeze"', html)

    @staticmethod
    def _section(html: str) -> str:
        """The opening <section> tag only. Asserting against the whole
        document catches the library's own `.cut-push` rules in the harness
        CSS, which is not what any of these tests mean."""
        return "<section" + html.split("<section", 1)[1].split(">", 1)[0]

    def test_a_scene_without_one_is_unchanged(self):
        html = RW.build_html({"design": {"css": ""},
                              "scenes": [{"seconds": 3, "html": "<p>x</p>"}]}, 30)
        self.assertIn('class="scene"', self._section(html))
        self.assertNotIn("cut-", self._section(html))

    def test_the_cut_name_cannot_carry_markup(self):
        """It becomes a class attribute and it is written by a model reading
        a customer's own words. The name is reduced to [a-z0-9-], so an
        injected quote cannot close the attribute and start a new one."""
        html = RW.build_html({"design": {"css": ""},
                              "scenes": [{"seconds": 3,
                                          "cut": 'x" onload="alert(1)',
                                          "html": "<p>x</p>"}]}, 30)
        tag = self._section(html)
        # The only attributes are the three we write. Counting quotes would
        # pass or fail on how many attributes the tag happens to have today.
        self.assertEqual(sorted(re.findall(r'(\w[\w-]*)=', tag)),
                         ["class", "data-type", "id"], tag)
        self.assertNotIn("onload", tag.split("class=")[1].split('"')[2])

    def test_the_prompt_offers_them_as_a_choice(self):
        """A menu, not another rule. An earlier attempt added six
        prohibitions to this prompt and made the output blander — told what
        NOT to do, a model plays safe, and safe is what generic is made of."""
        text = RW.design_instructions()
        self.assertIn('"cut": "push"', text)
        for name in ("squeeze", "zoom", "push-up"):
            self.assertIn(name, text)

    def test_the_attribution_is_shipped(self):
        """Apache 2.0 permits this commercially and requires the notice."""
        here = os.path.dirname(os.path.abspath(__file__))
        notice = os.path.join(here, "..", "NOTICE")
        self.assertTrue(os.path.exists(notice), "NOTICE is missing")
        body = open(notice, encoding="utf-8").read()
        self.assertIn("HyperFrames", body)
        self.assertIn("Apache License", body)


if __name__ == "__main__":
    unittest.main()
