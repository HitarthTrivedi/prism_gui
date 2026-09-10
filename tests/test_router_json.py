"""The plan survives a model that writes almost-JSON.

On 2026-09-07 the planner answered twice with the same fault — a raw double
quote inside a prompt string — and both times the whole plan was thrown away
behind "Something went wrong: Expecting ',' delimiter: line 16 column 49".
The parse was a bare json.loads with no repair and no second ask, on the one
call every run depends on.

Nothing here reaches Groq: groq_chat is replaced by a script of replies.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import router as R  # noqa: E402

GOOD = json.dumps({"brains": {"needed": True,
                              "questions": ["Act as a strategist."]}})
INNER_QUOTE = ('{"brains": {"needed": true, "questions": '
               '["Act as a "senior" strategist for Instagram."]}}')
TRUNCATED = '{"brains": {"needed": true, "questions": ["Act as'
# Balanced braces, so it looks like JSON, but a list never closed — nothing
# the repairs know how to fix.
BROKEN = '{"brains": {"needed": true, "questions": ["Act as" }}'
CFG = {"api_key": "k", "agents": {"brains": "ChatGPT"}}


class _Groq:
    """Answers the plan call from a script; every other call (the brief, the
    suggestions) gets the last reply, which they either ignore or fail to
    parse harmlessly."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, api_key, model, prompt, **kw):
        self.calls.append((prompt, kw))
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


class RepairingTheReply(unittest.TestCase):

    def test_a_raw_quote_inside_a_string_is_escaped(self):
        got, why = R._parse_plan(INNER_QUOTE)
        self.assertIsNone(why)
        self.assertEqual(got["brains"]["questions"],
                         ['Act as a "senior" strategist for Instagram.'])

    def test_valid_json_is_untouched(self):
        got, why = R._parse_plan("Here is the plan:\n" + GOOD + "\nDone.")
        self.assertIsNone(why)
        self.assertEqual(got["brains"]["questions"], ["Act as a strategist."])

    def test_trailing_commas_and_comments_are_forgiven(self):
        # A comment on its own line: that is the only kind _loosen strips,
        # because a mid-line "//" is what every URL in a prompt looks like.
        got, _ = R._parse_plan('{"brains": {"needed": true,\n// yes\n'
                               '"questions": ["x",],},}')
        self.assertEqual(got["brains"]["questions"], ["x"])

    def test_what_cannot_be_repaired_says_why(self):
        got, why = R._parse_plan(BROKEN)
        self.assertIsNone(got)
        self.assertIn("Expecting", str(why))          # the parser's own words
        self.assertEqual(R._parse_plan(TRUNCATED),
                         (None, "no JSON object in the reply"))
        self.assertEqual(R._parse_plan("no braces here"),
                         (None, "no JSON object in the reply"))


class ThePlanCall(unittest.TestCase):

    def setUp(self):
        self._enrich = mock.patch.object(R, "enrich_query", return_value="")
        self._enrich.start()

    def tearDown(self):
        self._enrich.stop()

    def test_the_faulty_reply_is_repaired_without_a_second_call(self):
        groq = _Groq(INNER_QUOTE)
        with mock.patch.object(R, "groq_chat", groq):
            routing = R.route("make a reel", CFG)
        self.assertEqual(routing["brains"]["questions"],
                         ['Act as a "senior" strategist for Instagram.'])
        plan_calls = [c for c in groq.calls if "NOT VALID JSON" in c[0]]
        self.assertEqual(plan_calls, [])

    def test_a_hopeless_reply_is_asked_again_in_json_mode(self):
        groq = _Groq(BROKEN, GOOD)
        with mock.patch.object(R, "groq_chat", groq):
            routing = R.route("make a reel", CFG)
        self.assertEqual(routing["brains"]["questions"], ["Act as a strategist."])
        again = [c for c in groq.calls if "NOT VALID JSON" in c[0]]
        self.assertEqual(len(again), 1)
        self.assertTrue(again[0][1].get("json_mode"))
        self.assertIn("Expecting", again[0][0])       # the parser's own words

    def test_two_hopeless_replies_fail_in_plain_words(self):
        groq = _Groq(BROKEN)
        with mock.patch.object(R, "groq_chat", groq), \
                self.assertRaises(RuntimeError) as caught:
            R.route("make a reel", CFG)
        self.assertIn("planner", str(caught.exception))
        self.assertIn("Make a plan again", str(caught.exception))


class StudioImageryGuardrail(unittest.TestCase):
    def test_studio_reel_gets_visual_stage_when_planner_omits_it(self):
        routing = {"media": {"needed": True, "questions": ["Film it."]}}
        forced = R.apply_studio_imagery_guardrail(
            "make a brand reel", routing,
            {"media": "Prism Studio", "visual": "ChatGPT"})
        self.assertTrue(forced)
        self.assertTrue(routing["visual"]["needed"])

    def test_explicit_type_only_request_stays_type_only(self):
        routing = {"media": {"needed": True, "questions": ["Film it."]}}
        forced = R.apply_studio_imagery_guardrail(
            "make a typography-only reel without images", routing,
            {"media": "Prism Studio", "visual": "ChatGPT"})
        self.assertFalse(forced)
        self.assertNotIn("visual", routing)


if __name__ == "__main__":
    unittest.main()
