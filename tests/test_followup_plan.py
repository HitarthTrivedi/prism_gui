"""A follow-up that needs more than one tool.

"Make a picture of the new truck and put it in scene 3" is the image tool,
then the design chat, then the renderer; "rewrite the script and re-film"
is the writer's chat, then the design chat, then the renderer. The
classifier now returns a plan — the steps, in order — and the window
carries it out: ordinary steps as one relay, each in the chat it answered
in; the reel last, with new pictures adopted as artwork and the earlier
steps' output handed to the design chat as what changed.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402
from core import reel_web as RW  # noqa: E402
import test_followup_session as base  # noqa: E402

SPEC = {"design": {"css": ""}, "_assets": {"logo": {}},
        "scenes": [{"type": "hook", "html": "<p>x</p>", "seconds": 4}]}


class TheClassifierReturnsAPlan(unittest.TestCase):

    def _plan(self, reply, reel):
        from workers import FollowupRouteWorker
        w = FollowupRouteWorker("x", [{"stage": "content", "agent": "ChatGPT",
                                       "summary": "script"}],
                                {"api_key": "k", "model": "m"}, reel=reel)
        got = []
        w.done.connect(got.append)
        with mock.patch.object(CB.router, "groq_chat", return_value=reply):
            w.run()
        return got[0] if got else None

    def test_steps_in_order_with_the_pictures_wanted(self):
        plan = self._plan(json.dumps({"steps": ["artwork", "reel"],
                                      "images": "a red truck"}), reel=True)
        self.assertEqual(plan, {"steps": ["artwork", "reel"], "images": "a red truck"})

    def test_reel_steps_are_only_offered_for_a_reel(self):
        plan = self._plan(json.dumps({"steps": ["artwork", "content", "reel"]}),
                          reel=False)
        self.assertEqual(plan["steps"], ["content"])

    def test_the_old_one_key_shape_still_reads(self):
        plan = self._plan(json.dumps({"stage": "content"}), reel=False)
        self.assertEqual(plan["steps"], ["content"])

    def test_the_prompt_tells_a_reel_task_about_its_two_extra_steps(self):
        from workers import FollowupRouteWorker
        seen = {}
        w = FollowupRouteWorker("x", [{"stage": "content", "agent": "ChatGPT",
                                       "summary": "s"}], {}, reel=True)
        with mock.patch.object(CB.router, "groq_chat",
                               side_effect=lambda *a, **k: seen.setdefault("p", a[2]) and "{}"):
            w.run()
        self.assertIn('"artwork"', seen["p"])
        self.assertIn('"reel"', seen["p"])
        self.assertIn("IN ORDER", seen["p"])


class TheEnginesSideOfAChain(unittest.TestCase):

    def test_the_image_tool_is_asked_for_reel_assets(self):
        said = RW.followup_imagery_instructions("a red truck, side on", SPEC)
        self.assertIn("a red truck, side on", said)
        self.assertIn("TRANSPARENT", said)
        self.assertIn("at most 3", said)
        self.assertIn("asset:logo", said)

    def test_the_design_chat_is_told_what_changed_upstream(self):
        said = RW.followup_instructions("shorter", SPEC, context="[CONTENT]\nNew script")
        self.assertIn("WHAT CHANGED UPSTREAM", said)
        self.assertIn("New script", said)
        self.assertNotIn("WHAT CHANGED UPSTREAM", RW.followup_instructions("x", SPEC))

    def test_refine_spec_passes_the_context_through(self):
        prompts = []

        def ask(prompt, expect=""):
            prompts.append(prompt)
            return json.dumps({"scenes": [{"scene": 1, "html": "<p>new</p>"}]})

        RW.refine_spec(SPEC, "shorter", ask, context="[CONTENT]\nNew script")
        self.assertIn("New script", prompts[0])


class TheWindowCarriesThePlanOut(base.FollowupBase):

    def _ready(self, reel=True):
        win = self._win()
        mp4 = self._filmed() if reel else None
        win._stage_agents = {"content": "ChatGPT", "brains": "Claude",
                             "design": "ChatGPT", "media": "Prism Studio"}
        win._followup_responses = {"content": ["script"], "brains": ["plan"],
                                   "design": ["look"], "media": ["filmed"]}
        win._followup_links = {"content": "https://c/1", "brains": "https://c/0",
                               "design": "https://c/2"}
        if mp4:
            win._followup_links["media"] = mp4
        win._followup_text = "change it"
        win._followup_attachments = []
        return win

    def _route(self, win, plan):
        import main_window
        with mock.patch.object(main_window, "StudioFollowupWorker") as studio, \
             mock.patch.object(main_window, "AutomationWorker") as auto:
            win._on_followup_routed(plan)
        return studio, auto

    def test_pictures_then_the_reel(self):
        win = self._ready()
        studio, auto = self._route(win, {"steps": ["artwork", "reel"],
                                         "images": "a red truck"})
        auto.assert_not_called()
        self.assertTrue(studio.called)
        self.assertEqual(studio.call_args.kwargs["images"], "a red truck")
        self.assertEqual(studio.call_args[0][3], "https://c/2")

    def test_the_writer_first_then_the_reel_with_its_new_script(self):
        win = self._ready()
        studio, auto = self._route(win, {"steps": ["content", "reel"]})
        # First half: the writer, in its own chat, as a follow-up run.
        self.assertTrue(auto.called)
        stages = auto.call_args.kwargs["custom_stages"]
        self.assertEqual([s[0] for s in stages], ["content"])
        self.assertEqual(auto.call_args.kwargs["resume_urls"], {"content": "https://c/1"})
        self.assertTrue(auto.call_args.kwargs["followup"])
        studio.assert_not_called()
        # Its completion continues into the reel, carrying the new script.
        then = auto.return_value.done.connect.call_args[0][0]
        import main_window
        with mock.patch.object(main_window, "StudioFollowupWorker") as studio2, \
             mock.patch.object(win, "_save_run"):
            then({"content": ["The new script."]}, {"content": "https://c/1"})
        self.assertTrue(studio2.called)
        self.assertIn("The new script.", studio2.call_args.kwargs["context"])
        self.assertEqual(studio2.call_args[0][3], "https://c/2")

    def test_two_ordinary_steps_run_as_one_relay(self):
        win = self._ready(reel=False)
        studio, auto = self._route(win, {"steps": ["brains", "content"]})
        studio.assert_not_called()
        stages = auto.call_args.kwargs["custom_stages"]
        self.assertEqual([(s[0], s[1]) for s in stages],
                         [("brains", "Claude"), ("content", "ChatGPT")])
        self.assertIn("redone for this change", stages[1][2][0])
        self.assertNotIn("redone for this change", stages[0][2][0])
        self.assertEqual(auto.call_args.kwargs["resume_urls"],
                         {"brains": "https://c/0", "content": "https://c/1"})

    def test_an_empty_plan_on_a_reel_task_means_the_reel(self):
        win = self._ready()
        studio, auto = self._route(win, {})
        self.assertTrue(studio.called)
        auto.assert_not_called()

    def test_an_empty_plan_otherwise_means_the_last_step(self):
        win = self._ready(reel=False)
        studio, auto = self._route(win, {})
        studio.assert_not_called()
        self.assertEqual(auto.call_args.kwargs["custom_stages"][0][0], "media")

    def test_the_classifier_is_told_when_there_is_a_reel(self):
        import main_window
        win = self._win()
        mp4 = self._filmed()
        win._stage_agents = {"content": "ChatGPT", "design": "ChatGPT"}
        with mock.patch("dialogs.followup_dialog.FollowupDialog", base._dialog("warmer")), \
             mock.patch.object(CB.config, "artifact_task_dir", return_value=self.art), \
             mock.patch.object(main_window, "FollowupRouteWorker") as classifier:
            win._offer_followup({"content": ["s"], "design": ["d"]},
                                {"content": "https://c/1", "design": "https://c/2",
                                 "media": mp4})
        self.assertTrue(classifier.call_args.kwargs["reel"])


if __name__ == "__main__":
    unittest.main()
