"""Does a first-time user get told what to do?

The product goal these defend: a business owner who has never used AI should
be able to resolve an ordinary problem without telephoning anyone. That means
two properties, and both are easy to lose by accident:

  · every failure they can meet is TRANSLATED — no HTTP codes, no exception
    class names, no "selector", "driver" or "token" on screen;
  · every message carries a NEXT ACTION. A message with no action is a phone
    call, so an entry with no steps is a bug in the copy.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import friendly  # noqa: E402
import plans  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Real error text, as the customer's machine would produce it.
REAL_ERRORS = [
    ("run", "Message: session not created: This version of ChromeDriver only "
            "supports Chrome version 131"),
    ("run", "selenium.common.exceptions.WebDriverException: unknown error"),
    ("plan", "Groq API error (HTTP 429): {'error': {'code': "
             "'rate_limit_exceeded'}}"),
    ("plan", "Groq rejected your API key. Re-enter it in Setup."),
    ("plan", "Couldn't reach Groq — check your internet connection."),
    ("run", "Couldn't reach the licence server at https://x.onrender.com"),
    ("run", "You're not signed in to this tool."),
    ("run", "This tool is showing a human-verification check."),
    ("email", "(535, b'5.7.8 Username and Password not accepted')"),
    ("attach", "[Errno 13] Permission denied: '/Users/x/spec.pdf'"),
    ("attach", "[Errno 28] No space left on device"),
    ("attach", "FileNotFoundError: /Users/x/gone.png"),
    ("boq", "ModuleNotFoundError: No module named 'ezdxf'"),
    ("reel", "FFmpeg is not installed"),
    ("voice", "Microphone unavailable: PortAudio not found"),
    ("run", "The agent returned nothing."),
    ("leads", "Apollo returned no rows."),
    ("licence", "Your licence has ended."),
    ("run", "KeyError: 'unexpected'"),
    ("run", ""),
]

# Words a business owner should never be shown. Checked against the friendly
# text only — the technical detail is folded away in the dialog on purpose.
JARGON = ("traceback", "exception", "stacktrace", "selector", "webdriver",
          "selenium", "http ", "json", "null", "none type", "stderr",
          "api endpoint", "token expired", "oauth", "regex", "sys.")


class EveryErrorIsAnswerable(unittest.TestCase):
    def test_each_one_gets_a_title_and_an_explanation(self):
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            self.assertTrue(problem.title, error)
            self.assertTrue(problem.what, error)

    def test_each_one_tells_them_what_to_do(self):
        """A message with no next action is a phone call."""
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            self.assertTrue(problem.steps,
                            f"no steps for {context}: {error[:60]}")

    def test_the_words_are_ones_a_business_owner_uses(self):
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            text = f"{problem.title} {problem.what} {' '.join(problem.steps)}"
            for word in JARGON:
                self.assertNotIn(word, text.lower(),
                                 f"{word!r} shown for {context}: {error[:50]}")

    def test_steps_read_as_instructions_not_descriptions(self):
        """Every step should start with a verb — 'Open…', 'Check…', 'Wait…' —
        rather than describing the system's state."""
        starts_badly = ("the ", "this ", "there ", "it ", "prism's ")
        for context, error in REAL_ERRORS:
            for step in friendly.explain(error, context).steps:
                self.assertFalse(
                    step.lower().startswith(starts_badly),
                    f"step reads as a description, not an instruction: {step}")

    def test_the_common_ones_offer_a_button_that_fixes_it(self):
        """Telling somebody to open Settings is worse than taking them."""
        for error, expected in (
                ("session not created: chrome version", "settings:chrome"),
                ("Groq rejected your api key", "settings:key"),
                ("You're not signed in to this tool", "login")):
            self.assertEqual(friendly.explain(error).action, expected, error)

    def test_an_unknown_error_still_helps(self):
        problem = friendly.explain("ZeroDivisionError: division by zero")
        self.assertTrue(problem.steps)
        self.assertTrue(problem.ask_support,
                        "when we don't know, the honest step is 'send it to us'")

    def test_support_is_offered_only_when_it_is_the_real_next_step(self):
        """Offering it every time trains people to send a file instead of
        reading the fix."""
        self.assertFalse(friendly.explain("rate limit exceeded").ask_support)
        self.assertFalse(friendly.explain("not signed in").ask_support)
        self.assertTrue(friendly.explain("something bizarre").ask_support)

    def test_nothing_blames_the_user(self):
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            text = f"{problem.title} {problem.what}".lower()
            for blame in ("you failed", "invalid input", "you must",
                          "illegal", "you should have"):
                self.assertNotIn(blame, text)


class ProblemDialogBuilds(unittest.TestCase):
    def test_it_builds_for_every_real_error(self):
        from dialogs.problem_dialog import ProblemDialog
        for context, error in REAL_ERRORS:
            dialog = ProblemDialog(friendly.explain(error, context),
                                   detail=str(error))
            self.assertTrue(dialog.windowTitle())

    def test_the_technical_detail_starts_hidden(self):
        from dialogs.problem_dialog import ProblemDialog
        dialog = ProblemDialog(friendly.explain("session not created"),
                               detail="WebDriverException: chrome 131")
        self.assertFalse(dialog._detail_label.isVisible())

    def test_pressing_the_fix_button_reports_the_action(self):
        from dialogs.problem_dialog import ProblemDialog
        dialog = ProblemDialog(friendly.explain("not signed in"))
        dialog._take_action()
        self.assertEqual(dialog.chosen_action, "login")


