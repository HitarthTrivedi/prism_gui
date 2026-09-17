"""Round 31 (owner, 11 Sep 2026): the message a tool gets from Prism core is
the person's own words, one line for the step, and at most four lines from
the step before. Nothing else.

The case: the same PDF, the same target (a BOQ for K J Pharmatech). Typed
to Claude by hand as one line with the file attached, the BOQ came back in
a fraction of the tokens. Sent through Prism, the message was a banner, a
paragraph on why the words win, the whole Perplexity research report, a
250-word role-play prompt and a hand-off rule sheet -- and the chat ran out
of tokens before the document existed. "AIs now are very understanding;
they don't need complex prompts, they need simple prompts."

Pinned here:

  · the person's words travel bare;
  · what travels from one step to the next is the HANDOFF block, at most
    four lines (every line for a tool with its own filter block);
  · the earlier tool is asked for exactly that -- a hand-off of at most
    four lines -- in one sentence, and the last step for the finished
    result in one sentence;
  · the planner is told one line of at most 25 words per step, on both
    the first plan and the rewrite for a confirmed plan;
  · the floor under a step with no prompt is one line.

Nothing here opens a browser or calls Groq.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import agents as A          # noqa: E402
from core import automation as AU     # noqa: E402
from core import router as R          # noqa: E402

REPORT = ("KJ PharmaTech (Projects) Pvt. Ltd. is a Vadodara company…\n"
          + "Section 3. Products.\n" * 40 +
          "HANDOFF FOR CLAUDE\n"
          "- Makarpura GIDC, Vadodara; SS cleanroom furniture incl. shoe racks\n"
          "- Drawing: SS shoe rack 600x900x300, mechanical lock\n"
          "\n"
          "- Grade, thickness, quantity are NOT on the drawing\n"
          "- Contact +91 99790 88855, info@kjpharmatech.com\n"
          "- Established 2007 (LinkedIn); entity incorporated 2025\n"
          "- Testimonials: Sunways Rohto, ITC Indivision\n")


class OnlyTheHandoffTravels(unittest.TestCase):

    def test_four_lines_under_the_heading_and_nothing_above_it(self):
        got = AU._handoff_of([REPORT])
        self.assertEqual(len(got.splitlines()), 4)
        self.assertTrue(got.startswith("- Makarpura"))
        self.assertIn("info@kjpharmatech.com", got)
        self.assertNotIn("Section 3", got)
        self.assertNotIn("Established 2007", got, "the fifth line is dropped")

    def test_the_last_heading_wins(self):
        text = "HANDOFF FOR CLAUDE\n- draft\n\nreal answer\n\nHANDOFF FOR CLAUDE\n- final"
        self.assertEqual(AU._handoff_of([text]), "- final")

    def test_a_tool_with_its_own_block_keeps_every_line(self):
        block = ("HANDOFF FOR APOLLO\nTITLES: CEO\nINDUSTRIES: pharma\n"
                 "LOCATIONS: Gujarat\nHEADCOUNT: 11-20\nKEYWORDS: cleanroom")
        self.assertIn("KEYWORDS: cleanroom", AU._handoff_of([block], lines=None))
        self.assertNotIn("KEYWORDS", AU._handoff_of([block]))

    def test_no_heading_falls_back_to_a_capped_tail(self):
        got = AU._handoff_of(["word " * 2000])
        self.assertLessEqual(len(got), AU._MAX_FORWARD_CHARS + 10)
        self.assertTrue(got.startswith("[…]"))
        self.assertLessEqual(AU._MAX_FORWARD_CHARS, 1500,
                             "the ceiling was 8,000 — that is the bug")

    def test_the_heading_is_read_through_markdown(self):
        for heading in ("## HANDOFF FOR CLAUDE", "**HANDOFF FOR CLAUDE**",
                        "Handoff for Claude:"):
            self.assertEqual(AU._handoff_of([f"x\n{heading}\n- a\n- b"]), "- a\n- b",
                             heading)

    def test_empty_in_empty_out(self):
        self.assertEqual(AU._handoff_of([]), "")
        self.assertEqual(AU._handoff_of(["", "   "]), "")

    def test_run_forwards_through_it(self):
        src = inspect.getsource(AU.run)
        self.assertIn("_handoff_of(prev_texts", src)
        self.assertNotIn("prev_text[-_MAX_FORWARD_CHARS:]", src,
                         "the whole previous answer must not travel")


class TheAskIsOneSentence(unittest.TestCase):

    def test_a_chat_tool_is_asked_for_four_lines_in_one_sentence(self):
        src = inspect.getsource(AU.run)
        self.assertIn("at most \"\n                    f\"{_MAX_HANDOFF_LINES} lines", src)
        for gone in ("WHERE THIS GOES", "Do the task above and", "This is the last step",
                     "no summary for a next step"):
            self.assertNotIn(gone, src)
        self.assertIn("else _FINAL_CLOSING", src)
        self.assertEqual(AU._FINAL_CLOSING,
                         "\n\nGive me the finished result — no questions back.")
        # On a file step contract.deliverable_line already says "give me the
        # finished result as a file", so the closing is just the other half.
        self.assertIn("handoff = _FINAL_CLOSING_AFTER_DELIVERABLE", src)
        self.assertEqual(AU._FINAL_CLOSING_AFTER_DELIVERABLE, "\n\nNo questions back.")

    def test_a_self_directing_tool_is_asked_the_same_way(self):
        text = AU._natural_handoff("Claude", final=False)
        self.assertIn("HANDOFF FOR CLAUDE", text)
        self.assertIn(f"at most {AU._MAX_HANDOFF_LINES} lines", text)
        self.assertLess(len(text), 260)
        self.assertLess(len(AU._natural_handoff("", final=True)), 160)

    def test_the_line_above_the_handoff_names_the_step_plainly(self):
        claude = A.AGENT_REGISTRY["Claude"]
        self.assertEqual(AU._context_header(claude, "research"),
                         "From the earlier step (Look things up):\n")
        self.assertEqual(AU._context_footer(claude), "\n\n")

    def test_the_whole_message_is_short(self):
        """The person's words, the attachment line, four lines from the
        earlier step, the step's one line, one closing sentence -- for the
        owner's BOQ request that is under 1,000 characters where the old
        message was over 9,000."""
        query = ("do research about K J pharmatech in vadodara, i have to make "
                 "a BOQ/BOM for the given PDF that they received. i want you to "
                 "make a proper documentation based on this as well")
        claude = A.AGENT_REGISTRY["Claude"]
        context = (AU._intent_block(query)
                   + AU._context_header(claude, "research")
                   + AU._handoff_of([REPORT])
                   + AU._context_footer(claude))
        line = "For this step: write the documentation and the BOQ/BOM from the PDF."
        closing = AU._FINAL_CLOSING_AFTER_DELIVERABLE
        message = AU._chat_header("do research about K J pharmatech", "content") \
            + context + line + closing
        self.assertLess(len(message), 1000, message)
        self.assertTrue(message.startswith("Prism · do research about K J pharmatech · Write it up\n\n"
                                           "do research about"))


class OnlyThisTasksFilesGoUp(unittest.TestCase):
    """One PDF attached in Prism; Claude's message went out with that PDF
    and a deck outline from a reel run days earlier (owner, 11 Sep 2026).
    claude.ai keeps an unsent draft, chips included. So every stage clears
    the composer's chips before its own upload."""

    class _Driver:
        def __init__(self, answer):
            self.answer, self.calls = answer, []

        def execute_script(self, js, *args):
            self.calls.append((js, args))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    def test_chips_are_removed_and_counted(self):
        d = self._Driver(2)
        with mock.patch.object(AU.ui, "warn") as warn:
            n = AU._clear_staged_attachments(d, {"textarea_selector": "textarea"}, "Claude")
        self.assertEqual(n, 2)
        self.assertEqual(d.calls[0][1], ("textarea",))
        self.assertIn("removed 2 attachment(s)", warn.call_args[0][0])
        js = d.calls[0][0]
        self.assertIn("remove|delete|dismiss|clear", js)
        self.assertIn("send|submit", js, "the send button is never a chip")

    def test_nothing_staged_says_nothing(self):
        with mock.patch.object(AU.ui, "warn") as warn:
            self.assertEqual(AU._clear_staged_attachments(self._Driver(0), {}), 0)
        warn.assert_not_called()

    def test_a_page_that_refuses_never_stops_the_stage(self):
        self.assertEqual(AU._clear_staged_attachments(self._Driver(RuntimeError("x")), {}), -1)
        self.assertEqual(AU._clear_staged_attachments(self._Driver("nonsense"), {}), -1)

    def test_run_clears_before_it_uploads(self):
        src = inspect.getsource(AU.run)
        i = src.index("_clear_staged_attachments(driver, agent_cfg, agent_name)")
        j = src.index("went_up = _upload_files(driver, agent_cfg, send_files, agent_name)")
        self.assertLess(i, j)


