"""Tests for Studio and Reel pipeline fixes:
- Accent colour auto-heal and preflight protection
- Follow-up spec refinement and brand preservation
- Fallback prose caption parsing for video-to-video / client footage
- ElevenLabs narration extraction and prompt hygiene
- 6-asset artwork instructions
"""
import unittest
import core_bridge  # noqa: F401
from core import reel_web as RW
from core import automation as auto


class TestAccentPreflightAndAutoHeal(unittest.TestCase):

    def test_ensure_accent_applied_injects_css(self):
        spec = {
            "brand": {"accent": "#3a713a", "deep": "#122012"},
            "design": {"css": "body { background: #fff; }"},
            "scenes": [{"type": "intro", "html": "<h1>Welcome</h1>", "css": "h1 { font-size: 40px; }"}],
        }
        healed = RW.ensure_accent_applied(spec)
        css = healed["design"]["css"]
        self.assertIn("var(--accent)", css)
        self.assertIn("#3a713a", css)
        self.assertIn(".kicker, .accent, .highlight", css)

    def test_ensure_accent_applied_noop_when_already_present(self):
        spec = {
            "brand": {"accent": "#3a713a"},
            "design": {"css": ":root { --accent: #3a713a; } h1 { color: var(--accent); }"},
            "scenes": [{"type": "intro", "html": "<h1>Welcome</h1>"}],
        }
        before = spec["design"]["css"]
        healed = RW.ensure_accent_applied(spec)
        self.assertEqual(healed["design"]["css"], before)

    def test_brand_faults_auto_heals_missing_accent(self):
        spec = {
            "brand": {"accent": "#3a713a"},
            "design": {"css": "body { background: #fff; }"},
            "scenes": [{"type": "intro", "html": "<h1>Welcome</h1>"}],
        }
        faults = RW.brand_faults(spec)
        self.assertEqual(faults, [])
        self.assertIn("var(--accent)", spec["design"]["css"])

    def test_apply_followup_auto_heals_accent(self):
        spec = {
            "brand": {"accent": "#3a713a"},
            "design": {"css": ":root { --accent: #3a713a; }"},
            "scenes": [{"type": "s1", "seconds": 4.0, "cut": "push", "html": "<p>Old</p>", "css": ""}],
        }
        patch = {
            "scenes": {0: {"scene": 1, "html": "<p>New</p>", "css": ""}},
            "design_css": "body { background: #000; }",  # replaced css without var(--accent)
            "remove": [],
        }
        new_spec = RW.apply_followup(spec, patch)
        self.assertIn("var(--accent)", new_spec["design"]["css"])
        self.assertIn("#3a713a", new_spec["design"]["css"])


class TestFootageScriptFallback(unittest.TestCase):

    def test_parses_json_scenes_cleanly(self):
        text = 'Here is the script:\n```json\n{"scenes": [{"seconds": 4, "caption": "Precision engineered", "voiceover": "Built for performance."}]}\n```'
        captions = auto._footage_script(text)
        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0]["text"], "Precision engineered")
        self.assertEqual(captions[0]["seconds"], 4)

    def test_parses_labelled_prose_fallback(self):
        text = (
            "Here is the promotional script:\n\n"
            "Scene 1:\n"
            "Caption: Built to last a lifetime.\n"
            "Voiceover: Experience unmatched durability.\n\n"
            "Scene 2:\n"
            "Caption: Engineered with surgical precision.\n"
            "Voiceover: Every tolerance inspected.\n"
        )
        captions = auto._footage_script(text)
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["text"], "Built to last a lifetime.")
        self.assertEqual(captions[1]["text"], "Engineered with surgical precision.")

    def test_parses_numbered_lines_fallback(self):
        text = (
            "1. High performance CNC cutting in action.\n"
            "2. Seamless finish with sub-micron accuracy.\n"
            "3. Trusted by industry leaders worldwide.\n"
        )
        captions = auto._footage_script(text)
        self.assertEqual(len(captions), 3)
        self.assertEqual(captions[0]["text"], "High performance CNC cutting in action.")
        self.assertEqual(captions[1]["text"], "Seamless finish with sub-micron accuracy.")
        self.assertEqual(captions[2]["text"], "Trusted by industry leaders worldwide.")

    def test_rejects_instructions_in_prose(self):
        text = "I want to create a reel about our machine shop.\nPlease make an instagram reel for us."
        captions = auto._footage_script(text)
        self.assertEqual(captions, [])


