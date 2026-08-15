"""Why a reel that obeyed every motion law still looked like PowerPoint.

The laws in the prompt describe the SEAM — how one scene hands over to the
next. A real reel followed all of them (one current, leftward, no wobble
keyframes anywhere) and came back looking exactly like a slide deck.

The slide-ness was not in the seams. It was inside the scenes:

  · `.entering{animation:pushIn}` slid the ENTIRE frame in as one slab. That
    satisfies "how a scene leaves decides how the next arrives" in the laziest
    available way, and it is a slide by definition.
  · 25 of the 30 things that moved used the same animation, differing only by
    `delay1…delay5`. Nothing led, nothing reacted, nothing was subordinate.

Both are now checked rather than merely requested, because requesting was
tried first and produced the reel that prompted this. The checks are pure
string work on the spec — no browser — so they are cheap and run anywhere.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import reel_web as RW  # noqa: E402


def spec(css: str, *html: str) -> dict:
    return {"design": {"css": css},
            "scenes": [{"html": h} for h in html]}


class TheSceneMustNotMoveAsOneBlock(unittest.TestCase):

    def test_the_real_failure_is_caught(self):
        """Verbatim from the reel that prompted this."""
        faults = RW.motion_faults(spec(
            ".entering{animation:pushIn 900ms cubic-bezier(.16,1,.3,1) both}"
            ".leaving{animation:pushOut 900ms cubic-bezier(.16,1,.3,1) both}",
            "<div class='content'>x</div>"))
        self.assertTrue(faults)
        self.assertIn("one slab", faults[0])

    def test_animating_a_child_of_the_scene_is_fine(self):
        """`.scene.entering .sheet {…}` is animating something INSIDE the
        scene on the way in — which is exactly what we asked for. Matching on
        the selector alone would have banned the fix along with the fault."""
        self.assertEqual(RW.motion_faults(spec(
            ".scene.entering .sheet{animation:glide 900ms both}"
            ".scene.entering .rule{animation:wipe 600ms both}",
            "<div class='sheet'>a</div>")), [])

    def test_styling_the_wrapper_without_moving_it_is_fine(self):
        """A scene may still take a class on the way in — opacity, a filter, a
        background shift. Only a wrapper ANIMATION is the slab."""
        self.assertEqual(RW.motion_faults(spec(
            ".entering{opacity:1}.leaving{opacity:.999}",
            "<div>a</div>")), [])


class EverythingMustNotDoTheSameThing(unittest.TestCase):

    def test_the_real_proportion_is_caught(self):
        """83% on the reel that prompted this. An earlier version of the check
        asked whether there was only ONE animation, which never fires — four
        were declared and it still read as a slide build."""
        css = (".reveal{animation:rise 800ms both}"
               ".lineIn{animation:lineIn 700ms both}"
               ".mark{animation:snap 400ms both}")
        scenes = ["<div class='reveal'>a</div><div class='reveal'>b</div>"
                  "<div class='reveal'>c</div><div class='reveal'>d</div>"
                  "<div class='reveal'>e</div><div class='lineIn'></div>"]
        faults = RW.motion_faults(spec(css, *scenes))
        self.assertTrue(faults)
        self.assertIn("83%", faults[0])

    def test_a_real_composition_passes(self):
        """One element carries the move, the others react differently."""
        css = (".hero{animation:glide 800ms both}"
               ".rule{animation:wipe 600ms both}"
               ".figure{animation:tick 900ms both}"
               ".mark{animation:snap 400ms both}")
        scenes = ["<div class='hero'>a</div><div class='rule'></div>"
                  "<div class='figure'>12</div><div class='mark'></div>"
                  "<div class='hero'>b</div>"]
        self.assertEqual(RW.motion_faults(spec(css, *scenes)), [])

    def test_a_title_card_is_not_nagged(self):
        """Below five moving things there is no composition to get wrong, and
        a card that is one line and a rule would flag every single time."""
        css = ".reveal{animation:rise 800ms both}"
        self.assertEqual(RW.motion_faults(spec(
            css, "<div class='reveal'>a</div><div class='reveal'>b</div>")), [])

    def test_an_animation_nothing_uses_does_not_count(self):
        """Declared-but-unused CSS is common in generated designs. Counting
        declarations rather than uses would let a slide build hide behind
        three animations it never applied."""
        css = (".reveal{animation:rise 800ms both}"
               ".unused1{animation:a 1s both}.unused2{animation:b 1s both}"
               ".unused3{animation:c 1s both}")
        scenes = ["<div class='reveal'>1</div><div class='reveal'>2</div>"
                  "<div class='reveal'>3</div><div class='reveal'>4</div>"
                  "<div class='reveal'>5</div>"]
        faults = RW.motion_faults(spec(css, *scenes))
        self.assertTrue(faults, "hid behind animations it never used")


class TheChecksAreWiredIn(unittest.TestCase):

    def test_an_empty_design_is_not_faulted(self):
        self.assertEqual(RW.motion_faults({}), [])
        self.assertEqual(RW.motion_faults({"design": {"css": "  "}}), [])

    def test_the_prompt_warns_before_the_check_corrects(self):
        """Being told only after the fact wastes a whole round trip."""
        text = RW.design_instructions()
        self.assertIn("DO NOT ANIMATE THE SCENE ITSELF", text)
        self.assertIn("ELEMENTS MUST NOT ALL DO THE SAME THING", text)
        self.assertIn("(This is checked and sent back.)", text)

    def test_the_other_two_rules_are_stated(self):
        """Not checked — too subjective to measure — but still said."""
        text = RW.design_instructions()
        self.assertIn("ONE AXIS AT A TIME", text)
        self.assertIn("KEEP WHAT RECURS", text)

    def test_the_render_check_calls_it(self):
        """The unit is worthless if the renderer never asks."""
        import ast
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "prism_terminal", "core", "reel_web.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("motion_faults(spec)", source)


if __name__ == "__main__":
    unittest.main()
