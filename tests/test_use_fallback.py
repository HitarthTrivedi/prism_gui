"""Use fallback — hand the running step to its fallback tool now.

The owner's ask: Prism waits a fixed time for a tool to answer and only
then hands the step to the next tool in its category. But the person
watching can often see the tool has errored, and does not want to sit out
600 seconds for Prism to notice. A button beside Skip this step does what
the failover pass would do, for that one step, immediately.

Pinned here, without a browser:

  · the worker's switch and the button (visible only while running, not
    latched, routed to the live worker by a real window);
  · the failover pass honours the flag inside a retry: a press abandons the
    tool that is retrying and moves to the next one, clearing the flag;
  · the engine's contract for the inline hand-off, on the source, in the
    same shape tests/test_skip_step.py uses for Skip.
"""
from __future__ import annotations

import inspect
import os
import sys
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge  # noqa: F401,E402
import plans  # noqa: E402
from test_gates import GateTest  # noqa: E402

_app = QApplication.instance() or QApplication([])
EVERYTHING = tuple(plans.FEATURES)


class TheWorkerSwitch(unittest.TestCase):

    def test_use_fallback_sets_the_event_the_engine_is_given(self):
        from workers import AutomationWorker
        w = AutomationWorker({}, {}, [], "task")
        self.assertFalse(w._fallback.is_set())
        w.use_fallback()
        self.assertTrue(w._fallback.is_set())

    def test_the_event_travels_into_the_run_call(self):
        from workers import AutomationWorker
        src = inspect.getsource(AutomationWorker.run)
        self.assertIn("fallback_signal=self._fallback", src)


class TheButton(unittest.TestCase):

    def _view(self):
        from widgets.output_panel import OutputPanel
        return OutputPanel()

    def test_it_sits_beside_skip_and_only_while_running(self):
        v = self._view()
        v.set_running(True)
        self.assertTrue(v.fallback_btn.isVisibleTo(v))
        self.assertTrue(v.skip_btn.isVisibleTo(v))
        v.set_running(False)
        self.assertFalse(v.fallback_btn.isVisibleTo(v))

    def test_it_emits_and_is_not_latched(self):
        """A second press during the retry means "not that tool either"."""
        v = self._view()
        v.set_running(True)
        seen = []
        v.fallback_requested.connect(lambda: seen.append(1))
        v.fallback_btn.click()
        v.fallback_btn.click()
        self.assertEqual(len(seen), 2)
        self.assertTrue(v.fallback_btn.isEnabled())


class TheWindowRoutesIt(GateTest):

    def test_the_press_reaches_the_live_worker(self):
        self.grant(EVERYTHING)
        win = self._window()
        fake = mock.MagicMock()
        fake.isRunning.return_value = True
        win._active_run = fake
        win.output_panel.fallback_requested.emit()
        fake.use_fallback.assert_called_once()

    def test_nothing_happens_with_no_run_going(self):
        self.grant(EVERYTHING)
        win = self._window()
        fake = mock.MagicMock()
        fake.isRunning.return_value = False
        win._active_run = fake
        win.output_panel.fallback_requested.emit()
        fake.use_fallback.assert_not_called()


class TheFailoverPassHonoursThePress(unittest.TestCase):
    """A press while an alternative is retrying abandons it and moves to
    the next tool, and clears the flag so one press means one tool."""

    def setUp(self):
        from core import automation as AU
        from core import agents as A
        self.AU, self.A = AU, A
        self.flag = threading.Event()
        self.events = []
        self.calls = []

    def _fake_run(self, routing, cfg, **kw):
        stage, alternative, _q = kw["custom_stages"][0]
        self.calls.append(alternative)
        if alternative == "X":
            self.flag.set()             # the person pressed Use fallback
            return {}, {}
        return {stage: ["Y's answer"]}, {stage: "https://y/1"}

    def test_a_press_moves_to_the_next_alternative(self):
        responses, links = {}, {}
        with mock.patch.object(self.AU, "run", self._fake_run), \
                mock.patch.object(self.A, "alternatives_for",
                                  return_value=["X", "Y"]):
            self.AU._retry_failed_stages(
                {"brains": {"agent": "ChatGPT", "questions": ["q"],
                            "reason": "handed over"}},
                {"agents": {}}, responses, links,
                attachments=[], query="task",
                emit=lambda k, p: self.events.append((k, p)),
                should_stop=lambda: False, fallback_signal=self.flag)
        self.assertEqual(self.calls, ["X", "Y"])
        self.assertEqual(responses["brains"], ["Y's answer"])
        self.assertFalse(self.flag.is_set(), "the flag is cleared per press")
        kinds = [k for k, _ in self.events]
        self.assertIn("stage_recovered", kinds)
        recovered = next(p for k, p in self.events if k == "stage_recovered")
        self.assertEqual(recovered["agent"], "Y")

    def test_the_nested_runs_waits_break_on_the_press(self):
        src = inspect.getsource(self.AU._retry_failed_stages)
        self.assertIn("def fallback_pressed()", src)
        halt = src[src.index("def halt()"):src.index("def give_up(")]
        self.assertIn("fallback_pressed()", halt)


class TheEngineContract(unittest.TestCase):
    """The inline hand-off lives inside run()'s 500-line loop, which no
    test can drive without a browser -- so, like Skip, its shape is pinned
    on the source."""

    def _run_src(self) -> str:
        from core import automation
        return inspect.getsource(automation.run)

    def test_run_accepts_the_flag_and_the_waits_poll_it(self):
        from core import automation
        self.assertIn("fallback_signal",
                      inspect.signature(automation.run).parameters)
        src = self._run_src()
        halt = src[src.index("def stage_halt()"):src.index("failures: dict")]
        self.assertIn("fallback_requested()", halt)

    def test_the_hand_off_is_the_failover_pass_for_that_one_stage_now(self):
        src = self._run_src()
        body = src[src.index("def _hand_to_fallback("):src.index("for stage_idx, (stage, agent_name, questions)")]
        self.assertIn("fallback_signal.clear()", body)
        self.assertIn("_retry_failed_stages(\n            {stage: info}", body)
        self.assertIn("fallback_signal=fallback_signal", body)
        # a nested run (failover=False) never fails over again
        self.assertIn("if not failover:", body)

    def test_a_press_is_noticed_after_the_text_wait_and_after_the_image_wait(self):
        src = self._run_src()
        self.assertEqual(
            src.count("_hand_to_fallback(stage, agent_name, questions)"), 2)
        self.assertEqual(src.count("if fallback_requested() and not stopped():"), 2)

    def test_a_stale_press_cannot_eat_the_next_stage(self):
        src = self._run_src()
        loop = src.index("for stage_idx, (stage, agent_name, questions)")
        head = src[loop:loop + 700]
        self.assertIn("if fallback_requested():", head)
        self.assertIn("fallback_signal.clear()", head)


if __name__ == "__main__":
    unittest.main()
