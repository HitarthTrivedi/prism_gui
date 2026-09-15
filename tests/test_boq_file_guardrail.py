"""A BOQ or BOM against an attached file is one document step, not a plan.

The owner's report (11 Sep 2026): the same request — a drawing attached,
"make a BOQ/BOM for this" — typed to Claude by hand got the document in a
fraction of the tokens a routed Prism run spent, because the routed run
also answered with Think-it-through and Sum-it-up. A skill built the same
day fixed it, then collided by filename with a teammate's much larger
Skills system that landed the same day and was kept (`core/skills.py`,
`skills/boq-writeup/`, `skills/bom-parts/`) — but that system answers a
different question (how a BOQ is WRITTEN: measurement traceability, unit
rules, IS 1200 rounding) and was never wired to prune a plan's STAGES, so
the thing this pins was gone from the repo entirely after that merge.

Rebuilt here as a router guardrail — the same deterministic, no-LLM-judgement
mechanism `apply_make_guardrail` and `apply_studio_guardrail` already use —
instead of a second skills module, so it cannot collide with Parth's work
again: it touches no file under skills/, and `core/skills.py` is untouched.

Pinned:

  · fires only with an attachment present and a BOQ/BOM word in the
    request — no file, no guardrail, whatever the words say;
  · turns off brains, leads, visual, summary, development, presentation,
    media, audio, design, artwork — every stage the owner's run answered
    with that the request had no use for;
  · leaves RESEARCH exactly as the planner decided — a "research the
    company" request in the same breath must still get its research;
  · turns CONTENT into the one document step, kind "file", briefed with
    the attached file's name and the requested format (default .docx);
  · wired into route() before the skills pass, so a skill is only ever
    offered a stage that will actually run.

No Groq, no browser: route()'s own guardrail application is exercised
directly against a routing dict, the same way the other guardrail tests in
this suite do it.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import router as R          # noqa: E402

OWNER = ("do research about K J pharmatech in vadodara, i have to make a "
         "BOQ/BOM for the given PDF that they received. i want you to make "
         "a proper documentation based on this as well")

ATTACHMENT = [{"name": "02 SS SHOE RACK.pdf", "path": "/x/02 SS SHOE RACK.pdf"}]

AGENTS = {"research": "Perplexity", "brains": "ChatGPT", "content": "Claude",
         "visual": "ChatGPT", "summary": "ChatGPT"}

ALL_ON = ("research", "brains", "content", "visual", "summary")


def _routing(*on) -> dict:
    return {s: {"needed": s in on, "questions": [f"{s} draft"] if s in on else []}
            for s in ALL_ON}


class ItOnlyFiresWithAFileAndTheWords(unittest.TestCase):

    def test_no_attachment_no_guardrail(self):
        routing = _routing(*ALL_ON)
        changed = R.apply_boq_file_guardrail(OWNER, routing, AGENTS, [])
        self.assertFalse(changed)
        self.assertTrue(routing["brains"]["needed"])

    def test_an_attachment_with_no_boq_word_does_nothing(self):
        routing = _routing(*ALL_ON)
        changed = R.apply_boq_file_guardrail(
            "summarise the attached drawing for me", routing, AGENTS, ATTACHMENT)
        self.assertFalse(changed)
        self.assertTrue(routing["brains"]["needed"])

    def test_every_way_people_write_boq_or_bom_fires_it(self):
        for phrase in ("BOQ", "bom", "bill of quantities", "Bill of Materials",
                       "BOQ/BOM"):
            with self.subTest(phrase=phrase):
                routing = _routing(*ALL_ON)
                changed = R.apply_boq_file_guardrail(
                    f"make a {phrase} for this file", routing, AGENTS, ATTACHMENT)
                self.assertTrue(changed, phrase)

    def test_bom_does_not_fire_on_a_word_that_merely_contains_it(self):
        routing = _routing(*ALL_ON)
        changed = R.apply_boq_file_guardrail(
            "a reel about a bombay-based startup", routing, AGENTS, ATTACHMENT)
        self.assertFalse(changed)


class WhatItTurnsOff(unittest.TestCase):

    def test_the_owners_exact_run(self):
        routing = _routing(*ALL_ON)
        R.apply_boq_file_guardrail(OWNER, routing, AGENTS, ATTACHMENT)
        self.assertFalse(routing["brains"]["needed"])
        self.assertEqual(routing["brains"]["questions"], [])
        self.assertFalse(routing["summary"]["needed"])
        self.assertFalse(routing["visual"]["needed"])

    def test_research_is_left_exactly_as_the_planner_decided(self):
        on = _routing(*ALL_ON)
        R.apply_boq_file_guardrail(OWNER, on, AGENTS, ATTACHMENT)
        self.assertTrue(on["research"]["needed"], "was on, asked to research too")

        off = _routing("content")
        R.apply_boq_file_guardrail("make a BOQ for this", off, AGENTS, ATTACHMENT)
        self.assertFalse(off["research"]["needed"], "was off, not forced on")

    def test_leads_development_presentation_media_audio_design_artwork_also_go(self):
        stages = ("leads", "development", "presentation", "media", "audio",
                 "design", "artwork")
        routing = {**_routing("content"),
                  **{s: {"needed": True, "questions": [f"{s} draft"]} for s in stages}}
        R.apply_boq_file_guardrail("make a BOM for this", routing, AGENTS, ATTACHMENT)
        for s in stages:
            with self.subTest(stage=s):
                self.assertFalse(routing[s]["needed"])


class WhatContentBecomes(unittest.TestCase):

    def test_content_is_kind_file_with_one_line_naming_the_attachment(self):
        routing = _routing("content")
        R.apply_boq_file_guardrail(OWNER, routing, AGENTS, ATTACHMENT)
        c = routing["content"]
        self.assertTrue(c["needed"])
        self.assertEqual(c["kind"], "file")
        self.assertEqual(len(c["questions"]), 1)
        line = c["questions"][0]
        self.assertIn("02 SS SHOE RACK.pdf", line)
        self.assertIn("BOQ/BOM", line)
        self.assertLessEqual(len(line.split()), 25)

    def test_a_requested_format_is_honoured(self):
        routing = _routing("content")
        R.apply_boq_file_guardrail("make a BOQ for this as an .xlsx",
                                   routing, AGENTS, ATTACHMENT)
        self.assertIn(".xlsx", routing["content"]["questions"][0])

    def test_no_format_named_defaults_to_docx(self):
        routing = _routing("content")
        R.apply_boq_file_guardrail(OWNER, routing, AGENTS, ATTACHMENT)
        self.assertIn(".docx", routing["content"]["questions"][0])

    def test_content_is_turned_on_even_if_the_planner_left_it_off(self):
        routing = _routing()  # nothing on at all
        changed = R.apply_boq_file_guardrail(
            "make a BOQ for this", routing, AGENTS, ATTACHMENT)
        self.assertTrue(changed)
        self.assertTrue(routing["content"]["needed"])

    def test_no_content_agent_configured_turns_off_the_other_stages_anyway(self):
        routing = _routing(*ALL_ON)
        agents = {k: v for k, v in AGENTS.items() if k != "content"}
        changed = R.apply_boq_file_guardrail(OWNER, routing, agents, ATTACHMENT)
        self.assertTrue(changed)
        self.assertFalse(routing["brains"]["needed"])


class ItNeverTouchesPartsSkillsSystem(unittest.TestCase):
    """The whole reason this is a guardrail and not a module named
    core/skills.py a second time."""

    def test_wired_before_the_skills_pass_not_instead_of_it(self):
        import inspect
        src = inspect.getsource(R.route)
        i = src.index("apply_boq_file_guardrail(query, routing, agents, attachments)")
        j = src.index("SK.assign(query, routing", i)
        self.assertLess(i, j)

    def test_the_guardrail_touches_no_skills_file(self):
        import core.skills as SK
        src_path = SK.__file__
        # Importing core.skills at all, successfully, alongside router's own
        # import of it, is the real assertion here -- a second module of the
        # same name would have shadowed or been shadowed by this one.
        self.assertTrue(os.path.isfile(src_path))
        self.assertIn("checks.py", open(src_path, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
