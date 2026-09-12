"""The composer: the reference's grammar built in code, the model's words
in its slots. Three reels written by the model scored 44-46; the
recreation the composer produces scores 84 — so a generated reel is now
composed, and the model is asked only for copy."""
from __future__ import annotations

import json
import os
import sys
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import compose, continuity, spine  # noqa: E402
from core.motion.fixtures import inspo_fixture  # noqa: E402
from core.motion.generate import (  # noqa: E402
    SPINE_SKELETON, build_spec, copy_instructions, parse_copy, storyboard_instructions)
from core.motion.schema import validate_motion_spec  # noqa: E402

COPY = {"brand": "Alphakore", "tagline": "AI agents that run your operations end to end",
        "cta": "Book a demo",
        "channel_cards": ["Lead Qualification", "Customer Support", "Scheduling"],
        "hub_card": {"title": "Inbound", "lines": "Qualifies every lead by budget and timing"},
        "bubbles": ["Hi Priya, your order is confirmed and ships tomorrow morning.",
                    "Can I change it?", "Yes, updated to your office address."],
        "cards": [{"label": "Sales Assistant",
                   "lines": "Answers pricing questions, books calls and hands warm leads to your reps."},
                  {"label": "Support Desk", "lines": "Resolves tickets from your docs."}],
        "knowledge": {"title": "Knowledge Base", "lines": "Your docs, policies and SOPs, always current.",
                      "labels": ["Pricing", "Compliance"]},
        "fact": "24/7", "captions": {"gather": "Every conversation, one system"}}


def _texts(spec):
    out = []
    stack = [n for sc in spec["scenes"] for n in sc["nodes"]]
    while stack:
        n = stack.pop()
        if n.get("type") == "text":
            out.append(str(n.get("content")))
        stack.extend(n.get("children") or [])
    return out


class TheSlots(unittest.TestCase):
    def test_fit_wraps_and_trims_to_the_box(self):
        self.assertEqual(compose.fit("one two three four five six", 9, 2), "one two\nthree fo…")
        self.assertEqual(compose.fit("short", 20), "short")
        self.assertEqual(compose.fit("a\nb", 5, 2), "a\nb")          # authored lines kept
        self.assertEqual(compose.fit("", 5), "")
        self.assertEqual(compose.fit(None, 5), "")

    def test_missing_slots_take_the_references_words(self):
        words = compose.normalise_copy({"brand": "Acme"})
        self.assertEqual(words["brand"], "Acme")
        self.assertEqual(words["fact"], "24/7")
        self.assertEqual(len(words["bubbles"]), 3)
        self.assertEqual(len(words["channel_cards"]), 3)
        self.assertEqual(words["cards"][1]["label"], "Front Desk Receptionist")
        self.assertEqual(words["captions"], {})

    def test_long_copy_is_cut_rather_than_spilt(self):
        words = compose.normalise_copy({"cta": "Book a free thirty minute strategy call with our team today"})
        self.assertLessEqual(len(words["cta"]), 22)
        self.assertTrue(words["cta"].endswith("…"))
        words = compose.normalise_copy({"bubbles": ["x " * 60, "y " * 30, "z"]})
        self.assertLessEqual(words["bubbles"][0].count("\n"), 1)
        self.assertNotIn("\n", words["bubbles"][1])


