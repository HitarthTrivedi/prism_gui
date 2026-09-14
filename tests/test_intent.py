"""The person's own words have to reach the tool that does the work.

Prism expands a request into a professional task brief, and the router writes
each stage prompt FROM that brief. The router is handed the raw request and
told it wins on scope — but the stage prompts it produces were only as good as
what it chose to carry across, and the agents never saw the original at all.

The run that found this: a customer asked for a reel about "Consiz, a mouse
with a middle button that summarises whatever you have selected and lets you
ask questions about it". The brief came back as "showcase the mouse,
demonstrate its features, explain its benefits". Every mechanical fact — the
button, the selecting, the summarising, the asking — gone. Claude then wrote a
genuinely good script about a generic productivity mouse, because a generic
productivity mouse is all it had ever been told about.

Nothing downstream can catch that. A summary that drops the one fact the whole
video is about still reads perfectly well, so every later stage compounds the
error confidently. The only fix is to stop losing it in the first place.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import automation as AU  # noqa: E402

CONSIZ = (
    "you have to make a minimal, aesthetic, informative reel describing the "
    "features and working of a mouse called as consiz, which have a button in "
    "middle, what it does whenever any user selects anything on his desktop, "
    "web browser, file, folder, mails etc — he selects it as anyone selects "
    "normally but when he presses that middle button it actually summarizes "
    "the texts, file, folder selected by the user, provides information about "
    "it, and also asks the user if he wants to ask some query about it. dont "
    "make this reel look AI ish, use some sophisticated template with good "
    "fonts"
)


class TheWordsSurvive(unittest.TestCase):

    def test_the_request_is_carried_verbatim(self):
        block = AU._intent_block(CONSIZ)
        for fact in ("button in middle", "summarizes", "ask some query",
                     "dont make this reel look AI ish", "sophisticated template"):
            self.assertIn(fact, block, f"lost: {fact}")

    def test_the_words_come_bare(self):
        """Round 31 (owner, 11 Sep 2026): the same request typed to Claude by
        hand as one line got the BOQ in a fraction of the tokens; Prism's
        message, with its banner and its paragraph on why the words above
        win, exhausted the chat. The tools need the words, not a label
        saying whose they are or a rule on how to rank them."""
        self.assertEqual(AU._intent_block(CONSIZ), CONSIZ + "\n\n")
        low = AU._intent_block(CONSIZ).lower()
        for gone in ("in their own words", "the words above win",
                     "engineered summary", "must survive", "---"):
            self.assertNotIn(gone, low)

    def test_an_empty_request_adds_nothing(self):
        """A stage with no user text behind it — an internal retry — must not
        get an empty banner with nothing under it."""
        self.assertEqual(AU._intent_block(""), "")
        self.assertEqual(AU._intent_block("   "), "")

    def test_a_very_long_request_is_capped_but_marked(self):
        """Truncation is survivable; silent truncation is not."""
        block = AU._intent_block("x" * 9000)
        self.assertLess(len(block), 4000)
        self.assertIn("[…]", block)

    def test_a_normal_request_is_never_truncated(self):
        """The Consiz prompt is about as long as a real one gets, and the
        mechanism was in its last third — a tight cap would have cut off the
        very sentences this exists to protect."""
        self.assertNotIn("[…]", AU._intent_block(CONSIZ))


class WiredIntoEveryStage(unittest.TestCase):
    """The block is worthless if it is not actually prepended."""

    def _run_source(self) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "prism_terminal", "core", "automation.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_run_builds_the_context_from_it(self):
        tree = ast.parse(self._run_source())
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        called = {n.func.id for n in ast.walk(run)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_intent_block", called,
                      "run() never builds the intent block — the person's own "
                      "words do not reach any agent")

    def test_it_comes_before_the_attachments(self):
        """Order is the point. A long prompt gets skimmed from the top, and
        this is the part that must not be the bit that gets skimmed past."""
        src = self._run_source()
        i = src.index("context = _intent_block(query)")
        j = src.index("context += F.context_block(attachments", i)
        self.assertLess(i, j)

    def test_the_cap_is_generous_enough_for_a_real_request(self):
        """A tight cap would reintroduce the bug quietly: the Consiz mechanism
        sat in the last third of the sentence."""
        self.assertGreaterEqual(AU._MAX_INTENT_CHARS, len(CONSIZ))


if __name__ == "__main__":
    unittest.main()
