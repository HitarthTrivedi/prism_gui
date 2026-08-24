"""The run timeline reads as a sequence you can follow.

Three behaviours, all of them things a nine-stage run needs and a pile of
identical expanded cards cannot give: finished steps get out of the way, a
failed one never does, and there is a way to reach it without scrolling.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                       # noqa: E402

from widgets.output_panel import OutputPanel, short_duration     # noqa: E402

_app = QApplication.instance() or QApplication([])


class Duration(unittest.TestCase):

    def test_it_reads_the_way_somebody_would_say_it(self):
        self.assertEqual(short_duration(8), "8s")
        self.assertEqual(short_duration(100), "1m 40s")
        # Minutes keep counting past the hour rather than rolling over. That
        # is deliberate — the figure has to fit inside a status pill, and a
        # Prism stage runs for tens of minutes, not hours. Pinned so that if
        # anyone does add an hour branch, they do it knowing this was a choice.
        self.assertEqual(short_duration(3700), "61m 40s")

    def test_it_survives_nonsense(self):
        self.assertEqual(short_duration(0), "0s")
        self.assertEqual(short_duration(-5), "0s")


class Folding(unittest.TestCase):

    def setUp(self):
        self.panel = OutputPanel()

    def _card(self, stage="research"):
        self.panel.stage_started(stage, "Perplexity")
        return self.panel._cards[stage]

    def test_a_running_stage_stays_open(self):
        card = self._card()
        self.assertFalse(card._collapsed)
        self.assertFalse(card.failed)

    def test_a_finished_stage_folds_itself_away(self):
        card = self._card()
        self.panel.stage_done("research", ["Some output."], "")
        self.assertTrue(card._collapsed)
        self.assertFalse(card.failed)

    def test_a_failed_stage_stays_open(self):
        card = self._card()
        self.panel.stage_error("research", "Chrome went away.")
        self.assertFalse(card._collapsed)
        self.assertTrue(card.failed)

    def test_a_finished_stage_keeps_its_time_on_screen(self):
        card = self._card()
        card._started = card._started - 100      # pretend it took a while
        self.panel.stage_done("research", ["out"], "")
        self.assertIsNotNone(card.duration)
        # The status used to be a bare Pill carrying the words "Done · 1m 40s".
        # It is now controls.StatusBadge — dot + LABEL + detail, driven by
        # theme.STATUS — so the words come back through status_text() rather
        # than off a QLabel, and the success label is COMPLETED in the OK tone
        # rather than "Done" in the rotating accent.
        self.assertIn("m", self.panel._cards["research"].status_text())
        self.assertEqual(card.state(), "completed")


class EngineWordsReachTheScreen(unittest.TestCase):
    """The panel used to throw away most of what the engine told it."""

    def setUp(self):
        self.panel = OutputPanel()

    def test_a_blocked_step_shows_the_engine_s_own_reason(self):
        # stage_done(count=0) carries `blocked` — the human-readable reason a
        # step came back empty. Nothing showed it, and it is the best piece of
        # copy in the run flow.
        self.panel.stage_started("research", "Perplexity")
        self.panel.stage_done("research", [], "https://perplexity.ai/x",
                              blocked="Perplexity has run out of free "
                                      "messages for today.",
                              exhausted=True)
        card = self.panel._cards["research"]
        self.assertEqual(card.state(), "needs_review")
        self.assertIn("run out", card.note.text())
        # …and it counts as something to jump to.
        self.assertIn(card, self.panel._problem_cards())

    def test_a_failover_reuses_the_card_instead_of_leaking_one(self):
        self.panel.stage_started("research", "Perplexity")
        card = self.panel._cards["research"]
        started = card._started
        self.panel.stage_failover("research", "Perplexity", "Claude",
                                  reason="this tool has run out")
        self.panel.stage_started("research", "Claude")
        self.assertEqual(len(self.panel._order), 1)
        self.assertIs(self.panel._cards["research"], card)
        self.assertEqual(card.agent, "Claude")
        # the elapsed clock does not restart on a retry
        self.assertEqual(card._started, started)

    def test_a_skipped_step_is_no_longer_dropped_in_silence(self):
        self.panel.stage_skipped("leads", "Apollo", "Apollo isn't in Prism's "
                                                    "tool registry.")
        card = self.panel._cards["leads"]
        self.assertEqual(card.state(), "skipped")
        self.assertIn("registry", card.note.text())

    def test_stopping_marks_the_card_that_was_in_flight(self):
        self.panel.stage_started("research", "Perplexity")
        self.panel.run_cancelled("research", done=0)
        self.assertEqual(self.panel._cards["research"].state(), "cancelled")

    def test_the_plan_seeds_the_timeline_as_queued(self):
        self.panel.set_plan({"research": "Perplexity", "content": "Claude"})
        self.assertEqual(self.panel._order, ["research", "content"])
        self.assertEqual(self.panel._cards["research"].state(), "queued")
        self.assertIn("2", self.panel.header.counts.text())


class NextProblem(unittest.TestCase):

    def setUp(self):
        self.panel = OutputPanel()

    def test_the_control_hides_until_something_fails(self):
        self.panel.stage_started("research", "Perplexity")
        self.assertFalse(self.panel.problem_btn.isVisible())

    def test_it_appears_and_counts_the_failures(self):
        for stage in ("research", "brains"):
            self.panel.stage_started(stage, "Tool")
            self.panel.stage_error(stage, "no")
        self.assertEqual(len(self.panel._problem_cards()), 2)
        self.assertIn("2", self.panel.problem_btn.text())

    def test_jumping_cycles_and_opens_what_it_lands_on(self):
        for stage in ("research", "brains"):
            self.panel.stage_started(stage, "Tool")
            self.panel.stage_error(stage, "no")
        problems = self.panel._problem_cards()
        for card in problems:
            card.set_collapsed(True)
        self.panel._next_problem()
        self.assertFalse(problems[0]._collapsed)
        self.panel._next_problem()
        self.assertFalse(problems[1]._collapsed)
        self.panel._next_problem()          # wraps
        self.assertEqual(self.panel._problem_at, 0)

    def test_a_new_run_forgets_the_old_problems(self):
        self.panel.stage_started("research", "Tool")
        self.panel.stage_error("research", "no")
        self.panel.clear()
        self.assertEqual(self.panel._problem_cards(), [])
        self.assertFalse(self.panel.problem_btn.isVisible())


if __name__ == "__main__":
    unittest.main()
