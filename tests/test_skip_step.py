"""Skip this step — the way past one stuck tool without losing the run.

The report: ChatGPT sat "generating" an image that was never coming (the
image wait never polled stop at all, so nothing could interrupt it), then
the failover handed the stage to a Canva that had no prompt configured —
and the only way out was stopping the whole run. Skip gives up on the
CURRENT stage only, keeps whatever it produced, and moves on.

What is pinned here, without a browser:

  · the engine's contract — run() takes skip_signal, the image wait polls
    the halt, the skip branch keeps the partial and `continue`s (never
    `break`s), and the flag is cleared both when acted on and at the top
    of the next stage so one press skips exactly one step;
  · the worker's switch and the wiring from the button to it;
  · the button itself — beside Stop, only while a run is live, and NOT
    latched (two slow steps in a row can both be skipped).
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge  # noqa: F401,E402

_app = QApplication.instance() or QApplication([])

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TheEngineContract(unittest.TestCase):

    def test_run_accepts_the_skip_signal(self):
        from core import automation
        self.assertIn("skip_signal",
                      inspect.signature(automation.run).parameters)

    def test_the_image_wait_can_be_interrupted(self):
        """The loop that held the run hostage: it slept 4s at a time for up
        to 240s and never once asked whether anyone wanted out."""
        from core import automation
        sig = inspect.signature(automation._wait_for_images).parameters
        self.assertIn("should_stop", sig)
        src = inspect.getsource(automation._wait_for_images)
        self.assertIn("_sleep_interruptibly(4, should_stop)", src)

    def test_a_skip_keeps_the_partial_and_continues(self):
        src = _source("prism_terminal/core/automation.py")
        i = src.index("if skip_requested() and not stopped():")
        block = src[i:src.index("if stopped():", i)]
        self.assertIn("skip_signal.clear()", block)
        self.assertIn('emit("stage_skipped"', block)
        self.assertIn("continue", block)
        self.assertNotIn("break", block, "a skip must never end the run")

    def test_a_leftover_press_cannot_eat_the_next_stage(self):
        """The engine clears the flag at the top of every stage too — a
        skip pressed in the dying moment of one stage skips that stage
        only, never the one after it."""
        src = _source("prism_terminal/core/automation.py")
        loop = src.index("for stage_idx, (stage, agent_name, questions)")
        head = src[loop:loop + 900]
        self.assertIn("if skip_requested():", head)
        self.assertIn("skip_signal.clear()", head)

    def test_the_stage_waits_poll_the_halt_not_just_stop(self):
        src = _source("prism_terminal/core/automation.py")
        self.assertIn("expect=expect, should_stop=stage_halt", src)
        self.assertIn("should_stop=stage_halt)", src)


class SkipWorksDuringFailoverToo(unittest.TestCase):
    """The second report, from a live reel run: "Make the images" had failed
    on ChatGPT and was being retried with Canva, the customer pressed Skip
    this step, and nothing happened. The nested run() the retry starts was
    never given the skip flag, so the one place a customer is most likely to
    press it — watching a second tool grind on the same stuck stage — was the
    one place it did nothing."""

    def _retry_src(self) -> str:
        from core import automation
        return inspect.getsource(automation._retry_failed_stages)

    def test_the_retry_pass_is_given_the_flag(self):
        from core import automation
        params = inspect.signature(automation._retry_failed_stages).parameters
        self.assertIn("skip_signal", params)
        run_src = inspect.getsource(automation.run)
        # rindex: the docstring mentions the function by name first.
        call = run_src[run_src.rindex("_retry_failed_stages("):]
        call = call[:call.index(")")]
        self.assertIn("skip_signal=skip_signal", call)
        self.assertIn("image_stages=image_stages", call)

    def test_a_press_reaches_the_nested_runs_waits(self):
        """As a stop, so the nested run winds up quietly and keeps what
        landed — it has no on_event of its own, so nothing it emits reaches
        the screen; the outer loop reports the skip."""
        src = self._retry_src()
        self.assertIn("should_stop=halt", src)
        self.assertIn("def halt()", src)
        self.assertIn("skipped()", src)

    def test_a_press_abandons_the_other_alternatives(self):
        """Skipping means "move on", not "try the third tool as well"."""
        src = self._retry_src()
        loop = src[src.index("for alternative in"):]
        self.assertIn("if skipped():", loop)
        self.assertIn("give_up(stage, info, texts)", loop)
        self.assertIn("break", loop[loop.index("give_up(stage, info, texts)"):][:80])

    def test_the_skip_is_reported_and_the_flag_cleared(self):
        src = self._retry_src()
        give_up = src[src.index("def give_up("):src.index("recovered: set")]
        self.assertIn("skip_signal.clear()", give_up)
        self.assertIn('"stage_skipped"', give_up)
        self.assertIn("while it was being retried", give_up)


class TheVideoWaitsForItsImages(unittest.TestCase):
    """Same run, the other half: "Make the video — FAILED" on screen while
    "Make the images" was still being retried underneath it. A local
    renderer used to run in its turn regardless; now, when a stage before it
    produced nothing and failover is about to retry that stage, the renderer
    is held back and run after the retry pass."""

    def _run_src(self) -> str:
        from core import automation
        return inspect.getsource(automation.run)

    def test_a_local_stage_is_held_while_a_feeder_awaits_retry(self):
        src = self._run_src()
        branch = src[src.index('if agent_cfg.get("local"):'):]
        branch = branch[:branch.index('emit("stage_start"')]
        self.assertIn("if failover and failures:", branch)
        self.assertIn("deferred_locals.append", branch)
        # and no stage_start until it really runs — the card stays queued
        self.assertNotIn("stage_start", branch)

    def test_the_held_stages_run_after_the_retry_pass(self):
        src = self._run_src()
        after = src[src.index("_retry_failed_stages("):]
        self.assertIn("for stage, agent_name, agent_cfg in deferred_locals:", after)
        self.assertIn("_run_local_stage(stage, agent_name, agent_cfg)", after)

    def test_one_function_renders_in_both_places(self):
        """The main loop and the deferred pass must not drift apart."""
        src = self._run_src()
        self.assertEqual(src.count("_run_local_stage(stage, agent_name, agent_cfg)"), 2)
        self.assertIn("def _run_local_stage(", src)


class TheScriptExampleCannotBeMistakenForABrief(unittest.TestCase):
    """The third fault in the same run. Claude answered the script stage
    with "the tail end of your prompt demands a JSON schema about Bombay
    Super Hybrid Seeds" and refused — the OUTPUT FORMAT block's example was
    a realistic sample about a named seed company, and the model read it as
    a smuggled second brief. No JSON, so the renderer had nothing to build."""

    def test_the_example_names_no_real_company_or_figures(self):
        from core import reel_web
        src = inspect.getsource(reel_web)
        self.assertNotIn("Bombay Super Hybrid Seeds", src)
        self.assertNotIn("66.43 Cr", src)
        self.assertNotIn("Rajkot expansion", src)

    def test_the_example_says_it_is_a_placeholder(self):
        from core import reel_web
        src = inspect.getsource(reel_web)
        self.assertIn("placeholders; every value must come from THIS task's "
                      "material", src)
        self.assertIn('"headline": "<Example Company Name>"', src)


class TheWorkerSwitch(unittest.TestCase):

    def test_skip_sets_the_event_the_engine_is_given(self):
        from workers import AutomationWorker
        w = AutomationWorker({}, {}, [], "task")
        self.assertFalse(w._skip.is_set())
        w.skip()
        self.assertTrue(w._skip.is_set())

    def test_the_event_travels_into_the_run_call(self):
        src = _source("workers.py")
        self.assertIn("skip_signal=self._skip", src)


class TheButton(unittest.TestCase):

    def _view(self):
        from widgets.output_panel import OutputPanel
        return OutputPanel()

    def test_it_sits_beside_stop_and_only_while_running(self):
        v = self._view()
        v.set_running(True)
        self.assertTrue(v.skip_btn.isVisibleTo(v))
        self.assertTrue(v.stop_btn.isVisibleTo(v))
        v.set_running(False)
        self.assertFalse(v.skip_btn.isVisibleTo(v))

    def test_it_emits_and_is_not_latched(self):
        """Stop latches (a second stop is meaningless); Skip must not —
        skipping two slow steps in a row is a legitimate thing to do."""
        v = self._view()
        v.set_running(True)
        seen = []
        v.skip_requested.connect(lambda: seen.append(1))
        v.skip_btn.click()
        v.skip_btn.click()
        self.assertEqual(len(seen), 2)
        self.assertTrue(v.skip_btn.isEnabled())

    def test_the_window_routes_it_to_the_live_worker(self):
        src = _source("main_window.py")
        self.assertIn("output_panel.skip_requested.connect(self._skip_step)",
                      src)
        self.assertIn("worker.skip()", src)


if __name__ == "__main__":
    unittest.main()
