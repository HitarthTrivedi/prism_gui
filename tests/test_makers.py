"""A tool that builds the thing is briefed to build it.

The owner's Canva run of 10 Sep, from the prompt Canva received: "Produce
the final deck in plain-text slide format ready for import into Gamma.app
... Do NOT generate actual PPT files". Canva obeyed and typed the outline
back. The stage prompt had been written for a chat tool, and it named the
wrong tool.

Pinned here:
  · the registry says what each maker builds (`makes`), and chat tools say
    nothing;
  · the router is told, per tool, and given a rule to brief makers to BUILD
    -- only when a maker is in the plan;
  · the engine opens a maker's stage with a plain brief that sets aside any
    text-shaped ask below it, reads the context the human way, and never
    asks a maker for a handoff section.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import agents as A  # noqa: E402
from core import automation as AU  # noqa: E402
from core import router as R  # noqa: E402


class TheRegistrySaysWhatEachToolBuilds(unittest.TestCase):

    def test_deck_image_video_and_app_tools_are_makers(self):
        for name in ("Canva", "Gamma.app", "Tome", "Midjourney", "Runway",
                     "ElevenLabs", "v0.dev"):
            with self.subTest(tool=name):
                self.assertTrue(A.is_maker(A.AGENT_REGISTRY[name]), name)
                self.assertTrue(A.AGENT_REGISTRY[name]["makes"].strip())

    def test_chat_and_search_tools_are_not(self):
        for name in ("ChatGPT", "Claude", "Perplexity", "Kimi 2.6", "Apollo",
                     "Prism Reel", "NotebookLM"):
            with self.subTest(tool=name):
                self.assertFalse(A.is_maker(A.AGENT_REGISTRY[name]), name)

    def test_canva_makes_an_editable_design(self):
        self.assertIn("editable Canva design", A.AGENT_REGISTRY["Canva"]["makes"])


class TheRouterBriefsAMakerToBuild(unittest.TestCase):

    def test_the_rule_appears_only_when_a_maker_is_in_the_plan(self):
        self.assertEqual(R._maker_rule({"brains": "ChatGPT", "content": "Claude"}), "")
        rule = R._maker_rule({"brains": "ChatGPT", "presentation": "Canva"})
        self.assertIn("MAKER TOOLS (Canva)", rule)
        self.assertIn("Never ask for \"plain text\"", rule)
        self.assertIn("do not generate", rule)
        self.assertIn("Name the tool actually assigned to the stage", rule)

    def test_the_tool_line_says_what_it_makes(self):
        lines = R._stage_lines({"presentation": "Canva", "brains": "ChatGPT"}, [])
        self.assertIn("MAKES: an editable Canva design", lines)
        self.assertNotIn("ChatGPT: general intelligence" + " MAKES", lines)

    def test_the_rule_is_wired_into_the_planner_prompt(self):
        src = inspect.getsource(R.build_prompt)
        self.assertIn("maker_block = _maker_rule(agents)", src)
        self.assertIn("{maker_block}", src)


class TheEngineOpensAMakersStageWithABrief(unittest.TestCase):

    def test_the_brief_names_the_tool_and_sets_text_asks_aside(self):
        brief = AU._maker_brief("Canva", A.AGENT_REGISTRY["Canva"])
        self.assertTrue(brief.startswith("You are Canva, and what I need from you is "))
        self.assertIn("Build it here, in this tool", brief)
        self.assertIn("plain text", brief)
        self.assertIn("does not apply to you: build it", brief)
        self.assertIn("say so in one line", brief)

    def test_a_chat_tool_gets_no_brief(self):
        self.assertEqual(AU._maker_brief("ChatGPT", A.AGENT_REGISTRY["ChatGPT"]), "")

    def test_a_maker_reads_the_context_the_human_way(self):
        canva = A.AGENT_REGISTRY["Canva"]
        self.assertTrue(AU._context_header(canva, "content").startswith(
            "Here's what I've got so far"))
        self.assertIn("With that in mind", AU._context_footer(canva))
        chatgpt = A.AGENT_REGISTRY["ChatGPT"]
        self.assertIn("Context from the previous pipeline stage",
                      AU._context_header(chatgpt, "content"))

    def test_a_maker_is_never_asked_for_a_handoff_section(self):
        closing = AU._maker_handoff()
        self.assertIn("What you build is what is collected", closing)
        self.assertNotIn("HANDOFF FOR", closing)
        src = inspect.getsource(AU.run)
        self.assertIn("handoff = _maker_handoff()", src)

    def test_the_brief_goes_first_on_the_first_prompt_and_into_the_canva_runner(self):
        src = inspect.getsource(AU.run)
        self.assertIn("full_prompt = _maker_brief(agent_name, agent_cfg) + full_prompt", src)
        self.assertIn("_maker_brief(agent_name, agent_cfg)\n                                         + context", src)


if __name__ == "__main__":
    unittest.main()
