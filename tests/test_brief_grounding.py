"""A reel request must not come back carrying a PDF, a budget and attachments
nobody gave.

On 21 Sep 2026 two of the owner's three reel tasks were sent to ChatGPT with
a quote-and-price document rulebook (prices with basis, GST, exclusions,
validity dates) typed into the storyboard step. Nothing in the request asked
for a document. The chain, and the guard on each link:

  1. the "task brief" pass -- told to fill in the deliverable, the constraints
     and "things the user didn't say" -- invented ".docx (script) + .pdf
     (storyboard)", a Rs 12,000 budget and "the attached cultural study
     excerpts" (nothing was attached; the request only mentioned a study);
  2. the planner wrote a "storyboard PDF" step from that brief and named the
     pdf-document skill for it;
  3. Prism typed that skill into the ChatGPT message itself.

Nothing here reaches Groq: groq_chat is replaced.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import config as C  # noqa: E402
from core import router as R  # noqa: E402
from core import skills as SK  # noqa: E402

# The shape of the owner's real request: a reel, a concept, and a sentence that
# says tribal life "is documented through cultural studies" -- the word
# "documented" and the mention of a study are what the brief step turned into a
# document deliverable and an attachment.
REEL = (
    "i want a reel on basis of the prompt i have given below :\n\n"
    "Theme: when there was no plastic, how was cleanliness?\n\n"
    "You could show a Timli/Adivasi village scene with two time periods: "
    "before and today, ending with the SBM message.\n\n"
    "This would fit very well with Timli visuals + tribal lifestyle + Swachhta "
    "without falsely claiming that a specific historical community followed "
    "particular practices unless we have evidence. Historical tribal life in "
    "South Gujarat is documented through cultural studies, including "
    "traditions, material culture, folk songs and dances."
)
GOOD_PLAN = json.dumps({"content": {"needed": True, "questions": ["x"]}})
CFG = {"api_key": "k", "agents": {"content": "ChatGPT"}}
ATTACHED = [{"name": "study-excerpts.pdf", "kind": "pdf",
             "path": "C:/tmp/study-excerpts.pdf"}]


class _Groq:
    """Answers every call with the same reply and remembers the prompts."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts = []

    def __call__(self, api_key, model, prompt, **kw):
        self.prompts.append(prompt)
        return self.reply


class TheBriefIsToldNotToEnlargeTheRequest(unittest.TestCase):

    def _prompt(self, query=REEL, profile="", attachments=None) -> str:
        groq = _Groq("- GOAL: a reel")
        with mock.patch.object(R, "groq_chat", groq):
            R.enrich_query(query, profile, "k", "m", attachments)
        self.assertEqual(len(groq.prompts), 1)
        return groq.prompts[0]

    def test_it_may_sharpen_the_request_but_never_enlarge_it(self):
        self.assertIn("NEVER ENLARGES IT", self._prompt())

    def test_a_gap_is_written_as_not_specified_and_not_guessed(self):
        p = self._prompt()
        self.assertIn('"not specified"', p)
        self.assertIn("not \".pdf\"", p)

    def test_a_second_deliverable_beside_the_one_asked_for_is_forbidden(self):
        p = self._prompt()
        self.assertIn("second deliverable", p)
        self.assertIn("storyboard PDF", p)

    def test_implicit_needs_stay_inside_the_requested_deliverable(self):
        p = self._prompt()
        self.assertIn("INSIDE the requested deliverable", p)
        self.assertNotIn("things the user didn't say but a professional "
                         "would include", p)

    def test_constraints_are_only_what_the_request_states(self):
        self.assertIn('only what the request states', self._prompt())

    def test_with_nothing_attached_it_says_so(self):
        """The request only MENTIONS a study; nothing is attached."""
        p = self._prompt()
        self.assertIn("Files the user attached: none.", p)
        self.assertIn("does not make it an attachment", p)

    def test_attached_files_are_named(self):
        p = self._prompt(attachments=ATTACHED)
        self.assertIn("Files the user attached: study-excerpts.pdf.", p)
        self.assertNotIn("attached: none", p)

    def test_junk_in_the_attachment_list_does_not_raise(self):
        p = self._prompt(attachments=[None, "x", {}, {"name": ""}, 5])
        self.assertIn("Files the user attached: none.", p)

    def test_the_raw_request_still_goes_to_the_model_word_for_word(self):
        self.assertIn(REEL, self._prompt())

    def test_the_profile_line_is_kept(self):
        p = self._prompt(profile="a school in Vadodara")
        self.assertIn('The user describes themselves as: "a school in '
                      'Vadodara".', p)

    def test_the_sections_the_planner_reads_are_all_still_there(self):
        p = self._prompt()
        for heading in ("GOAL:", "DELIVERABLE & FORMAT:", "AUDIENCE & TONE",
                        "SCOPE:", "CONSTRAINTS & GIVENS:", "QUALITY BAR:",
                        "IMPLICIT NEEDS:"):
            self.assertIn(heading, p)

    def test_a_failure_still_returns_an_empty_brief(self):
        """Enrichment is a nicety: routing works without it."""
        with mock.patch.object(R, "groq_chat", side_effect=RuntimeError("x")):
            self.assertEqual(R.enrich_query(REEL, "", "k", "m"), "")

    def test_the_brief_comes_back_trimmed(self):
        with mock.patch.object(R, "groq_chat", _Groq("  - GOAL: a reel \n")):
            self.assertEqual(R.enrich_query(REEL, "", "k", "m"),
                             "- GOAL: a reel")


