"""Canva is opt-in, and staying that way.

The bug: with the Canva app connected to ChatGPT, every visual and
presentation turn came back as a flat Canva template — including "da Vinci
sipping a cup of Wagh Bakri chai", which needs a rendered illustration and
cannot be a stock layout. Routing an ordinary image request through Canva
loses the picture that was asked for.

So the editable-design path now has to be something the CUSTOMER asked for,
in their own words. Two halves worth testing separately:

  · an ordinary request must NOT go to Canva, and must be told so explicitly —
    silence is not enough, because ChatGPT reaches for a connected app given
    any chance at all;
  · a request that does ask for something editable must still get it.

The trigger is matched against the user's original task text and never against
the router's rewrite of it. A router paraphrasing a brief must not be able to
opt somebody into Canva — that is how this broke the first time.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import agents as A  # noqa: E402
from core.automation import _resolve_suffix  # noqa: E402

CHATGPT = A.AGENT_REGISTRY["ChatGPT"]

# The prompt that produced the complaint.
DA_VINCI = ("you have to make a post like da vinci is sipping a cup of tea "
            "from 'wagh bakri chai', its like a commercial post, it should "
            "show the packaging of wagh bakri chai")


def route(query: str, stage: str = "visual") -> str:
    """'canva' | 'direct' | 'none' — which way the switch fell."""
    suffix = _resolve_suffix(CHATGPT, stage, query)
    if not suffix:
        return "none"
    return "direct" if "Do NOT route this through the Canva app" in suffix \
        else "canva"


class NotAsked(unittest.TestCase):
    """The default. Most image requests want a rendered picture."""

    def test_the_da_vinci_post_renders_instead_of_templating(self):
        self.assertEqual(route(DA_VINCI), "direct")

    def test_ordinary_image_requests_do_not_go_to_canva(self):
        for query in ("make an instagram post for our new product launch",
                      "create artwork for the diwali campaign",
                      "a hero image for the website",
                      "make a poster about our new CNC machine"):
            self.assertEqual(route(query), "direct", query)

    def test_the_refusal_is_explicit_not_merely_absent(self):
        """Saying nothing leaves a connected Canva app free to take over —
        which is exactly what happened. It has to be told not to."""
        suffix = _resolve_suffix(CHATGPT, "visual", DA_VINCI)
        self.assertTrue(suffix, "an ordinary request must still get direction")
        self.assertIn("Do NOT route this through the Canva app", suffix)

    def test_an_ordinary_deck_is_not_a_canva_deck(self):
        self.assertEqual(route("make a deck about Q3 results",
                               "presentation"), "direct")


class Asked(unittest.TestCase):
    """The opt-in still works — that was the point of connecting Canva."""

    def test_naming_canva_switches_it_on(self):
        self.assertEqual(route("make a post for wagh bakri chai in canva"),
                         "canva")

    def test_asking_to_edit_it_later_switches_it_on(self):
        for query in ("design a brochure the client can edit later",
                      "an editable design for the sales team",
                      "make a template we can reuse",
                      "a post so we can edit the copy afterwards"):
            self.assertEqual(route(query), "canva", query)

    def test_an_editable_deck_switches_it_on(self):
        self.assertEqual(route("build me an editable deck for the board",
                               "presentation"), "canva")

    def test_the_link_is_still_demanded_back(self):
        """An editable design nobody can open is worth less than a flat
        image, so the link is the deliverable.

        It moved: the first prompt now asks only for the picture, and the
        follow-up asks Canva to convert it. Same requirement, second message.
        """
        self.assertIn("CANVA LINK:", A._CANVA_FOLLOWUP)

    def test_the_first_prompt_no_longer_asks_canva_to_compose(self):
        """The change this file exists to defend. Asking for the image AND
        the Canva design in one prompt makes Canva BUILD the image — a stock
        template where DALL-E would have rendered the scene — so the customer
        had to choose between a good picture and an editable one."""
        suffix = _resolve_suffix(CHATGPT, "visual", "make it in canva")
        low = suffix.lower()
        self.assertIn("highest quality", low)
        self.assertIn("do not route this through canva", low)
        self.assertNotIn("build this as a real, editable canva", low)

    def test_both_branches_now_ask_for_the_same_picture(self):
        """Asked-for-Canva and not-asked-for-Canva both generate at full
        quality. They differ in what happens AFTER, not in the artwork."""
        asked = _resolve_suffix(CHATGPT, "visual", "make it in canva")
        plain = _resolve_suffix(CHATGPT, "visual", "make me a poster")
        for text in (asked, plain):
            self.assertIn("highest quality", text.lower())

    def test_the_followup_addresses_the_canva_app(self):
        """"@canva" is how ChatGPT routes a message to a connected app. Without
        it the model answers about Canva instead of using it."""
        self.assertTrue(A._CANVA_FOLLOWUP.lstrip().startswith("@canva"))

    def test_the_followup_points_at_the_image_above_it(self):
        """It must convert the artwork already in the thread, not invent a
        new design from the words — inventing is the template failure."""
        low = A._CANVA_FOLLOWUP.lower()
        self.assertIn("image above", low)

    def test_a_missing_canva_app_has_a_defined_answer(self):
        """Otherwise the model writes a paragraph apologising, and that
        paragraph gets captured as if it were the deliverable."""
        self.assertIn("CANVA LINK: none", A._CANVA_FOLLOWUP)

    def test_case_and_wording_do_not_matter(self):
        self.assertEqual(route("Make This In CANVA Please"), "canva")


class Scope(unittest.TestCase):
    def test_only_the_stages_that_make_artwork_are_switched(self):
        """ChatGPT's thinking and writing turns must not be told anything
        about design tools."""
        for stage in ("brains", "content", "research", "development"):
            self.assertEqual(_resolve_suffix(CHATGPT, stage, "use canva"), "")

    def test_the_trigger_reads_the_users_words_not_the_routers(self):
        """_resolve_suffix is handed the original task text. If it were ever
        handed the router's stage question instead, a paraphrase mentioning
        'editable' would silently opt the customer in."""
        self.assertEqual(route("make a poster of a tiger"), "direct")
        self.assertEqual(route(""), "direct")

    def test_a_plain_string_suffix_still_applies_unconditionally(self):
        """Other agents may want an always-on suffix; the switch is opt-in
        for the registry too."""
        cfg = {"stage_suffix": {"visual": "always this"}}
        self.assertEqual(_resolve_suffix(cfg, "visual", "anything"),
                         "always this")

    def test_an_agent_with_no_suffix_gets_nothing(self):
        self.assertEqual(_resolve_suffix({}, "visual", "use canva"), "")
        self.assertEqual(
            _resolve_suffix(A.AGENT_REGISTRY["Claude"], "visual", "x"), "")

    def test_a_malformed_entry_is_ignored_rather_than_crashing_a_run(self):
        self.assertEqual(_resolve_suffix({"stage_suffix": {"visual": 42}},
                                         "visual", "x"), "")


class RouterNudge(unittest.TestCase):
    """The suffix is only half of it. The registry's `specialty` is what the
    ROUTER reads when it decides what to ask for, and it used to recommend
    Canva unprompted."""

    def test_the_specialty_leads_with_rendered_images(self):
        spec = A.AGENT_REGISTRY["ChatGPT"]["specialty"].lower()
        self.assertIn("dall", spec)

    def test_the_specialty_tells_the_router_to_wait_to_be_asked(self):
        spec = A.AGENT_REGISTRY["ChatGPT"]["specialty"].lower()
        self.assertIn("only", spec)
        self.assertIn("template", spec)   # names the cost of getting it wrong

    def test_wants_canva_agrees_with_the_resolver(self):
        """Two doors to one decision; they must not drift."""
        for query in (DA_VINCI, "make it in canva", "an editable post",
                      "a poster of a tiger", ""):
            expected = "canva" if A.wants_canva(query) else "direct"
            self.assertEqual(route(query), expected, query)




class SelfDirectingTools(unittest.TestCase):
    """LAZYCOOK does its own research loop. Prism's house style switched it off.

    "Perform ONLY the task above — nothing more" reads to a tool that runs
    Generate → Analyze → Optimize → Validate as an instruction to stop after
    the first pass. It then answers in one shot and comes back thinner than
    the plain search tool it was chosen over — which looks like Prism picking
    the wrong tool, when it was Prism asking the wrong way.
    """

    def test_lazycook_is_marked_self_directing(self):
        self.assertEqual(A.AGENT_REGISTRY["LAZYCOOK"].get("prompt_style"),
                         "natural")

    def test_ordinary_chat_tools_are_unchanged(self):
        """The strict rules are what keep a ten-stage run coherent — they must
        stay on for everything that is genuinely just a chat model."""
        for name in ("Claude", "ChatGPT", "Perplexity"):
            self.assertIsNone(
                A.AGENT_REGISTRY[name].get("prompt_style"), name)

    def test_it_is_asked_rather_than_ordered(self):
        from core.automation import _natural_handoff
        text = _natural_handoff("Claude", final=False).lower()
        for bossy in ("strict pipeline rules", "perform only",
                      "nothing more", "your reader is another ai",
                      "do not build"):
            self.assertNotIn(bossy, text)

    def test_but_the_handoff_is_still_requested(self):
        """The pipeline cannot work without it — the next tool sees only this
        answer. Softening the tone must not drop the requirement."""
        from core.automation import _natural_handoff
        text = _natural_handoff("Claude", final=False)
        self.assertIn("HANDOFF FOR CLAUDE", text)

    def test_the_last_stage_is_not_asked_for_a_handoff(self):
        from core.automation import _natural_handoff
        text = _natural_handoff("", final=True)
        self.assertNotIn("HANDOFF FOR", text)
        self.assertIn("finished piece", text)

    def test_depth_is_actively_invited(self):
        from core.automation import _natural_handoff
        for final in (True, False):
            text = _natural_handoff("Claude", final=final).lower()
            self.assertTrue("deep" in text or "depth" in text,
                            "the whole point is to let it do its extra passes")

    def test_the_context_header_is_conversational_for_these_tools(self):
        from core.automation import _context_header
        lazy = A.AGENT_REGISTRY["LAZYCOOK"]
        claude = A.AGENT_REGISTRY["Claude"]
        self.assertNotIn("pipeline stage", _context_header(lazy, "research"))
        self.assertIn("pipeline stage", _context_header(claude, "research"))

    def test_the_router_is_told_to_stop_over_specifying(self):
        from core import router as R
        prompt = R.build_prompt("write about batteries", "",
                                {"research": "LAZYCOOK"})
        self.assertIn("SELF-DIRECTING", prompt)
        self.assertIn('Do NOT use the "Your ONLY task is:" opener', prompt)

    def test_the_rule_is_absent_when_no_such_tool_is_in_the_plan(self):
        """A rule about a tool that is not running is prompt budget spent for
        nothing, and one more thing for the router to weigh."""
        from core import router as R
        prompt = R.build_prompt("write about batteries", "",
                                {"research": "Perplexity"})
        self.assertNotIn("SELF-DIRECTING", prompt)

    def test_marking_a_new_tool_self_directing_needs_only_the_flag(self):
        from core import router as R
        self.assertIn("LAZYCOOK", R._self_directing_names())


class TheSecondPrompt(unittest.TestCase):
    """Generate the picture properly, then convert it. Nothing here opens a
    browser: _reask is swapped for a recorder."""

    def setUp(self):
        from core import automation as AU
        self.AU = AU
        self.asked = []
        self._real = AU._reask
        AU._reask = lambda drv, cfg, prompt, expect="": (
            self.asked.append(prompt) or self.reply)
        self.reply = ["CANVA LINK: https://canva.com/design/abc"]

    def tearDown(self):
        self.AU._reask = self._real

    def run_it(self, stage="visual", query="make it in canva",
               responses=("here is your image",)):
        return self.AU._make_editable(None, CHATGPT, stage, query,
                                      list(responses))

    def test_it_asks_canva_after_the_image_exists(self):
        out = self.run_it()
        self.assertEqual(len(self.asked), 1)
        self.assertTrue(self.asked[0].lstrip().startswith("@canva"))
        self.assertIn("CANVA LINK: https://canva.com/design/abc", out[-1])

    def test_the_image_is_kept_as_well_as_the_link(self):
        """Replacing the first answer with the link would throw away the
        artwork the customer actually asked for."""
        out = self.run_it(responses=("here is your image",))
        self.assertIn("here is your image", out[0])
        self.assertEqual(len(out), 2)

    def test_nothing_happens_unless_the_user_asked(self):
        self.run_it(query="make me a poster of a spring")
        self.assertEqual(self.asked, [])

    def test_only_the_stages_that_make_artwork(self):
        """A research answer cannot be opened in Canva, and asking would only
        confuse the tool."""
        for stage in ("research", "content", "brains", "development"):
            self.run_it(stage=stage)
        self.assertEqual(self.asked, [])

    def test_studio_internal_stages_are_left_alone(self):
        """Caught on the first real run. The Studio pipeline\'s design stage
        emits a JSON scene spec for Prism\'s own renderer, so asking Canva to
        "import the image above" pointed it at a CSS blob. Canva answered
        "none", and the turn was pure waste on a conversation that had just
        been asked twice for strict JSON."""
        for stage in ("design", "artwork"):
            self.run_it(stage=stage)
        self.assertEqual(self.asked, [])

    def test_a_machine_read_stage_is_never_interrupted(self):
        """Belt and braces for the same failure. A stage told to reply with
        ONLY a JSON object must not then be sent a chat message — it wastes a
        round trip and leaves prose where the parser looks for the spec."""
        self.AU._make_editable(None, CHATGPT, "visual", "make it in canva",
                               ["{...}"], machine_shaped=True)
        self.assertEqual(self.asked, [])

    def test_the_editable_stages_match_the_registry(self):
        """The suffix and the follow-up have to agree on which stages are in
        play. They drifted apart once already, and that drift WAS the bug."""
        from core.agents import AGENT_REGISTRY
        configured = set(AGENT_REGISTRY["ChatGPT"]["stage_suffix"])
        self.assertEqual(set(self.AU._EDITABLE_STAGES), configured)

    def test_it_does_not_ask_when_nothing_was_made(self):
        """With no image in the thread, Canva would invent a design from the
        words alone — which is exactly the template-instead-of-artwork
        failure this whole change removes."""
        self.run_it(responses=())
        self.assertEqual(self.asked, [])

    def test_a_disconnected_canva_app_does_not_pollute_the_output(self):
        """"CANVA LINK: none" is a status, not a deliverable. Appending it
        would hand the next stage a sentence about Canva instead of an
        image."""
        self.reply = ["CANVA LINK: none"]
        out = self.run_it()
        self.assertEqual(out, ["here is your image"])

    def test_a_silent_canva_leaves_the_image_intact(self):
        """The follow-up failing must never cost the picture that already
        worked."""
        self.reply = []
        out = self.run_it()
        self.assertEqual(out, ["here is your image"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
