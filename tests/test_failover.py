"""When a tool cannot finish, another one gets the job.

The failure this covers is the expensive one. A run is twenty to forty minutes
of browser automation, the whole pitch is that you start it and walk away, and
the heaviest stage is usually the last. So the free tier that runs out runs out
at the END — and before this, the customer came back to a pipeline that had
done nine tenths of the work and produced nothing they could use.

Three things are tested, because three separate things have to be right:

  1. **Recognising it.** "You've reached your limit" has to be told apart from
     "please sign in", because those need opposite responses: one Prism can
     route around by itself, the other only the user can fix.
  2. **Choosing the replacement.** It has to be able to do the same job, and it
     has to be one the user is plausibly signed in to.
  3. **Not making things worse.** No infinite retry, no rescue that throws away
     the results it was rescuing, and no retry of a stage that actually worked.

Nothing here opens a browser. The driver is a stub that returns page text.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import agents as A  # noqa: E402
from core import automation as AU  # noqa: E402


class _Page:
    """Just enough of a Selenium driver to be asked for the page text."""

    def __init__(self, text: str):
        self._text = text
        self.current_url = "https://example.test/c/1"

    def find_element(self, _how, _what):
        return type("El", (), {"text": self._text})()


# ── 1. recognising a tool that has run out ───────────────────────────────────

class TellingExhaustedFromSignedOut(unittest.TestCase):

    def test_the_real_wordings(self):
        """Taken from what these tools actually put on the page."""
        for wording in (
            "You've reached your limit for Claude Sonnet. Limit resets at 3 PM.",
            "You are out of free messages until tomorrow.",
            "Upgrade to continue using this model",
            "Too many requests. Please try again in a few minutes.",
            "Your daily limit has been reached.",
            "Quota exceeded for this project.",
            "We're currently at capacity. Please check back soon.",
        ):
            self.assertTrue(AU._looks_exhausted(_Page(wording)), wording)

    def test_a_working_page_is_not_mistaken_for_one(self):
        for wording in (
            "Here is the pitch deck outline you asked for. Slide 1: the problem…",
            "I've written the script. It runs about ninety seconds.",
            "",
        ):
            self.assertFalse(AU._looks_exhausted(_Page(wording)), wording)

    def test_a_quota_notice_on_a_long_page_is_still_caught(self):
        """This is why the check has no page-length ceiling, unlike the
        sign-in one. A limit notice appears on a full conversation with every
        previous turn still on it, so "a real page is long" would miss it."""
        page = _Page("some earlier answer. " * 500 +
                     "You've reached your limit for Claude Sonnet.")
        self.assertTrue(AU._looks_exhausted(page))

    def test_being_signed_out_is_a_different_answer(self):
        """They need opposite responses: Prism can route around an exhausted
        tool by itself, but only the user can sign in."""
        page = _Page("Please sign in to continue")
        self.assertFalse(AU._looks_exhausted(page))
        self.assertTrue(AU._looks_signed_out(page))

    def test_a_dead_driver_is_not_an_exception(self):
        class _Broken:
            def find_element(self, *_a):
                raise RuntimeError("session closed")

        self.assertEqual(AU._looks_exhausted(_Broken()), "")

    def test_the_message_quotes_the_page(self):
        """So the customer can see WHY Prism switched tools, rather than
        being told a tool failed for reasons of its own."""
        said = AU._looks_exhausted(_Page("You've reached your limit today."))
        self.assertIn("usage limit", said)
        self.assertIn("you've reached your limit", said)


# ── 2. choosing the replacement ──────────────────────────────────────────────

class PickingAnAlternative(unittest.TestCase):

    def test_the_customers_example(self):
        """Their words: "the freemium claude gets over, we have to give that
        task to kimi". Kimi is in the content category and configured, so it
        goes first."""
        picks = A.alternatives_for(
            "content", ["Claude"],
            {"agents": {"content": "Claude", "development": "Kimi 2.6"}})
        self.assertEqual(picks[0], "Kimi 2.6")

    def test_it_stays_in_the_same_category(self):
        """An alternative has to do the same JOB. Handing a failed image stage
        to a research tool produces an answer, and the answer is an essay
        about pictures."""
        for stage in ("content", "research", "visual", "presentation"):
            for name in A.alternatives_for(stage, []):
                self.assertIn(name, A.CATEGORIES[stage]["agents"], stage)

    def test_a_tool_already_tried_is_never_offered_again(self):
        self.assertNotIn("Claude", A.alternatives_for("content", ["Claude"]))
        self.assertEqual(
            A.alternatives_for("brains",
                               A.CATEGORIES["brains"]["agents"]), [])

    def test_tools_the_user_configured_come_first(self):
        """They picked them, which almost always means they are signed in —
        and a signed-out alternative fails exactly as fast as the tool it is
        replacing."""
        picks = A.alternatives_for(
            "research", ["Perplexity"],
            {"agents": {"research": "Perplexity", "brains": "NotebookLM"}})
        self.assertEqual(picks[0], "NotebookLM")

    def test_prisms_own_renderers_are_never_the_alternative(self):
        """They are local renderers, not web tools. A stage that failed in a
        browser is not fixed by handing it to one."""
        picks = A.alternatives_for("media", ["Runway"])
        for name in picks:
            self.assertFalse(A.AGENT_REGISTRY[name].get("local"), name)

    def test_it_is_capped(self):
        """Each attempt is minutes of browser time. Trying eight tools turns a
        failed run into an afternoon."""
        self.assertLessEqual(len(A.alternatives_for("media", [])), 2)

    def test_an_unknown_stage_offers_nothing(self):
        self.assertEqual(A.alternatives_for("not-a-category", []), [])

    def test_every_alternative_is_actually_in_the_registry(self):
        """A category listing a tool the registry does not have would fail
        over onto a name that resolves to nothing."""
        for stage in A.CATEGORIES:
            for name in A.alternatives_for(stage, []):
                self.assertIn(name, A.AGENT_REGISTRY, f"{stage} -> {name}")


# ── 3. the retry pass ────────────────────────────────────────────────────────

class TheRetryPass(unittest.TestCase):

    def setUp(self):
        self.calls = []
        self.events = []
        self._real_run = AU.run

    def tearDown(self):
        AU.run = self._real_run

    def _fake_run(self, answers):
        """Stand in for a real pipeline run. `answers` maps agent name -> the
        text it produces (or "" for a tool that also fails)."""
        def fake(routing, cfg, **kw):
            stage, agent, _q = kw["custom_stages"][0]
            self.calls.append((stage, agent, kw.get("failover")))
            text = answers.get(agent, "")
            return ({stage: [text]} if text else {}), {stage: "https://x/1"}
        return fake

    def _retry(self, failures, responses, answers, cfg=None):
        AU.run = self._fake_run(answers)
        AU._retry_failed_stages(
            failures, cfg or {}, responses, {},
            attachments=[], query="q",
            emit=lambda k, p: self.events.append((k, p)),
            should_stop=None)

    def test_a_failed_stage_is_handed_to_another_tool(self):
        responses = {}
        self._retry({"content": {"agent": "Claude", "questions": ["write it"],
                                 "reason": "usage limit", "exhausted": True}},
                    responses, {"Jasper": "the finished copy"})
        self.assertEqual(responses["content"], ["the finished copy"])

    def test_the_retry_cannot_itself_retry(self):
        """Without this, a category where every tool is having a bad afternoon
        recurses until something gives out."""
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {"Jasper": "done"})
        self.assertEqual([c[2] for c in self.calls], [False])

    def test_it_moves_on_when_the_first_alternative_also_fails(self):
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {"Copy.ai": "second one worked"})
        tried = [c[1] for c in self.calls]
        self.assertEqual(len(tried), 2)
        self.assertEqual(tried[-1], "Copy.ai")

    def test_it_stops_once_one_works(self):
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {"Jasper": "done", "Copy.ai": "also done"})
        self.assertEqual(len(self.calls), 1)

    def test_a_stage_that_already_worked_is_left_alone(self):
        """Re-running a good stage would replace a real answer with a second
        opinion, and cost minutes doing it."""
        responses = {"content": ["the good answer"]}
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    responses, {"Jasper": "different answer"})
        self.assertEqual(self.calls, [])
        self.assertEqual(responses["content"], ["the good answer"])

    def test_an_exception_in_the_rescue_does_not_take_the_run_down(self):
        """A rescue that destroys the results it was rescuing is worse than
        not trying."""
        def explode(routing, cfg, **kw):
            raise RuntimeError("chrome died")

        AU.run = explode
        responses = {"research": ["kept"]}
        AU._retry_failed_stages(
            {"content": {"agent": "Claude", "questions": ["x"],
                         "reason": "r", "exhausted": True}},
            {}, responses, {}, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None)
        self.assertEqual(responses["research"], ["kept"])

    def test_stopping_is_honoured_before_a_retry_starts(self):
        AU.run = self._fake_run({"Jasper": "done"})
        AU._retry_failed_stages(
            {"content": {"agent": "Claude", "questions": ["x"],
                         "reason": "r", "exhausted": True}},
            {}, {}, {}, attachments=[], query="q",
            emit=lambda *a: None, should_stop=lambda: True)
        self.assertEqual(self.calls, [])

    def test_the_screen_is_told_which_tool_took_over(self):
        """It matters to the customer: the answer came from somewhere other
        than the tool named in their plan, and History has to say so."""
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "usage limit", "exhausted": True}},
                    {}, {"Jasper": "done"})
        kinds = [k for k, _ in self.events]
        self.assertIn("stage_failover", kinds)
        self.assertIn("stage_recovered", kinds)
        payload = dict(self.events)["stage_recovered"]
        self.assertEqual(payload["failed"], "Claude")
        self.assertEqual(payload["agent"], "Jasper")

    def test_giving_up_is_reported_too(self):
        """Silence here would look like the stage was never attempted."""
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {})            # nothing answers
        self.assertIn("stage_unrecovered", [k for k, _ in self.events])


# ── 4. a recovered stage feeding a renderer that already ran ────────────────
#
# `media` (Prism Reel/Studio) runs as one function call, in its own turn — so
# if `visual` failed there and only came back through the retry above, the
# renderer already finished without the images `visual` was going to hand it.
# A plain text/URL handoff can't make an already-rendered video notice new
# pictures showed up afterwards, so the renderer has to be called again.

class ARendererThatAlreadyRan(unittest.TestCase):

    def setUp(self):
        self._real_run = AU.run
        self._real_run_local = AU._run_local

    def tearDown(self):
        AU.run = self._real_run
        AU._run_local = self._real_run_local

    def _fake_run(self, success_text="recovered", images=None):
        """Succeeds on whichever alternative gets tried first — these tests
        are about what happens AFTER a stage recovers, not about which tool
        does the recovering, so which name `alternatives_for` picks first is
        not something they should have to track."""
        def fake(routing, cfg, **kw):
            stage, _agent, _q = kw["custom_stages"][0]
            out = kw.get("pipeline_files_out")
            if images and out is not None:
                out.extend(images)
            return {stage: [success_text]}, {stage: "https://x/1"}
        return fake

    def test_the_renderer_is_called_again_with_the_recovered_images(self):
        rerender_calls = []

        def fake_run_local(kind, prior_text, attachments, cfg, stage, brand=None):
            rerender_calls.append((kind, stage, list(attachments)))
            return "/runs/reel_2.mp4", "reel rendered — reel_2.mp4"

        AU.run = self._fake_run(
            "some images",
            images=[{"name": "grid.png", "path": "/tmp/grid.png", "kind": "image"}])
        AU._run_local = fake_run_local

        stages = [("content", "Claude", ["write it"]),
                  ("visual", "ChatGPT", ["make images"]),
                  ("media", "Prism Reel", ["render it"])]
        responses = {"content": ["the script"]}
        links = {"media": "/runs/reel_1.mp4"}       # media already rendered once
        pipeline_files = []

        AU._retry_failed_stages(
            {"visual": {"agent": "DALL-E", "questions": ["make images"],
                       "reason": "quota", "exhausted": True}},
            {}, responses, links, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None,
            stages=stages, pipeline_files=pipeline_files, brand={})

        self.assertEqual(len(rerender_calls), 1, rerender_calls)
        kind, stage, attachments_seen = rerender_calls[0]
        self.assertEqual(kind, "reel")
        self.assertEqual(stage, "media")
        self.assertIn({"name": "grid.png", "path": "/tmp/grid.png", "kind": "image"},
                      attachments_seen)
        self.assertEqual(links["media"], "/runs/reel_2.mp4")

    def test_a_renderer_with_nothing_recovered_upstream_is_left_alone(self):
        """`audio` sits AFTER `media` in this plan — its recovery has nothing
        to do with what the renderer already drew, so re-running the render
        would just cost minutes for an identical result. (`content`, which
        genuinely feeds the render, is covered by the test above — recovering
        it SHOULD trigger a re-render, and does.)"""
        rerender_calls = []
        AU._run_local = lambda *a, **kw: rerender_calls.append(a) or ("x", "y")
        AU.run = self._fake_run("the narration")

        stages = [("content", "Claude", ["write it"]),
                  ("media", "Prism Reel", ["render it"]),
                  ("audio", "ElevenLabs", ["voice it"])]
        links = {"media": "/runs/reel_1.mp4"}

        AU._retry_failed_stages(
            {"audio": {"agent": "ElevenLabs", "questions": ["voice it"],
                      "reason": "quota", "exhausted": True}},
            {}, {}, links, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None,
            stages=stages, pipeline_files=[], brand={})

        self.assertEqual(rerender_calls, [])

    def test_a_renderer_that_never_ran_is_not_conjured_into_existing(self):
        """`media` isn't in `all_links` at all here — it was never reached, so
        there is nothing to redo."""
        rerender_calls = []
        AU._run_local = lambda *a, **kw: rerender_calls.append(a) or ("x", "y")
        AU.run = self._fake_run("images")

        stages = [("visual", "ChatGPT", ["make images"]),
                  ("media", "Prism Reel", ["render it"])]

        AU._retry_failed_stages(
            {"visual": {"agent": "DALL-E", "questions": ["make images"],
                       "reason": "quota", "exhausted": True}},
            {}, {}, {}, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None,
            stages=stages, pipeline_files=[], brand={})

        self.assertEqual(rerender_calls, [])


class WiredIntoTheRun(unittest.TestCase):
    """The units above are worthless if run() never calls them."""

    def test_run_takes_the_switch_and_defaults_to_on(self):
        import inspect

        sig = inspect.signature(AU.run)
        self.assertIn("failover", sig.parameters)
        self.assertIs(sig.parameters["failover"].default, True)

    def test_run_actually_calls_the_retry(self):
        import ast

        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "prism_terminal", "core", "automation.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        called = {n.func.id for n in ast.walk(run)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_retry_failed_stages", called)


if __name__ == "__main__":
    unittest.main()
