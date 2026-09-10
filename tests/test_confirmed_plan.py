"""The prompts are written for the plan the person confirmed, not the one
the router guessed.

The owner's deck run of 2026-09-10: the router planned the presentation
step on Gamma and wrote its prompt for Gamma ("a senior presentation
designer experienced with Gamma.app ... plain-text slide format ready for
import into Gamma.app"). The person switched the step to Canva on the
Plan screen. The prompt did not change, Canva received Gamma's brief, and
typed an outline back. Adding, dropping or reordering a step had the same
flaw: the prompts were pre-built.

Pinned here: the reading of the router's plan (planned_steps), the test of
whether the person changed it (plan_changed), and the rewrite for the
confirmed plan (brief_confirmed_plan) -- its prompt names the confirmed
tools and order, carries the maker rule when a maker is in, keeps the
drafts on a bad answer, and gives a promptless step the floor. Groq is a
fake throughout.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import router as R  # noqa: E402

CFG = {"api_key": "gsk_test", "model": "m", "profile": "a mould-tool maker",
       "agents": {"brains": "ChatGPT", "content": "Kimi 2.6",
                  "presentation": "Gamma.app"}}
ROUTING = {
    "brains": {"needed": True, "questions": ["Your ONLY task is: think it through"]},
    "content": {"needed": True, "questions": ["Your ONLY task is: write it up"]},
    "presentation": {"needed": True,
                     "questions": ["Your ONLY task is: act as a designer "
                                   "experienced with Gamma.app; plain-text "
                                   "slide format ready for import into Gamma"]},
    "research": {"needed": False, "questions": []},
    "_brief": "A solution proposal deck for a mould-tech company.",
}


class ReadingThePlan(unittest.TestCase):

    def test_planned_steps_are_the_needed_stages_on_the_configured_tools(self):
        self.assertEqual(R.planned_steps(ROUTING, CFG["agents"]),
                         [("brains", "ChatGPT"), ("content", "Kimi 2.6"),
                          ("presentation", "Gamma.app")])

    def test_an_override_wins_and_a_promptless_stage_is_not_planned(self):
        r = json.loads(json.dumps(ROUTING))
        r["presentation"]["agent_override"] = "Canva"
        r["content"]["questions"] = []
        self.assertEqual(R.planned_steps(r, CFG["agents"]),
                         [("brains", "ChatGPT"), ("presentation", "Canva")])


class DidThePersonChangeIt(unittest.TestCase):
    planned = [("brains", "ChatGPT"), ("content", "Kimi 2.6"), ("presentation", "Gamma.app")]

    def test_the_same_plan_is_not_a_change(self):
        confirmed = [(s, t, ["p"]) for s, t in self.planned]
        self.assertFalse(R.plan_changed(self.planned, confirmed))

    def test_a_swapped_tool_is(self):
        confirmed = [("brains", "ChatGPT", ["p"]), ("content", "Kimi 2.6", ["p"]),
                     ("presentation", "Canva", ["p"])]
        self.assertTrue(R.plan_changed(self.planned, confirmed))

    def test_a_dropped_added_or_moved_step_is(self):
        self.assertTrue(R.plan_changed(self.planned, [("brains", "ChatGPT", ["p"])]))
        self.assertTrue(R.plan_changed(self.planned, [
            ("brains", "ChatGPT", ["p"]), ("content", "Kimi 2.6", ["p"]),
            ("presentation", "Gamma.app", ["p"]), ("visual", "ChatGPT", ["p"])]))
        self.assertTrue(R.plan_changed(self.planned, [
            ("content", "Kimi 2.6", ["p"]), ("brains", "ChatGPT", ["p"]),
            ("presentation", "Gamma.app", ["p"])]))

    def test_a_step_with_no_prompt_is(self):
        confirmed = [("brains", "ChatGPT", ["p"]), ("content", "Kimi 2.6", []),
                     ("presentation", "Gamma.app", ["p"])]
        self.assertTrue(R.plan_changed(self.planned, confirmed))


class RewritingForTheConfirmedPlan(unittest.TestCase):
    steps = [("brains", "ChatGPT", ["Your ONLY task is: think it through"]),
             ("content", "Kimi 2.6", ["Your ONLY task is: write it up"]),
             ("presentation", "Canva", ["Your ONLY task is: act as a designer "
                                        "experienced with Gamma.app; plain-text "
                                        "slide format"])]

    def _fake(self, reply):
        self.sent = []

        def groq(api_key, model, prompt, **kw):
            self.sent.append(prompt)
            return reply
        return groq

    def test_the_prompt_names_the_confirmed_tools_in_order_with_the_maker_rule(self):
        reply = json.dumps({"steps": [
            {"stage": "brains", "questions": ["Your ONLY task is: A"]},
            {"stage": "content", "questions": ["Your ONLY task is: B"]},
            {"stage": "presentation", "questions": ["Your ONLY task is: build the deck in Canva"]}]})
        with mock.patch.object(R, "groq_chat", self._fake(reply)):
            out = R.brief_confirmed_plan("make the deck", CFG, self.steps, ROUTING)
        sent = self.sent[0]
        self.assertIn("STEP 1 — BRAINS on ChatGPT", sent)
        self.assertIn("STEP 3 — PRESENTATION on Canva (last step)", sent)
        self.assertIn("MAKES: an editable Canva design", sent)
        self.assertIn("MAKER TOOLS (Canva)", sent)
        self.assertIn("draft prompt: Your ONLY task is: act as a designer", sent)
        self.assertIn("The task brief the drafts were written from", sent)
        self.assertIn("mould-tool maker", sent)
        self.assertEqual([s[2] for s in out],
                         [["Your ONLY task is: A"], ["Your ONLY task is: B"],
                          ["Your ONLY task is: build the deck in Canva"]])
        self.assertEqual([s[:2] for s in out], [s[:2] for s in self.steps])

    def test_no_maker_rule_when_no_maker_is_in_the_plan(self):
        steps = self.steps[:2]
        reply = json.dumps({"steps": [{"stage": "brains", "questions": ["a"]},
                                      {"stage": "content", "questions": ["b"]}]})
        with mock.patch.object(R, "groq_chat", self._fake(reply)):
            R.brief_confirmed_plan("x", CFG, steps, ROUTING)
        self.assertNotIn("MAKER TOOLS", self.sent[0])

    def test_a_bad_answer_keeps_the_drafts(self):
        for reply in ("not json at all", json.dumps({"steps": [{"stage": "brains", "questions": ["only one"]}]})):
            with self.subTest(reply=reply[:20]), \
                    mock.patch.object(R, "groq_chat", self._fake(reply)):
                out = R.brief_confirmed_plan("x", CFG, self.steps, ROUTING)
            self.assertEqual([s[2] for s in out], [s[2] for s in self.steps])

    def test_a_groq_failure_keeps_the_drafts_and_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError("down")
        with mock.patch.object(R, "groq_chat", boom):
            out = R.brief_confirmed_plan("x", CFG, self.steps, ROUTING)
        self.assertEqual([s[2] for s in out], [s[2] for s in self.steps])

    def test_a_step_with_no_draft_gets_the_floor_on_failure(self):
        steps = [("brains", "ChatGPT", []), ("visual", "ChatGPT", [])]

        def boom(*a, **k):
            raise RuntimeError("down")
        with mock.patch.object(R, "groq_chat", boom):
            out = R.brief_confirmed_plan("draw a poster of a spring", CFG, steps, ROUTING)
        for stage, tool, qs in out:
            self.assertEqual(len(qs), 1)
            self.assertTrue(qs[0].startswith("Your ONLY task is:"))
            self.assertIn("draw a poster of a spring", qs[0])

    def test_no_key_means_the_floor_without_a_call(self):
        cfg = dict(CFG); cfg["api_key"] = ""
        with mock.patch.object(R, "groq_chat", self._fake("")) as groq:
            out = R.brief_confirmed_plan("x", cfg, self.steps, ROUTING)
        self.assertEqual(self.sent, [])
        self.assertEqual([s[2] for s in out], [s[2] for s in self.steps])


class TheWorkerAndTheWindow(unittest.TestCase):

    def test_the_worker_calls_the_router_off_the_thread(self):
        from workers import PlanBriefWorker, _Worker
        self.assertTrue(issubclass(PlanBriefWorker, _Worker))
        w = PlanBriefWorker("q", CFG, [("brains", "ChatGPT", ["p"])], ROUTING)
        got = []
        w.done.connect(got.append)
        with mock.patch.object(core_bridge.router, "brief_confirmed_plan",
                               return_value=[("brains", "ChatGPT", ["new"])]):
            w.run()
        self.assertEqual(got, [[("brains", "ChatGPT", ["new"])]])

    def test_the_run_button_rewrites_before_the_licence_check(self):
        import main_window
        src = inspect.getsource(main_window.MainWindow._run_pipeline)
        self.assertIn("CB.router.plan_changed(", src)
        self.assertIn("PlanBriefWorker(", src)
        self.assertIn("_authorize_and_start(", src)
        after = inspect.getsource(main_window.MainWindow._authorize_and_start)
        self.assertIn("AuthorizeWorker(", after)


if __name__ == "__main__":
    unittest.main()
