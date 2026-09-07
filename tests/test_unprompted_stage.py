"""A step with no prompt behind it is not run.

What happened on 2026-09-07: the owner ticked "Find the people" and "Think it
through" onto a reel plan the router had not written prompts for. The engine
opened ChatGPT for each, uploaded the brand guide, typed nothing — there was
nothing to type — and then waited the whole 300-second cap for an answer to a
question it had never asked. The first stage cost 322 seconds; the second was
doing the same when Stop was pressed.

Two guards, tested separately because they live in different places:

  · the engine skips a browser stage whose question list is empty BEFORE it
    opens a tab, and says so as a `stage_skipped` event the plan can show;
  · the plan panel can name the ticked rows that have no prompt, which is
    what lets the window refuse the run up front instead of five minutes in.

Nothing here opens a browser. The driver stub fails the test if it is so much
as looked at.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import automation as AU  # noqa: E402


class _UntouchableDriver:
    """Any use of the browser for a stage with no prompt IS the bug."""

    def __getattr__(self, name):
        raise AssertionError(
            f"driver.{name} was used for a stage that has no prompt")


class TheEngineSkipsAnUnpromptedStage(unittest.TestCase):

    def setUp(self):
        self._real_get_driver = AU._get_driver
        AU._get_driver = lambda cfg: (_UntouchableDriver(), True)

    def tearDown(self):
        AU._get_driver = self._real_get_driver

    def _run(self, stages):
        events = []
        responses, links = AU.run(
            {}, {"agents": {"leads": "ChatGPT"}}, custom_stages=stages,
            on_event=lambda kind, payload: events.append((kind, payload)),
            failover=False)
        return responses, links, events

    def test_it_is_skipped_before_a_tab_is_opened(self):
        responses, links, events = self._run([("leads", "ChatGPT", [])])
        kinds = [k for k, _ in events]
        self.assertIn("stage_skipped", kinds)
        # Never started: the plan should show a step left out, not a step
        # that ran and produced nothing.
        self.assertNotIn("stage_start", kinds)
        self.assertEqual((responses, links), ({}, {}))

    def test_the_reason_names_the_step_and_what_to_do(self):
        _, _, events = self._run([("leads", "ChatGPT", [])])
        payload = next(p for k, p in events if k == "stage_skipped")
        self.assertEqual(payload["stage"], "leads")
        self.assertEqual(payload["agent"], "ChatGPT")
        self.assertIn("no prompt", payload["reason"])
        self.assertIn("Open Prompt", payload["reason"])

    def test_a_blank_prompt_counts_as_none(self):
        """Whitespace is what an emptied prompt drawer hands back."""
        _, _, events = self._run([("leads", "ChatGPT", ["", "   \n"])])
        self.assertIn("stage_skipped", [k for k, _ in events])

    def test_it_is_not_a_failure_to_retry_elsewhere(self):
        """A failed stage is retried on another tool; there is nothing to
        send that tool either, so this must not land in the failover pass."""
        events = []
        seen = []
        real = AU._retry_failed_stages
        AU._retry_failed_stages = lambda *a, **k: seen.append(a)
        try:
            AU.run({}, {"agents": {"leads": "ChatGPT"}},
                   custom_stages=[("leads", "ChatGPT", [])],
                   on_event=lambda k, p: events.append(k), failover=True)
        finally:
            AU._retry_failed_stages = real
        self.assertEqual(seen, [])
        self.assertNotIn("stage_error", events)


class ThePlanNamesTheRowsWithoutAPrompt(unittest.TestCase):
    """The panel side: which ticked rows would reach the engine empty."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _panel(self):
        from widgets.agents_panel import AgentsPanel
        panel = AgentsPanel()
        panel.set_content(
            {"leads": {"needed": False, "questions": []},
             "content": {"needed": True, "questions": ["Write the script."]}},
            {"leads": "ChatGPT", "content": "ChatGPT"})
        return panel

    def test_a_step_the_router_planned_is_not_named(self):
        self.assertEqual(self._panel().unprompted_steps(), [])

    def test_a_step_ticked_on_by_hand_is_named_as_the_plan_shows_it(self):
        panel = self._panel()
        row = next(r for r in panel.rows() if r.stage == "leads")
        self.assertFalse(row.is_checked(), "the router did not plan it")
        row.set_included(True)
        self.assertEqual(panel.unprompted_steps(), ["Find the people"])
        # The engine-bound list still carries it, empty — which is exactly
        # why the refusal has to happen before the run rather than in it.
        self.assertIn(("leads", "ChatGPT", []), panel.selected_steps())

    def test_a_prompt_typed_into_the_drawer_clears_it(self):
        panel = self._panel()
        row = next(r for r in panel.rows() if r.stage == "leads")
        row.set_included(True)
        row.set_questions(["Who buys from this brand, and where?"])
        self.assertEqual(panel.unprompted_steps(), [])


if __name__ == "__main__":
    unittest.main()
