"""The art-direction reply is found wherever the tool put it.

A client's Mac (11 Sep 2026): "No JSON found in the agent's reply" for a
Studio run, with the design visibly on screen -- in a side panel, the kind
Claude and ChatGPT open on their own for long code-shaped answers. Pinned:
the prompts forbid that; the design turn is read from an older capture,
from a code panel on the page, or asked for again in the chat before the
run gives up.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: F401,E402
from core import automation as AU  # noqa: E402
from core import reel_web as RW  # noqa: E402

DESIGN = ('```json\n{"design": {"css": "body{margin:0}", "palette": ["#111"]}, '
          '"storyboard": [{"job": "open", "look": "dark", "motion": "rise", '
          '"cut": "push"}]}\n```')
PROSE = ("I've put the complete design spec in the artifact on the right — "
         "palette, type, shared stylesheet and a six-scene storyboard.")
ECHO = ('Reply with only a JSON object describing the reel — {"design": {}, '
        '"storyboard": []} — strict pipeline rules: nothing else.')


class _Page:
    def __init__(self, panels):
        self.panels = panels
        self.calls = 0

    def execute_script(self, js, marker=None):
        self.calls += 1
        return [t for t in self.panels if marker in t]


class ThePromptsSayInTheChat(unittest.TestCase):
    def test_every_json_prompt_forbids_a_side_panel(self):
        for text in (RW.script_instructions(),
                     RW.design_instructions(None, "a reel", ""),
                     RW.scene_instructions(0, 3, {}, {}, "")):
            low = text.lower()
            self.assertIn("artifact", low)
            self.assertIn("canvas", low)
            self.assertIn("chat message", low)


class ThePanelIsRead(unittest.TestCase):
    def test_code_panels_carrying_the_marker_are_returned_minus_the_echo(self):
        page = _Page([ECHO, "short", DESIGN])
        self.assertEqual(AU._rescue_json_from_page(page, '"storyboard"'), [DESIGN])

    def test_a_page_that_cannot_be_asked_is_empty(self):
        class Broken:
            def execute_script(self, *a):
                raise RuntimeError("no session")
        self.assertEqual(AU._rescue_json_from_page(Broken(), '"design"'), [])


class TheDesignTurnIsFound(unittest.TestCase):
    def setUp(self):
        self.asked = []

    def _ask(self, prompt, expect=""):
        self.asked.append(prompt)
        return self._reply

    def test_an_older_capture_that_parses_beats_a_newer_one_that_does_not(self):
        self._reply = ""
        page = _Page([])
        got = AU._design_turn_text(page, {}, [DESIGN, PROSE], RW, self._ask)
        self.assertEqual(got, DESIGN)
        self.assertEqual(self.asked, [])
        self.assertEqual(page.calls, 0, "no need to look at the page")

    def test_a_design_in_a_side_panel_is_read_without_asking_again(self):
        self._reply = ""
        page = _Page([DESIGN])
        got = AU._design_turn_text(page, {}, [PROSE], RW, self._ask)
        self.assertEqual(got, DESIGN)
        self.assertEqual(self.asked, [])

    def test_otherwise_it_is_asked_for_in_the_chat_once(self):
        self._reply = DESIGN
        page = _Page([])
        got = AU._design_turn_text(page, {}, [PROSE], RW, self._ask)
        self.assertEqual(got, DESIGN)
        self.assertEqual(len(self.asked), 1)
        self.assertIn("IN THIS CHAT MESSAGE", self.asked[0])
        self.assertIn("artifact", self.asked[0].lower())

    def test_when_nothing_helps_the_newest_capture_is_kept_for_the_evidence_file(self):
        self._reply = "Sorry, I can't do that."
        got = AU._design_turn_text(_Page([]), {}, [PROSE], RW, self._ask)
        self.assertEqual(got, PROSE)
        self.assertEqual(len(self.asked), 1)


if __name__ == "__main__":
    unittest.main()
