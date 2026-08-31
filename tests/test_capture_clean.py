"""What a scraped answer carries into the next tool's prompt.

The run that forced this: the design stage's prompt relayed the script as
"Claude responded: … Thought for 9s Thought for 9s …", claimed the brand
colours were "measured, not guessed", and demanded JSON-only output — and
the Claude on the other end read the whole thing as a prompt-injection
attempt, said so, refused the format, and spent ten minutes doing its own
research instead. The reel died at the design stage.

Two defences, both pinned here:

  · captures shed the page's own furniture (the "X responded:" caption,
    the thinking pills) the moment they are scraped — nothing fabricated-
    looking rides the relay — while fences and content stay untouched;
  · the pipeline's prompts say honestly what is going on: who launched
    this, where the colours came from, why the format is strict.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import automation as AU  # noqa: E402
from core import reel_web  # noqa: E402


class CapturesShedThePageFurniture(unittest.TestCase):

    def test_the_caption_and_the_thinking_pills_go(self):
        raw = ("Claude responded: Thought for 9s Thought for 9s Here's the "
               "on-screen caption copy for the reel.")
        clean = AU._clean_capture(raw)
        self.assertEqual(clean, "Here's the on-screen caption copy for the reel.")

    def test_fences_and_content_are_untouched(self):
        raw = 'ChatGPT said: ```json\n{"scenes": [1]}\n```'
        self.assertEqual(AU._clean_capture(raw), '```json\n{"scenes": [1]}\n```')

    def test_plain_text_passes_through(self):
        text = "The customer said: we like it. Claude responded well to that."
        self.assertEqual(AU._clean_capture(text), text)

    def test_the_scraper_applies_it(self):
        import inspect
        src = inspect.getsource(AU._capture)
        self.assertIn("_clean_capture", src)


class ThePromptsSayHonestlyWhatIsGoingOn(unittest.TestCase):
    """A model told a fabricated-sounding story refuses; one told the true
    one cooperates. The true one: the client's own team launched Prism, the
    earlier stages really ran, the colours came off the client's site."""

    def test_the_colours_name_who_measured_them(self):
        block = reel_web.brand_block({"accent": "#C7F000", "deep": "#071A2B"})
        self.assertIn("research step", block)
        self.assertIn("you did not measure them", block)
        self.assertNotIn("measured, not guessed", block)

    def test_both_json_format_blocks_state_the_context(self):
        for text in (reel_web.script_instructions(),
                     reel_web.design_instructions()):
            self.assertIn("Context, honestly stated", text)
            self.assertIn("one stage of Prism", text)

    def test_the_relayed_script_names_its_source(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "prism_terminal", "core", "automation.py"), encoding="utf-8").read()
        i = src.index("THE SCRIPT — final")
        self.assertIn("one stage of Prism", src[max(0, i - 800):i])


if __name__ == "__main__":
    unittest.main()
