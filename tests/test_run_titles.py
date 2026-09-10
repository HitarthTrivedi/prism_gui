"""Runs, folders, files and chats are named after the job, not the request.

Before this, the request went everywhere verbatim — "make a reel for
instgram for this brand", typo and all, as the folder, the History row and
the Home row — and every chat Prism opened was titled by its own opening
line ("Senior Creative Director Task"), so a sidebar of forty Prism chats
said nothing about which job or which step any of them was.

Now the planner writes a short title alongside the brief, the engine files
the run under it, and the first message of every step opens with
`Prism · <title> · <step>` so the chat is named after the job.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import automation as AU  # noqa: E402
from core import config as CFG  # noqa: E402
from core import router as R  # noqa: E402


class ThePlannerNamesTheJob(unittest.TestCase):

    def test_a_good_answer_is_tidied_and_used(self):
        with mock.patch.object(R, "groq_chat",
                               return_value='{"title": "\\"Instagram reel · brand guide.\\""}'):
            self.assertEqual(R.title_for("make a reel for instgram", "", "k", "m"),
                             "Instagram reel · brand guide")

    def test_the_call_is_cheap_and_in_json_mode(self):
        with mock.patch.object(R, "groq_chat", return_value='{"title": "X"}') as g:
            R.title_for("q", "the brief", "k", "m")
        kw = g.call_args.kwargs
        self.assertTrue(kw.get("json_mode"))
        self.assertEqual(kw.get("retries"), 0)
        self.assertIn("the brief", g.call_args[0][2])

    def test_junk_or_failure_falls_back_to_the_requests_first_words(self):
        with mock.patch.object(R, "groq_chat", return_value="not json"):
            self.assertEqual(R.title_for("make a reel for instgram for this brand",
                                         "", "k", "m"),
                             "make a reel for instgram for this brand")
        with mock.patch.object(R, "groq_chat", side_effect=RuntimeError("down")):
            self.assertEqual(R.title_for("draft an email to the supplier", "", "k", "m"),
                             "draft an email to the supplier")

    def test_route_puts_the_title_on_the_plan(self):
        plan = json.dumps({"brains": {"needed": True, "questions": ["think"]}})
        replies = {"title": '{"title": "Platform like GitHub"}'}

        def groq(api_key, model, prompt, **kw):
            return replies["title"] if "Name this job" in prompt else plan

        with mock.patch.object(R, "groq_chat", groq), \
                mock.patch.object(R, "enrich_query", return_value=""):
            routing = R.route("can we make a platform like github",
                              {"api_key": "k", "agents": {"brains": "ChatGPT"}})
        self.assertEqual(routing["_title"], "Platform like GitHub")


class TheChatIsNamedAfterTheJob(unittest.TestCase):

    def test_the_header_names_the_job_and_the_step(self):
        self.assertEqual(AU._chat_header("Instagram reel · brand guide", "content"),
                         "Prism · Instagram reel · brand guide · Write it up\n\n")
        self.assertEqual(AU._chat_header("X", "design"), "Prism · X · Design the reel\n\n")

    def test_a_duplicated_step_label_still_reads_as_its_step(self):
        self.assertIn("Think it through", AU._chat_header("X", "brains 2"))

    def test_an_unknown_step_is_at_least_readable(self):
        self.assertEqual(AU._chat_header("", "motion_plan"), "Prism · Plan the motion\n\n")
        self.assertEqual(AU._chat_header("", "something_new"), "Prism · Something new\n\n")

    def test_the_first_message_of_every_step_opens_with_it(self):
        """A source-level pin, the way this suite pins other prompt
        assembly: the header is prepended to prompt 1 of each stage."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "prism_terminal", "core", "automation.py"),
                   encoding="utf-8").read()
        self.assertIn("full_prompt = _chat_header(run_title, stage) + full_prompt", src)
        self.assertIn("C.begin_run(query, title=run_title)", src)


class HistoryAndHomeShowTheTitle(unittest.TestCase):

    def test_home_prefers_the_title_and_keeps_the_request(self):
        import tempfile
        import dashboard_data as D
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "run_1.json"), "w", encoding="utf-8") as f:
            json.dump({"query": "make a reel for instgram for this brand",
                       "title": "Instagram reel · brand guide",
                       "agents": {"content": "ChatGPT"}}, f)
        with open(os.path.join(d, "run_2.json"), "w", encoding="utf-8") as f:
            json.dump({"query": "an old run", "agents": {}}, f)
        with mock.patch.object(D, "_run_files", return_value=[
                os.path.join(d, "run_1.json"), os.path.join(d, "run_2.json")]):
            rows = D.recent_runs({})
        self.assertEqual(rows[0]["title"], "Instagram reel · brand guide")
        self.assertEqual(rows[0]["query"], "make a reel for instgram for this brand")
        self.assertEqual(rows[1]["title"], "an old run")


if __name__ == "__main__":
    unittest.main()