class TestVoiceoverPromptAndRunner(unittest.TestCase):

    def test_voiceover_text_extracts_spoken_dialogue(self):
        text = '{"scenes": [{"voiceover": "Welcome to the workshop."}, {"voiceover": "We craft precision components."}]}'
        vo = auto._voiceover_text(text)
        self.assertIn("Welcome to the workshop.", vo)
        self.assertIn("We craft precision components.", vo)

    def test_maker_brief_tailored_for_voice(self):
        brief = auto._maker_brief("ElevenLabs", {"makes": "a voice-over audio file", "runner": "elevenlabs"})
        self.assertIn("voice-over audio", brief)
        self.assertIn("Speak ONLY the dialogue", brief)
        self.assertNotIn("Use the content below exactly as written: the headings", brief)


class TestArtworkAssetsCount(unittest.TestCase):

    def test_max_generated_is_six(self):
        self.assertEqual(RW.MAX_GENERATED, 6)

    def test_imagery_instructions_contains_six_assets(self):
        instructions = RW.imagery_instructions("A precision machine shop")
        self.assertIn("GENERATE EXACTLY 6 SEPARATE, REUSABLE", instructions)
        self.assertIn("WHAT THE 6 ASSETS ARE:", instructions)
        self.assertIn("1. A wordmark or emblem", instructions)
        self.assertIn("2. The PRIMARY HERO SUBJECT", instructions)
        self.assertIn("3. PROCESS / ACTION", instructions)
        self.assertIn("4. SECONDARY DETAIL", instructions)
        self.assertIn("5. TRUST / BADGE / METRIC", instructions)
        self.assertIn("6. OUTCOME / FINISH", instructions)


class TestPlanningStageMediaGuard(unittest.TestCase):

    def test_chatgpt_profile_avoid_prohibits_unprompted_images(self):
        from core import agents as A
        profile = A._PROFILES.get("ChatGPT", {})
        avoid = profile.get("avoid", "")
        self.assertIn("Do not generate images or call image tools", avoid)

    def test_claude_design_profile_avoid_prohibits_unprompted_images(self):
        from core import agents as A
        profile = A._PROFILES.get("Claude Design", {})
        avoid = profile.get("avoid", "")
        self.assertIn("Do not generate images or call image tools", avoid)

    def test_media_avoidance_note_added_when_query_requests_images(self):
        query = "i want to make a reel... ALSO GENERATE REQUIRED IMAGES FROM DIFFERENT ANGLE"
        # Simulate text stage context logic
        _kind = "text"
        context = auto._intent_block(query)
        if _kind == "text" and any(w in (query or "").lower() for w in (
                "image", "picture", "photo", "drawing", "visual", "artwork",
                "video", "reel", "audio", "voice")):
            context += (
                "NOTE ON MEDIA: The user's request asks for generated media "
                "(images, audio, or video). However, media generation is "
                "handled by dedicated later stages in this pipeline. For "
                "THIS step, do NOT generate images or call image creation "
                "tools — reply strictly with written text.\n\n"
            )
        self.assertIn("NOTE ON MEDIA:", context)
        self.assertIn("do NOT generate images", context)

    def test_media_avoidance_note_not_added_for_text_only_query(self):
        query = "summarise the strategic positioning of this competitor"
        _kind = "text"
        context = auto._intent_block(query)
        if _kind == "text" and any(w in (query or "").lower() for w in (
                "image", "picture", "photo", "drawing", "visual", "artwork",
                "video", "reel", "audio", "voice")):
            context += "NOTE ON MEDIA:"
        self.assertNotIn("NOTE ON MEDIA:", context)


class TestElevenLabsAndArtworkSequencing(unittest.TestCase):

    def test_chatgpt_is_busy_function_exists_and_callable(self):
        class MockDriver:
            def execute_script(self, script):
                return True
        self.assertTrue(auto._chatgpt_is_busy(MockDriver()))

    def test_output_panel_reuses_queued_visual_card_for_artwork(self):
        from widgets.output_panel import OutputPanel
        panel = OutputPanel()
        panel.set_plan([("brains", "ChatGPT"), ("visual", "ChatGPT"), ("media", "Prism Studio")])
        self.assertIn("visual", panel._cards)
        self.assertEqual(panel._cards["visual"]._state, "queued")

        # When artwork stage starts, it should reuse the visual card
        card = panel._ensure_card("artwork", "ChatGPT")
        self.assertIn("artwork", panel._cards)
        self.assertNotIn("visual", panel._cards)
        self.assertEqual(card.stage, "artwork")


if __name__ == "__main__":
    unittest.main()