class TheComposition(unittest.TestCase):
    def test_the_references_copy_composes_the_recreation(self):
        a = json.loads(json.dumps(compose.compose(compose.REFERENCE_COPY)))
        b = json.loads(json.dumps(inspo_fixture()))
        self.assertEqual(a, b)
        spec = validate_motion_spec(a)
        for scene, name in zip(spec["scenes"], spine.beats_for(10)):
            self.assertEqual(spine.beat_faults(scene, name), [], name)

    def test_generated_copy_lands_in_its_slots_with_the_clients_mark(self):
        spec = compose.compose(COPY, 1080, 1920, 30,
                               logo={"src": "asset:logo", "w": 231, "h": 155},
                               palette={"accent": "#38BDF8", "accent2": "#7C3AED"})
        texts = _texts(spec)
        self.assertIn("Book a demo", texts)
        self.assertIn("Alphakore", texts)
        self.assertIn("Lead Qualification", texts)
        self.assertIn("Can I change it?", texts)
        self.assertIn("Every conversation, one system", texts)
        self.assertTrue(any(t.startswith("Hi Priya") and "\n" in t for t in texts), texts)
        last = spec["scenes"][-1]["nodes"]
        image = [n for n in last if n.get("type") == "image"]
        self.assertEqual(image[0]["src"], "asset:logo")
        self.assertLess(image[0]["position"][0], 400)       # a symbol stands left of the name
        self.assertTrue(any(n.get("id") == "logo_light" or n.get("id") == "logo" for n in last if n.get("type") == "text"))
        bubble = [n for n in spec["scenes"][4]["nodes"] if n.get("id") == "bubble_2"][0]
        self.assertEqual(bubble["fill"], "rgba(52,62,84,0.72)")   # a dark glass question, not the brand's colour
        orb = [n for n in spec["scenes"][8]["nodes"] if n.get("id") == "orb_blue"][0]
        self.assertEqual(orb["core"], "#38BDF8")
        validated = validate_motion_spec(json.loads(json.dumps(spec)))
        self.assertEqual(continuity.report(validated)["errors"], [])
        self.assertEqual(validated["project"]["fps"], 30)
        self.assertAlmostEqual(validated["project"]["duration"], 29.15, places=2)

    def test_a_wide_mark_stands_where_the_name_does(self):
        spec = compose.compose(COPY, logo={"src": "asset:wordmark", "w": 900, "h": 200})
        last = spec["scenes"][-1]["nodes"]
        self.assertFalse(any(n.get("id") in ("logo_light",) for n in last))
        image = [n for n in last if n.get("type") == "image"][0]
        self.assertEqual(image["position"], [540.0, 760.0])


class TheStage(unittest.TestCase):
    def test_a_panned_camera_can_look_past_the_frame(self):
        """The hub beat is authored below y 1920 under a camera that pans
        there; a stage that clipped at the frame hid its cards and lights."""
        html = open(os.path.join(ENGINE, "core", "motion", "runtime", "index.html"), encoding="utf-8").read()
        stage = html[html.index("#stage"):html.index("}", html.index("#stage"))]
        self.assertNotIn("overflow: hidden", stage)
        self.assertIn("overflow: visible", stage)


class TheComposedPath(unittest.TestCase):
    REPLY = "```json\n" + json.dumps({"project": {"palette": {"accent": "#38BDF8"}}, "copy": COPY}) + "\n```"

    def test_the_copy_turn_asks_for_the_slots_and_carries_the_script(self):
        prompt = storyboard_instructions("a reel", skeleton=SPINE_SKELETON, script="SCENE 1: Built for AI")
        self.assertIn('"copy":', prompt)
        self.assertIn('"bubbles"', prompt)
        self.assertIn("Built for AI", prompt)
        self.assertNotIn("storyboard", prompt.lower().split("reply with only")[0][-200:])
        self.assertEqual(prompt, copy_instructions("a reel", script="SCENE 1: Built for AI"))

    def test_parse_copy_reads_the_slots(self):
        project, copy = parse_copy(self.REPLY)
        self.assertEqual(copy["brand"], "Alphakore")
        self.assertEqual(project["palette"]["accent"], "#38BDF8")
        self.assertEqual(parse_copy("nothing here"), ({}, {}))

    def test_build_spec_composes_and_never_asks_for_a_scene(self):
        def ask(prompt, expect):
            raise AssertionError("the composed path must not ask for scenes")
        notes = []
        spec = build_spec(self.REPLY, ask, skeleton=SPINE_SKELETON, log=notes.append,
                          assets_table={"logo": {"path": "/x/logo.png", "w": 231, "h": 155,
                                                 "alpha": True, "kind": "logo"}},
                          check=lambda s: [])
        self.assertEqual(len(spec["scenes"]), 10)
        self.assertEqual(spec["_motion_profile"], "cinematic_glass")
        self.assertEqual(spec["_copy"]["brand"], "Alphakore")
        self.assertIn("logo", spec["_assets"])
        self.assertEqual(spec["scenes"][-1]["nodes"][1]["src"], "asset:logo")
        self.assertTrue(any("composed 10 scenes" in n for n in notes), notes)

    def test_a_reply_without_copy_is_asked_once_more(self):
        asked = []

        def ask(prompt, expect):
            asked.append(prompt)
            return self.REPLY
        spec = build_spec("{\"project\": {\"fps\": 30}}", ask, skeleton=SPINE_SKELETON)
        self.assertEqual(len(asked), 1)
        self.assertEqual(len(spec["scenes"]), 10)


if __name__ == "__main__":
    unittest.main()
