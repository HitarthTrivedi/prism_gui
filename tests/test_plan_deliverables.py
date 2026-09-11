"""The plan says what each step will produce, and only a step the person
switched off is treated as switched off.

Two failures from the 11 Sep 2026 audit of the owner's runs:

- A reel whose plan simply did not include "Make the images" came out with
  no pictures. Every unticked row — including rows the planner never turned
  on and nobody touched — reached the engine as skip_stages, and "visual"
  there switches off the artwork step Prism inserts for a reel.
- Nothing on the plan said which step would produce the file or the
  pictures, so a plan that produced neither looked exactly like one that did.

And one the review of the first fix found: a step the planner left out that
the person switched ON and then OFF again was still not counted as off.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from widgets.agents_panel import AgentsPanel  # noqa: E402


def _panel(routing: dict, agents: dict, query: str = "") -> AgentsPanel:
    panel = AgentsPanel()
    panel.set_content(routing, agents, query)
    return panel


def _row(panel: AgentsPanel, stage: str):
    return next(r for r in panel.rows() if r.stage == stage)


REEL = ({"content": {"needed": True, "questions": ["Write the script."]},
         "media": {"needed": True, "questions": ["Film it."]},
         "visual": {"needed": False, "questions": []}},
        {"content": "ChatGPT", "media": "Prism Studio", "visual": "ChatGPT"})


class OnlyWhatThePersonSwitchedOffIsOff(unittest.TestCase):

    def test_a_step_the_planner_never_turned_on_is_not_a_veto(self):
        panel = _panel(*REEL)
        self.assertFalse(_row(panel, "visual").is_checked())
        self.assertEqual([], panel.left_out_stages())

    def test_a_planned_step_the_person_unticks_is(self):
        panel = _panel(
            {"visual": {"needed": True, "questions": ["Make the pictures."]}},
            {"visual": "ChatGPT"})
        _row(panel, "visual").set_included(False)
        self.assertEqual(["visual"], panel.left_out_stages())

    def test_a_step_the_person_switched_on_and_off_again_is_off(self):
        panel = _panel(*REEL)
        row = _row(panel, "visual")
        row.toggle()
        row.toggle()
        self.assertFalse(row.is_checked())
        self.assertEqual(["visual"], panel.left_out_stages())


class EachStepSaysWhatItMakes(unittest.TestCase):
    ASK = "make DOCX document for this product"

    def test_a_document_request_shows_which_step_makes_the_file(self):
        panel = _panel(
            {"content": {"needed": True, "kind": "text", "questions": ["Write it."]}},
            {"content": "Claude"}, query=self.ASK)
        self.assertIn("makes a file to download",
                      _row(panel, "content").engine_meta.text())

    def test_only_one_step_is_marked_as_making_it(self):
        panel = _panel(
            {"brains": {"needed": True, "questions": ["Plan it."]},
             "content": {"needed": True, "questions": ["Write it."]}},
            {"brains": "ChatGPT", "content": "Claude"}, query=self.ASK)
        self.assertNotIn("makes a file", _row(panel, "brains").engine_meta.text())
        self.assertIn("makes a file to download",
                      _row(panel, "content").engine_meta.text())

    def test_a_tool_that_cannot_make_the_file_does_not_claim_to(self):
        panel = _panel(
            {"content": {"needed": True, "questions": ["Write it."]}},
            {"content": "Perplexity"}, query=self.ASK)
        self.assertNotIn("makes a file", _row(panel, "content").engine_meta.text())

    def test_the_picture_step_says_so(self):
        panel = _panel({"visual": {"needed": True, "questions": ["Make it."]}},
                       {"visual": "ChatGPT"})
        self.assertIn("makes pictures", _row(panel, "visual").engine_meta.text())

    def test_a_plain_answer_adds_nothing_to_the_row(self):
        panel = _panel({"brains": {"needed": True, "questions": ["Think."]}},
                       {"brains": "ChatGPT"})
        self.assertNotIn("makes", _row(panel, "brains").engine_meta.text())


if __name__ == "__main__":
    unittest.main()
