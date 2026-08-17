"""Which capture off the page is the reel script, and keeping it when none is.

A real failure this could not explain, and that is the point of the file. A
reel run came back with "no JSON scene spec found" against a Claude tab that
visibly contained a perfect spec. The log had one line — `captured 991 chars`
— and the text itself had already gone out of scope. Pasting the reply in by
hand parsed first time, so the reply was never the problem; something about
WHICH text was parsed, or what the page did to it, was. Neither could be
checked, because the evidence was thrown away at the moment it became
interesting.

Two defects, both real regardless of which one caused that run:

  · **`texts[0]` is the top of the tab, not the answer.** Prism reuses its
    browser profile, so a reused tab opens on an older conversation entirely
    — and the page also holds the prompt Prism just typed, which carries an
    EXAMPLE spec inside it. The web renderer had already learned this
    ("LAST, not longest"); the Pillow one and both of its callers had not.

  · **The unparseable reply was discarded.** The web renderer keeps it. The
    Pillow renderer, the GUI dialog and the CLI all dropped it, which is why
    the run above is undiagnosable rather than merely broken.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel as R  # noqa: E402


REPLY = json.dumps({"fps": 30, "scenes": [
    {"type": "statement", "seconds": 5,
     "lines": ["A Gerber folder arrives.", "Someone opens it,",
               "reads out the specs by hand."],
     "tail": "Before they can even quote."},
    {"type": "list", "seconds": 6, "heading": "One real board",
     "items": ["125.93 × 76.40 mm", "4 layers", "238 holes, 7 sizes",
               "0.152 mm thinnest track"],
     "tail": "Read instantly."},
    {"type": "endcard", "seconds": 4, "name": "Prism",
     "tagline_lines": ["Read the board.", "Skip the manual work."],
     "contact": ""},
]}, ensure_ascii=False)

# What the chat page holds ABOVE the answer: the prompt Prism typed, whose
# instructions quote an example spec, and — on a reused profile — whatever
# conversation was there before.
PRISM_OWN_PROMPT = (
    "SCENE TYPES — pick only the ones the story needs. Shape: "
    '{"fps": 30, "scenes": [ … ]}   '
    '  statement  {"type":"statement","seconds":4,'
    '"lines":["Up to 3 short lines"],"tail":"one quieter line"}   '
    '  endcard    {"type":"endcard","seconds":4,"name":"Company Name",'
    '"tagline_lines":["two short","lines"],"contact":"www.example.com"}')
AN_OLDER_CHAT = "Sure — here is a summary of your quarter. Nothing JSON here."


class TheNewestCaptureThatParses(unittest.TestCase):

    def test_it_is_the_answer_and_not_the_top_of_the_tab(self):
        spec, why = R.first_spec([AN_OLDER_CHAT, PRISM_OWN_PROMPT, REPLY])
        self.assertIsNotNone(spec, why)
        self.assertEqual(len(spec["scenes"]), 3)
        self.assertEqual(spec["scenes"][0]["lines"][0],
                         "A Gerber folder arrives.")

    def test_prisms_own_example_spec_is_not_mistaken_for_the_answer(self):
        """The prompt quotes single scenes AND a `{"scenes": [ … ]}` shape.
        Reading the page top-down walks straight into them."""
        spec, _ = R.first_spec([PRISM_OWN_PROMPT, REPLY])
        self.assertEqual(len(spec["scenes"]), 3)

    def test_the_longest_capture_is_not_the_answer_either(self):
        """A guard against the other tempting rule. The prompt is far longer
        than the reply — it is four thousand characters of instructions."""
        long_prompt = PRISM_OWN_PROMPT + "\n" + ("filler. " * 900)
        self.assertGreater(len(long_prompt), len(REPLY))
        spec, _ = R.first_spec([long_prompt, REPLY])
        self.assertEqual(len(spec["scenes"]), 3)

    def test_blank_captures_are_stepped_over(self):
        spec, _ = R.first_spec([REPLY, "", "   \n  "])
        self.assertIsNotNone(spec)

    def test_when_nothing_parses_it_says_why(self):
        spec, why = R.first_spec(["not json", "still not json"])
        self.assertIsNone(spec)
        self.assertIsInstance(why, Exception)
        self.assertTrue(str(why).strip())

    def test_nothing_at_all_is_not_a_crash(self):
        self.assertEqual(R.first_spec([]), (None, None))
        self.assertEqual(R.first_spec(None), (None, None))


class WhatTheChatWindowDoesToItOnTheWayOut(unittest.TestCase):

    def test_a_soft_wrapped_reply_still_parses(self):
        """The prompt forbids fences here, so the reply renders as prose and
        the scrape gets the browser's wrapping as real newlines — illegal
        inside a JSON string."""
        wrapped = "\n".join(textwrap.wrap(REPLY, 72, replace_whitespace=False,
                                          drop_whitespace=False))
        self.assertIsNotNone(R.first_spec([wrapped])[0])

    def test_a_linkified_url_no_longer_eats_the_spec(self):
        """Fixed on the web renderer and never carried across, which is
        obvious in hindsight — it is the same chat window. The swallowed link
        label brings its own unbalanced braces, so the brace scan cuts the
        spec in the wrong place."""
        spec = json.dumps({"scenes": [
            {"type": "endcard", "seconds": 4, "name": "Prism",
             "contact": "https://alphakore.in"}]})
        mangled = spec.replace(
            '"https://alphakore.in"',
            '"[https://alphakore.in/{a}](https://alphakore.in/%7Ba%7D)"')
        got, why = R.first_spec([mangled])
        self.assertIsNotNone(got, why)
        self.assertEqual(got["scenes"][0]["contact"], "https://alphakore.in/{a}")

    def test_a_thinking_chip_before_the_json_is_ignored(self):
        self.assertIsNotNone(R.first_spec(["Thought for 21s\n\n" + REPLY])[0])


class TheEvidenceIsKept(unittest.TestCase):
    """"No JSON scene spec found" against a tab that visibly contains JSON is
    unanswerable. Those two facts cannot both be investigated from a log
    line."""

    def setUp(self):
        import tempfile
        from core import config
        self.tmp = tempfile.mkdtemp()
        self._was = config.CONFIG_PATH
        # Into a scratch directory, never the customer's own — a test suite
        # that writes into ~/.prism has form in this repo.
        config.CONFIG_PATH = os.path.join(self.tmp, "config.json")
        self.config = config

    def tearDown(self):
        self.config.CONFIG_PATH = self._was

    def test_every_candidate_is_written_down(self):
        path = R.keep_unparsed(["first thing", "second thing"])
        self.assertTrue(path and os.path.exists(path))
        body = open(path, encoding="utf-8").read()
        self.assertIn("first thing", body)
        self.assertIn("second thing", body)

    def test_the_length_is_recorded_beside_each(self):
        """`captured 991 chars` in the log against a 935-character reply was
        the thread that unpicked this. The count has to sit with the text."""
        path = R.keep_unparsed(["abcde"])
        self.assertIn("(5 chars)", open(path, encoding="utf-8").read())

    def test_it_lands_somewhere_a_person_can_find(self):
        path = R.keep_unparsed(["x"])
        self.assertTrue(path.endswith(".txt"))
        self.assertIn("logs", path)
        self.assertIn("would-not-parse", os.path.basename(path))

    def test_a_full_disk_does_not_turn_a_bad_spec_into_a_crash(self):
        self.config.CONFIG_PATH = "/definitely/not/a/real/place/config.json"
        self.assertEqual(R.keep_unparsed(["x"]), "")


if __name__ == "__main__":
    unittest.main()


class TheMixOfScenes(unittest.TestCase):
    """What separates a reel from a wall of text, measured on two real reels
    drawn by this same renderer from this same prompt.

    The one the customer called the best they had: seven scenes, ONE of them
    text-only — statement, brand, pillar, pillar, pillar, hub, endcard. The
    one they called the worst: six scenes, FOUR of them text-only —
    statement, statement, list, statement, pillar, endcard.

    Nothing else differed. The prompt already said "pick by what you are
    saying, not by habit", and habit still won, because `statement` is the
    easiest scene to write and nothing counted them.
    """

    def spec(self, *kinds):
        secs = {"trend": 6, "hub": 5, "brand": 5, "figure": 5}
        out = []
        for k in kinds:
            sc = {"type": k, "seconds": secs.get(k, 4)}
            if k == "pillar":
                sc["icons"] = ["server", "network", "security"]
            if k == "hub":
                sc["nodes"] = [{"icon": "server", "label": f"n{i}"}
                               for i in range(4)]
            if k == "trend":
                sc["points"] = [{"label": "a", "value": 1},
                                {"label": "b", "value": 2}]
            out.append(sc)
        return {"scenes": out}

    def faults(self, *kinds):
        return " ".join(R.lint_spec(self.spec(*kinds)))

    def test_the_shape_that_worked_passes(self):
        """The real Raj Infotech running order. If this ever fails, the rule
        is wrong, not the reel."""
        self.assertEqual(R.lint_spec(self.spec(
            "statement", "brand", "pillar", "pillar", "pillar", "hub",
            "endcard")), [])

    def test_a_wall_of_text_is_sent_back(self):
        """The real failing order, verbatim."""
        said = self.faults("statement", "statement", "list", "statement",
                           "pillar", "endcard")
        self.assertIn("text-only", said)

    def test_two_text_scenes_are_still_allowed(self):
        """The rule has to leave room to make a point in words. Two is a
        reel with an opening and a turn; four is a post."""
        self.assertNotIn("text-only", self.faults(
            "statement", "brand", "list", "pillar", "hub", "endcard"))

    def test_two_statements_in_a_row_are_sent_back(self):
        said = self.faults("statement", "statement", "pillar", "hub",
                           "endcard")
        self.assertIn("in a row", said)

    def test_the_same_two_apart_are_not(self):
        self.assertNotIn("in a row", self.faults(
            "statement", "pillar", "statement", "hub", "brand", "endcard"))

    def test_a_reel_with_nothing_drawn_is_sent_back(self):
        """It could have been a post. That is the whole complaint."""
        said = self.faults("statement", "list", "statement", "endcard")
        self.assertIn("drawn as a diagram", said)

    def test_the_complaint_names_what_to_use_instead(self):
        """A rule the writer cannot act on is a rule that gets ignored on the
        retry as well."""
        said = self.faults("statement", "statement", "list", "statement",
                           "pillar", "endcard")
        for kind in ("figure", "trend", "pillar", "hub", "brand"):
            self.assertIn(f"'{kind}'", said, kind)

    def test_the_prompt_states_the_ratio_as_a_count(self):
        """The list of scene types was already there when the wall of text
        was written, so something has to actually count."""
        text = R.spec_instructions()
        self.assertIn("At most TWO text-only", text)
        self.assertIn("never two in a row", text)

    def test_the_prompt_gives_no_single_running_order_to_copy(self):
        """A worked example WAS given here — the good reel's actual order —
        and it was copied straight onto an unrelated business the same day.
        One template for every client is what this renderer is trying not to
        be, so the shapes offered have to be several and contradictory."""
        text = R.spec_instructions()
        self.assertIn("THE RUNNING ORDER IS YOURS", text)
        self.assertIn("examples of DIFFERENT, not a menu", text)
        # More than one shape, and they must not all start the same way.
        shapes = [ln for ln in text.split("\n")
                  if "endcard" in ln and "·" in ln and "—" in ln]
        self.assertGreaterEqual(len(shapes), 4, shapes)
        openers = {ln.split("—")[1].strip().split(",")[0] for ln in shapes}
        self.assertGreater(len(openers), 2, openers)


class NothingRunsOffTheFrame(unittest.TestCase):
    """Found by looking at a rendered frame, not by reading the code.

    `scene_statement` drew its lines and its tail with raw `d.text`, which
    Pillow will happily paint past the edge of the canvas without complaining.
    A three-word line fits and a sentence does not — and a sentence is what a
    model writes. The tail read "Read off every Gerber folder by hand, before
    anyo" on screen, cut mid-word.

    `scene_list` had wrapped the same field correctly all along, which is what
    made it obvious this was an oversight rather than a design.
    """

    def edge(self, scene, frames=90, step=5):
        """Rightmost pixel the TEXT paints. The blueprint grid is drawn edge
        to edge by design, so it is rendered separately and subtracted."""
        from PIL import Image, ImageDraw, ImageChops
        blank = {"lines": [], "tail": ""}
        out = 0
        for f in range(0, frames, step):
            a = Image.new("RGB", (R.W, R.H), R.Brand().bg)
            R.scene_statement(ImageDraw.Draw(a), R.Brand(), scene, f)
            g = Image.new("RGB", (R.W, R.H), R.Brand().bg)
            R.scene_statement(ImageDraw.Draw(g), R.Brand(), blank, f)
            box = ImageChops.difference(a, g).convert("L").point(
                lambda p: 255 if p > 8 else 0).getbbox()
            if box:
                out = max(out, box[2])
        return out

    def test_the_tail_that_was_clipped_now_wraps(self):
        """The exact string, off the reel that failed."""
        self.assertLess(self.edge({
            "lines": ["Layers.", "Holes.", "Tracks."],
            "tail": "Read off every Gerber folder by hand, before anyone "
                    "can quote."}), R.W)

    def test_a_line_longer_than_the_examples_shrinks_to_fit(self):
        self.assertLess(self.edge({"lines": ["Precision machined components"],
                                   "tail": "since 2009"}), R.W)

    def test_the_good_reels_own_scene_is_unchanged(self):
        """It fitted before and must still fit, well inside the margin."""
        self.assertLessEqual(self.edge({
            "lines": ["Servers.", "Networks.", "Security."],
            "tail": "The infrastructure your business runs on."}),
            R.W - R.SAFE_X)

    def test_a_line_too_long_to_shrink_is_rejected_upstream(self):
        """Past about forty characters no floor saves it, which is why the
        check exists before anything is drawn rather than only inside the
        renderer."""
        said = " ".join(R.lint_spec({"scenes": [
            {"type": "statement", "seconds": 5,
             "lines": ["Precision machined components for auto and pharma"]},
            {"type": "figure", "seconds": 6, "value": "1"},
            {"type": "hub", "seconds": 6, "nodes": [1, 2, 3, 4]},
            {"type": "endcard", "seconds": 5}]}))
        self.assertIn("characters", said)
        self.assertIn("under 24", said)

    def test_short_lines_are_not_complained_about(self):
        self.assertNotIn("under 24", " ".join(R.lint_spec({"scenes": [
            {"type": "statement", "seconds": 5,
             "lines": ["Servers.", "Networks.", "Security."]},
            {"type": "figure", "seconds": 6, "value": "1"},
            {"type": "hub", "seconds": 6, "nodes": [1, 2, 3, 4]},
            {"type": "endcard", "seconds": 5}]})))
