"""A tool that finishes with nothing, and a Canva that needs two moves.

The owner's run of 2026-09-10, from its log: ChatGPT put up an empty
reply -- the toolbar under a blank bubble, no Stop button -- and Prism
waited the whole 300s cap for text that was never coming, then handed the
stage to the fallback. And Canva: "the prompt would not go into Canva's
message box" (the registry pointed at a marketing page with no composer),
and once the box was found, nothing ever pressed Generate design.

Pinned here, without a browser:

  · _smart_wait ends early when a reply turn has sat idle and empty --
    and does NOT when the tool is still generating or text has arrived;
  · _regenerate_once clicks the tool's own control, inside the last turn;
  · run() regenerates once before calling an empty answer a failure, and
    only for a tool that has a regenerate control;
  · the Canva entry points at Canva AI with the live page's controls and
    is dispatched to _run_canva, whose steps are the ones the live probe
    needed: dismiss the promo, submit, press Generate design.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import agents as A  # noqa: E402
from core import automation as AU  # noqa: E402

CHATGPT = A.AGENT_REGISTRY["ChatGPT"]


class _El:
    def __init__(self, text=""):
        self.text = text


class _Driver:
    """Answers each selector from a script of readings, one per poll."""

    def __init__(self, script):
        self.script = script          # list of {selector: [texts]}
        self.i = -1
        self.executed = []

    def find_elements(self, _by, sel):
        frame = self.script[min(self.i, len(self.script) - 1)]
        return [_El(t) for t in frame.get(sel, [])]

    def execute_script(self, js, *args):
        self.executed.append(args)
        return True


def _wait(driver, script, cap=600):
    """Run _smart_wait with time faked: every poll advances the clock and
    the driver's reading. Returns (seconds, settled)."""
    clock = [0.0]

    def sleep(sec, *_):
        clock[0] += sec
        driver.i += 1
        return False

    with mock.patch.object(AU.time, "time", lambda: clock[0]), \
            mock.patch.object(AU, "_sleep_interruptibly", sleep):
        return AU._smart_wait(driver, CHATGPT, cap, poll=5,
                              stable_for=25, min_wait=35)


RESP = CHATGPT["response_selector"]
TURN = CHATGPT["turn_selector"]
BUSY = CHATGPT["busy_selector"]


class AnEmptyFinishedTurnEndsTheWait(unittest.TestCase):

    def test_an_idle_empty_turn_settles_in_well_under_a_minute(self):
        # baseline: no turns; then a turn appears, no text, no stop button
        frames = [{TURN: [], RESP: []}] + [{TURN: ["x"], RESP: []}] * 40
        d = _Driver(frames)
        took, settled = _wait(d, frames)
        self.assertTrue(settled)
        self.assertLess(took, 60)
        self.assertGreaterEqual(took, AU.EMPTY_TURN_AFTER)

    def test_a_turn_that_is_still_generating_is_left_alone(self):
        frames = [{TURN: [], RESP: []}] + [{TURN: ["x"], RESP: [], BUSY: ["stop"]}] * 40
        d = _Driver(frames)
        took, settled = _wait(d, frames, cap=120)
        self.assertFalse(settled)
        self.assertGreaterEqual(took, 120)

    def test_text_arriving_takes_the_ordinary_path(self):
        frames = ([{TURN: [], RESP: []}]
                  + [{TURN: ["x"], RESP: ["a" * 200]}] * 3
                  + [{TURN: ["x"], RESP: ["a" * 400]}] * 40)
        d = _Driver(frames)
        took, settled = _wait(d, frames)
        self.assertTrue(settled)
        self.assertGreaterEqual(took, 35)

    def test_a_tool_without_the_selectors_waits_as_before(self):
        plain = {k: v for k, v in CHATGPT.items()
                 if k not in ("busy_selector", "turn_selector")}
        frames = [{TURN: [], RESP: []}] + [{TURN: ["x"], RESP: []}] * 40
        d = _Driver(frames)
        clock = [0.0]

        def sleep(sec, *_):
            clock[0] += sec
            d.i += 1
            return False

        with mock.patch.object(AU.time, "time", lambda: clock[0]), \
                mock.patch.object(AU, "_sleep_interruptibly", sleep):
            took, settled = AU._smart_wait(d, plain, 100, poll=5)
        self.assertFalse(settled)
        self.assertGreaterEqual(took, 100)


class RegenerateOnce(unittest.TestCase):

    def test_it_clicks_the_tools_control_inside_the_last_turn(self):
        d = _Driver([{}])
        self.assertTrue(AU._regenerate_once(d, CHATGPT))
        sel, turn = d.executed[0]
        self.assertEqual(sel, CHATGPT["regenerate_selector"])
        self.assertEqual(turn, CHATGPT["turn_selector"])

    def test_a_tool_without_a_control_is_not_touched(self):
        d = _Driver([{}])
        self.assertFalse(AU._regenerate_once(d, {"regenerate_selector": ""}))
        self.assertEqual(d.executed, [])

    def test_run_regenerates_once_before_recording_a_failure(self):
        src = inspect.getsource(AU.run)
        i = src.index("texts = _capture(driver, agent_cfg)")
        block = src[i:i + 900]
        self.assertIn('agent_cfg.get("regenerate_selector")', block)
        self.assertIn("_regenerate_once(driver, agent_cfg)", block)
        self.assertIn('"empty answer — regenerated once"', block)
        self.assertIn("texts = _capture(driver, agent_cfg)", block[40:])


class TheCanvaEntryMatchesTheLivePage(unittest.TestCase):

    def test_it_points_at_canva_ai_not_the_marketing_page(self):
        c = A.AGENT_REGISTRY["Canva"]
        self.assertEqual(c["url"], "https://www.canva.com/ai")
        self.assertEqual(c["runner"], "canva")
        self.assertEqual(c["textarea_selector"], "textarea[aria-label]")
        self.assertEqual(c["submit_selector"], "button[aria-label='Submit']")

    def test_it_is_dispatched_to_its_own_runner(self):
        src = inspect.getsource(AU.run)
        self.assertIn('agent_cfg.get("runner") == "canva"', src)
        self.assertIn("_run_canva(driver, agent_cfg, stage,", src)

    def test_the_runner_makes_the_two_moves_the_page_needs(self):
        src = inspect.getsource(AU._run_canva)
        self.assertIn("Keys.ESCAPE", src)                 # the promo dialog
        self.assertIn("_click_control(driver, [\"generate design\"]", src)
        self.assertIn('"generate design"', src)          # the second move
        self.assertIn('"view outline"', src)
        self.assertIn("submit_selector", src)

    def test_the_runner_polls_the_halt_between_its_waits(self):
        params = inspect.signature(AU._run_canva).parameters
        self.assertIn("should_stop", params)
        src = inspect.getsource(AU._run_canva)
        self.assertIn("if halted():", src)


class TheHeaderIsShorterAndStillSaysWhatMatters(unittest.TestCase):

    def test_the_rules_survive_the_trim(self):
        header = AU._intent_block("make a poster")
        if not header:
            self.skipTest("header builder is named differently")
        self.assertIn("the words above win", header)
        self.assertIn("must survive", header)
        self.assertLess(len(header) - len("make a poster"), 420)


if __name__ == "__main__":
    unittest.main()