class ThePlannerWritesOneLine(unittest.TestCase):
    AGENTS = {"research": "Perplexity", "content": "Claude"}

    def test_the_first_plan(self):
        with mock.patch.object(R, "_tool_notes", return_value=""):
            p = R.build_prompt("make a BOQ", "", self.AGENTS)
        self.assertIn("ONE line of at most 25 words", p)
        for gone in ("40–80", "ROLE", "QUALITY BAR", "120–250", "HANDOFF FOR"):
            self.assertNotIn(gone, p)

    def test_the_rewrite_for_a_confirmed_plan(self):
        sent = []

        def fake(api_key, model, prompt, **kw):
            sent.append(prompt)
            raise RuntimeError("no groq in tests")
        steps = [("research", "Perplexity", ["x"]), ("content", "Claude", ["y"])]
        with mock.patch.object(R, "groq_chat", fake):
            R.brief_confirmed_plan("make a BOQ", {"api_key": "k"}, steps, {})
        # (a RuntimeError makes it retry once without json mode)
        self.assertGreaterEqual(len(sent), 1)
        self.assertIn("ONE line of at most\n  25 words", sent[0])
        for gone in ("HAND-OFF:", "FINAL STEP:", "PROMPT CRAFT", "120–250",
                     "Your ONLY task is", "HANDOFF FOR <NEXT TOOL"):
            self.assertNotIn(gone, sent[0])

    def test_the_floor_is_one_line_with_the_words_in_it(self):
        line = R.passthrough_prompt("draw a poster of a spring", "visual")
        self.assertEqual(len(line.splitlines()), 1)
        self.assertTrue(line.startswith("For this step:"))
        self.assertIn("draw a poster of a spring", line)
        self.assertNotIn("Your ONLY task", line)


if __name__ == "__main__":
    unittest.main()
