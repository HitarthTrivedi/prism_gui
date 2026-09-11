"""A prompt is written for the tool that will read it, and what Prism knows
about a tool can be refreshed without a release.

The owner's words, 11 Sep 2026: "when any agent is changed the prompt should
also be built for how that agent thinks, and this should be updated every
now and then." The profile lives in core/agents.py; the signed licence
payload can replace it (licensing/payload.py profiles_for). What must hold:
a publish can change the WORDS Prism sends a tool, never where Prism goes,
and never with a value that would make a step unverifiable.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import agents as A          # noqa: E402
from core import contract as C        # noqa: E402
from licensing import payload as P    # noqa: E402


class WhatAPayloadMaySay(unittest.TestCase):

    @staticmethod
    def claims(profiles):
        return {"content": {"profiles": profiles}}

    def test_the_known_fields_pass(self):
        got = P.profiles_for(self.claims({"Claude": {
            "produces": ["text", "file"], "file_hint": "Build it.",
            "avoid": "Not in a panel."}}))
        self.assertEqual({"Claude": {"produces": ("text", "file"),
                                     "file_hint": "Build it.",
                                     "avoid": "Not in a panel."}}, got)

    def test_it_cannot_change_where_prism_goes_or_how_it_reads(self):
        got = P.profiles_for(self.claims({"Claude": {
            "url": "https://example.invalid", "textarea_selector": "x",
            "avoid": "ok"}}))
        self.assertEqual({"Claude": {"avoid": "ok"}}, got)

    def test_it_cannot_invent_a_kind(self):
        got = P.profiles_for(self.claims({"Claude": {"produces": ["text", "rootkit"]}}))
        self.assertEqual(("text",), got["Claude"]["produces"])

    def test_rubbish_is_ignored(self):
        self.assertEqual({}, P.profiles_for(self.claims({
            "Claude": "nope", "X": {"avoid": "y" * 5000}})))
        self.assertEqual({}, P.profiles_for({}))


class TheEngineUsesThem(unittest.TestCase):

    def setUp(self):
        self._saved = copy.deepcopy(A._PROFILES)

    def tearDown(self):
        A._PROFILES.clear()
        A._PROFILES.update(self._saved)

    def test_a_published_profile_reaches_the_tool(self):
        A.apply_profiles({"Claude": {"avoid": "Answer in the chat."}})
        claude = A.resolve_agent("content", "Claude")
        self.assertEqual("Answer in the chat.", claude["avoid"])
        # A partial publish does not wipe the rest of the built-in profile.
        self.assertIn("file", claude["produces"])

    def test_unpublishing_puts_the_built_in_profile_back(self):
        """An empty payload is an undo. Merging on top of the last one kept
        a withdrawn profile in force until restart."""
        A.apply_profiles({"Claude": {"avoid": "A published line."}})
        A.apply_profiles({})
        self.assertEqual(self._saved["Claude"].get("avoid"),
                         A.resolve_agent("content", "Claude").get("avoid"))

    def test_rubbish_cannot_break_asking(self):
        A.apply_profiles({"Claude": {"produces": "all of them"}, "ChatGPT": None})
        self.assertEqual(self._saved["Claude"]["produces"],
                         A.resolve_agent("content", "Claude")["produces"])

    def test_the_shipped_registry_is_never_changed(self):
        before = dict(A.AGENT_REGISTRY["Claude"])
        A.resolve_agent("content", "Claude")["avoid"] = "mutated"
        self.assertEqual(before, A.AGENT_REGISTRY["Claude"])

    def test_a_tool_that_only_writes_is_not_held_to_a_file(self):
        perplexity = A.resolve_agent("research", "Perplexity")
        self.assertEqual("text", C.for_stage("research", "file", perplexity))

    def test_every_profile_names_a_real_tool(self):
        """A typo here is silent: the profile would simply never apply."""
        for name in A._PROFILES:
            self.assertIn(name, A.AGENT_REGISTRY)

    def test_profiles_stay_inside_what_a_payload_may_set(self):
        for prof in A._PROFILES.values():
            self.assertLessEqual(set(prof), set(P._PROFILE_KEYS))
            for kind in prof.get("produces", ()):
                self.assertIn(kind, C.KINDS)
        self.assertEqual(set(P._PROFILE_KINDS), set(C.KINDS))


if __name__ == "__main__":
    unittest.main()
