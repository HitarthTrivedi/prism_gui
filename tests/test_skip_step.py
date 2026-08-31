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