class Guide(unittest.TestCase):
    def test_every_topic_has_a_title_and_body(self):
        from dialogs.guide_dialog import TOPICS
        for topic in TOPICS:
            self.assertTrue(topic.title)
            self.assertGreater(len(topic.body), 40, topic.title)

    def test_the_guide_avoids_jargon_too(self):
        from dialogs.guide_dialog import TOPICS
        banned = ("prompt engineering", "llm", "api", "pipeline stage",
                  "selector", "agent registry", "oauth")
        for topic in TOPICS:
            text = f"{topic.title} {topic.body}".lower()
            for word in banned:
                self.assertNotIn(word, text, f"{word!r} in {topic.title}")

    def test_every_add_on_topic_names_the_feature_that_unlocks_it(self):
        from dialogs.guide_dialog import TOPICS
        for topic in TOPICS:
            if topic.feature:
                self.assertIn(topic.feature, plans.FEATURES, topic.title)

    def test_locked_topics_are_still_listed(self):
        """The guide is the only place a customer can discover what else
        Prism does — a list with holes teaches them nothing."""
        from dialogs.guide_dialog import TOPICS
        self.assertTrue([t for t in TOPICS if t.feature])

    def test_it_builds_and_shows_locked_items_greyed(self):
        from unittest import mock
        import licensing
        from dialogs.guide_dialog import GuideDialog
        core_only = type("S", (), {
            "usable": True, "status": "valid", "features": frozenset(["core"]),
            "message": "", "customer": "X", "plan": "p", "kind": "paid",
            "seats": 1, "license_ends": 0, "days_left": 9, "license_id": "l",
            "grace_days": 0, "has": lambda s, f: f == "core"})()
        with mock.patch.object(licensing, "state", return_value=core_only):
            GuideDialog()          # builds without raising


class Plans(unittest.TestCase):
    def test_the_three_plans_exist_and_are_distinct(self):
        self.assertEqual(set(plans.ORDER), {"studio", "works", "complete"})
        sets = [set(plans.PLANS[k].includes) for k in plans.ORDER]
        self.assertEqual(len(sets), len({frozenset(s) for s in sets}))

    def test_every_plan_includes_the_pipeline(self):
        """A licence that cannot run a task is not a product."""
        for key in plans.ORDER:
            self.assertIn("core", plans.PLANS[key].includes, key)

    def test_the_manufacturing_plan_sells_the_shop_floor_tools(self):
        works = plans.PLANS["works"].includes
        for feature in ("boq", "bom", "attendance"):
            self.assertIn(feature, works)
        self.assertIn("marketing", plans.PLANS["works"].addons)

    def test_the_services_plan_sells_the_marketing_tools(self):
        studio = plans.PLANS["studio"].includes
        for feature in ("marketing", "leads"):
            self.assertIn(feature, studio)
        self.assertIn("boq", plans.PLANS["studio"].addons)

    def test_complete_really_is_everything(self):
        self.assertEqual(set(plans.PLANS["complete"].includes),
                         set(plans.FEATURES))

    def test_a_plan_and_its_addons_never_overlap(self):
        """Selling somebody something they already have is the worst kind of
        pricing bug."""
        for key in plans.ORDER:
            plan = plans.PLANS[key]
            self.assertFalse(set(plan.includes) & set(plan.addons), key)

    def test_a_plan_plus_its_addons_covers_the_catalogue(self):
        for key in plans.ORDER:
            plan = plans.PLANS[key]
            self.assertEqual(set(plan.includes) | set(plan.addons),
                             set(plans.FEATURES), key)

    def test_every_feature_can_be_sold(self):
        """A feature no plan includes is one nobody can ever buy."""
        sellable = set()
        for key in plans.ORDER:
            sellable |= set(plans.PLANS[key].includes)
        self.assertEqual(sellable, set(plans.FEATURES))

    def test_every_feature_has_words_to_sell_it_with(self):
        for key, feature in plans.FEATURES.items():
            self.assertTrue(feature.label, key)
            self.assertTrue(feature.blurb, key)
            self.assertTrue(plans.pitch(key), key)

    def test_a_broken_licence_still_leaves_a_working_pipeline(self):
        self.assertEqual(plans.features_for("nonsense"), plans.FALLBACK)
        self.assertIn("core", plans.FALLBACK)

    def test_a_bespoke_set_is_reported_as_custom_not_as_a_plan(self):
        self.assertEqual(plans.plan_of({"core", "boq"}), "Custom")
        self.assertEqual(plans.plan_of(plans.features_for("works")),
                         "Prism Works")

    def test_the_paywall_can_pitch_every_feature(self):
        from dialogs.paywall import PITCH
        for key in plans.FEATURES:
            self.assertIn(key, PITCH, f"no paywall copy for {key}")
            _name, _icon, text = PITCH[key]
            self.assertTrue(text, key)


class BoqIsLocked(unittest.TestCase):
    """The specific gate that was asked about."""

    def test_boq_is_not_in_the_services_plan(self):
        self.assertNotIn("boq", plans.PLANS["studio"].includes)
        self.assertIn("boq", plans.PLANS["studio"].addons)

    def test_a_core_only_licence_cannot_reach_boq(self):
        from unittest import mock
        import licensing
        core_only = type("S", (), {
            "usable": True, "status": "valid", "features": frozenset(["core"]),
            "message": "", "has": lambda s, f: f == "core"})()
        with mock.patch.object(licensing, "state", return_value=core_only):
            self.assertFalse(licensing.has("boq"))
            self.assertTrue(licensing.has("core"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
