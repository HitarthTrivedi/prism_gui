"""The shelf item is called "Reel / Studio" and only ever ran Reel.

Studio — the renderer that films a real web page and art-directs a scene at a
time — was reachable in exactly one way: open Agents, set the Video & Reels
tool to Prism Studio, close it, and type a task on Home. Nobody found that.
Meanwhile the sidebar offered "Reel / Studio", and clicking it ran the
template renderer that gives every client the same film with different words.

A menu entry naming a thing it cannot do is worse than not offering it, and
this one sent a customer off to test the wrong renderer entirely.

So the dialog asks. Studio is the default wherever it can run — it is the
better film — and falls back with the reason attached when the browser engine
it needs is missing.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402
from dialogs.reel_dialog import ReelDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Started(Exception):
    """Raised in place of launching a browser, carrying what it was given."""

    def __init__(self, kwargs):
        super().__init__("started")
        self.kwargs = kwargs


def _dialog(**agents):
    cfg = {"agents": agents or {"content": "ChatGPT"}}
    dlg = ReelDialog(cfg, [], None)
    dlg.ask.set_text("a reel about what we sell")
    return dlg


class BothRenderersAreOffered(unittest.TestCase):

    def test_the_dialog_asks_which(self):
        dlg = _dialog()
        self.assertTrue(dlg.studio_btn.text())
        self.assertTrue(dlg.reel_btn.text())
        self.assertEqual(len(dlg.render_choice.buttons()), 2)

    def test_studio_is_the_default_when_it_can_run(self):
        """It is the better film. The template renderer exists for the
        machine that cannot run a browser, and for the minute-not-minutes
        case — neither is the common one."""
        if not CB.studio_available()[0]:
            self.skipTest("no browser engine on this machine")
        # Held in a local: a dialog dropped on the same line takes its
        # C++ widgets with it before the assertion reads them.
        dlg = _dialog()
        self.assertTrue(dlg.studio_btn.isChecked())

    def test_each_says_what_it_costs(self):
        """The difference that matters to someone choosing is time. Studio is
        minutes, and a person who does not know that reads it as a hang."""
        dlg = _dialog()
        self.assertIn("minutes", dlg.studio_btn.text())
        self.assertIn("minute", dlg.reel_btn.text())

    def test_an_unavailable_studio_is_disabled_with_its_reason(self):
        was = CB.studio_available
        CB.studio_available = lambda: (False, "Playwright is not installed")
        try:
            dlg = _dialog()
            self.assertFalse(dlg.studio_btn.isEnabled())
            self.assertTrue(dlg.reel_btn.isChecked())
            self.assertIn("Playwright", dlg.studio_btn.toolTip())
        finally:
            CB.studio_available = was


class ChoosingStudioRunsStudio(unittest.TestCase):
    """The bug in one sentence: it didn't."""

    def _capture_run(self, dlg):
        """Intercept the worker rather than let it open a browser."""
        import dialogs.reel_dialog as mod
        seen = {}

        class Fake:
            def __init__(self, *a, **kw):
                seen["args"], seen["kwargs"] = a, kw
                self.done = self.failed = _Sig()

            def start(self):
                seen["started"] = True

        class _Sig:
            def connect(self, *_):
                pass

        was = mod.AutomationWorker
        mod.AutomationWorker = Fake
        try:
            dlg._run()
        finally:
            mod.AutomationWorker = was
        return seen

    def test_it_sends_two_writing_passes(self):
        """Words first, look second. One reply asked for both produces a
        design that DESCRIBES itself — "clean data card", "logo reveal" —
        rather than one that exists."""
        dlg = _dialog(content="ChatGPT")
        dlg.studio_btn.setChecked(True)
        seen = self._capture_run(dlg)
        stages = seen["kwargs"]["custom_stages"]
        self.assertEqual([s[0] for s in stages], ["script", "design"])

    def test_it_names_the_stage_that_holds_the_conversation(self):
        """Art direction is several turns — the look and a storyboard, then a
        scene at a time. A routed run infers which stage that is from the
        renderer in its plan; this dialog has no renderer stage, so it must
        say."""
        dlg = _dialog(content="ChatGPT")
        dlg.studio_btn.setChecked(True)
        seen = self._capture_run(dlg)
        self.assertEqual(seen["kwargs"].get("reel_design_stage"), "design")

    def test_the_stronger_tool_art_directs(self):
        """This pass is the harder of the two by a distance."""
        dlg = _dialog(content="ChatGPT", brains="Claude")
        dlg.studio_btn.setChecked(True)
        stages = self._capture_run(dlg)["kwargs"]["custom_stages"]
        self.assertEqual(stages[0][1], "ChatGPT")     # writes the words
        self.assertEqual(stages[1][1], "Claude")      # art-directs

    def test_choosing_quick_still_runs_the_template_renderer(self):
        dlg = _dialog(content="ChatGPT")
        dlg.reel_btn.setChecked(True)
        seen = self._capture_run(dlg)
        self.assertEqual([s[0] for s in seen["kwargs"]["custom_stages"]],
                         ["script"])
        self.assertNotIn("reel_design_stage", seen["kwargs"])


class TheRendererFollowsTheChoice(unittest.TestCase):

    def test_the_worker_is_told_which_engine_to_use(self):
        from workers import ReelWorker
        self.assertTrue(ReelWorker({}, "", studio=True).studio)
        self.assertFalse(ReelWorker({}, "").studio)

    def test_studio_renders_through_the_web_engine(self):
        """Same spec shape, same progress callback, different renderer — and
        picking the wrong one draws a Studio design in Pillow, which cannot
        read its CSS and produces a blank film."""
        from workers import ReelWorker
        import inspect
        src = inspect.getsource(ReelWorker.run)
        self.assertIn("CB.get_studio() if self.studio else CB.get_reel()", src)


if __name__ == "__main__":
    unittest.main()