class TheRouteHandsTheBriefTheRealAttachments(unittest.TestCase):

    def _asked_with(self, attachments):
        enrich = mock.patch.object(R, "enrich_query", return_value="")
        with enrich as brief, \
                mock.patch.object(R, "groq_chat", _Groq(GOOD_PLAN)):
            R.route("make a reel", CFG, attachments=attachments)
        args, kwargs = brief.call_args
        return kwargs.get("attachments", args[4] if len(args) > 4 else None)

    def test_the_files_the_person_attached_reach_the_brief_step(self):
        self.assertEqual(self._asked_with(ATTACHED), ATTACHED)

    def test_no_files_means_the_brief_step_is_told_none(self):
        self.assertFalse(self._asked_with(None))


class ThePlannerIsToldTheBriefNeverAdds(unittest.TestCase):

    def test_the_brief_is_context_not_extra_orders(self):
        p = R.build_prompt("make a reel", "", {"content": "ChatGPT"}, None,
                           brief="- GOAL: a reel")
        self.assertIn("- GOAL: a reel", p)
        self.assertIn("never adds to it", p)
        self.assertIn("ignore that part", p)

    def test_no_brief_no_block(self):
        p = R.build_prompt("make a reel", "", {"content": "ChatGPT"}, None)
        self.assertNotIn("TASK BRIEF", p)


class ADocumentRulebookNeedsARequestForADocument(unittest.TestCase):

    def setUp(self):
        SK.reload()

    def _plan(self, *skills):
        return {"content": {"needed": True, "kind": "file",
                            "questions": ["Create a storyboard PDF."],
                            "skills": list(skills)}}

    def test_the_shipped_pdf_skill_is_marked(self):
        self.assertIs(SK.get("pdf-document").only_when_asked, True)

    def test_the_marked_skill_has_triggers_or_it_could_never_be_attached(self):
        for s in SK.catalog().values():
            if s.only_when_asked:
                with self.subTest(skill=s.key):
                    self.assertTrue(s.triggers)

    def test_a_pdf_rulebook_the_planner_named_is_left_off_a_reel_request(self):
        routing = self._plan("pdf-document")
        SK.assign(REEL, routing, ["content"])
        self.assertNotIn("pdf-document", routing["content"]["skills"])

    def test_the_word_documented_is_not_a_request_for_a_document(self):
        self.assertIn("documented", REEL)
        routing = self._plan("pdf-document")
        chosen = SK.assign(REEL, routing, ["content"])
        self.assertNotIn("pdf-document", chosen.get("content", []))

    def test_the_skill_is_kept_when_the_person_asks_for_a_pdf(self):
        routing = self._plan("pdf-document")
        SK.assign("make a reel and a one-pager pdf brochure about it",
                  routing, ["content"])
        self.assertEqual(routing["content"]["skills"], ["pdf-document"])

    def test_the_skill_is_kept_when_the_person_asks_for_a_word_document(self):
        routing = self._plan("pdf-document")
        SK.assign("write a proposal for the bank", routing, ["content"])
        self.assertEqual(routing["content"]["skills"], ["pdf-document"])

    def test_the_planners_other_picks_are_untouched(self):
        routing = self._plan("scene")
        SK.assign(REEL, routing, ["content"])
        self.assertEqual(routing["content"]["skills"], ["scene"])

    def test_a_skill_that_is_not_marked_is_still_kept_without_a_trigger(self):
        """The rule is opt-in per skill: the router's judgement stands for
        every skill that does not ask to be gated."""
        routing = {"presentation": {"needed": True,
                                    "skills": ["slide-deck"]}}
        SK.assign("investor pitch for the bank", routing, ["presentation"])
        self.assertEqual(routing["presentation"]["skills"], ["slide-deck"])

    def test_when_the_pick_is_dropped_the_persons_own_words_still_decide(self):
        routing = self._plan("pdf-document")
        SK.assign("storyboard a 20 second reel for the launch", routing,
                  ["content"])
        self.assertEqual(routing["content"]["skills"], ["scene"])

    def test_dropping_it_is_said_in_the_log(self):
        routing = self._plan("pdf-document")
        with mock.patch.object(SK.ui, "info") as said:
            SK.assign(REEL, routing, ["content"])
        text = " ".join(str(c.args[0]) for c in said.call_args_list)
        self.assertIn("pdf-document", text)
        self.assertIn("left off", text)

    def test_a_stage_that_is_not_running_gets_nothing_either_way(self):
        routing = {"content": {"needed": False, "skills": ["pdf-document"]}}
        SK.assign(REEL, routing, ["content"])
        self.assertEqual(routing["content"]["skills"], [])

    def test_the_flag_reads_the_ways_a_person_writes_yes_and_no(self):
        for text in ("true", "True", "yes", "on", "1", True):
            with self.subTest(text=text):
                self.assertIs(SK._as_flag(text), True)
        for text in ("false", "No", "off", "0", False):
            with self.subTest(text=text):
                self.assertIs(SK._as_flag(text), False)
        for text in (None, "", "maybe", []):
            with self.subTest(text=text):
                self.assertIsNone(SK._as_flag(text))


class ACustomerOverrideKeepsOrClearsTheGate(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(C, "CONFIG_DIR", self._tmp.name)
        self._patch.start()
        self.user = os.path.join(self._tmp.name, "skills")

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()
        SK.reload()

    def _write(self, text: str):
        folder = os.path.join(self.user, "pdf-document")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(text)

    def test_a_body_only_override_keeps_the_gate(self):
        self._write("Our documents always open with a one-line summary.")
        SK.reload()
        s = SK.get("pdf-document")
        self.assertTrue(s.overridden)
        self.assertIs(s.only_when_asked, True)

    def test_a_frontmatter_that_omits_the_key_keeps_the_gate(self):
        self._write("---\ntitle: House documents\n---\nOne-line summary first.")
        SK.reload()
        self.assertIs(SK.get("pdf-document").only_when_asked, True)

    def test_a_customer_can_switch_the_gate_off_on_purpose(self):
        self._write("---\nonly_when_asked: false\n---\nOne-line summary first.")
        SK.reload()
        self.assertIs(SK.get("pdf-document").only_when_asked, False)
        routing = {"content": {"needed": True, "skills": ["pdf-document"]}}
        SK.assign(REEL, routing, ["content"])
        self.assertEqual(routing["content"]["skills"], ["pdf-document"])

    def test_a_skill_of_their_own_is_not_gated_unless_it_says_so(self):
        folder = os.path.join(self.user, "house-tone")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\ntitle: House tone\ndescription: How this company "
                    "writes to its customers.\nstages: [content]\n"
                    "triggers: [letter]\n---\nShort sentences.")
        SK.reload()
        self.assertIsNone(SK.get("house-tone").only_when_asked)


if __name__ == "__main__":
    unittest.main()
