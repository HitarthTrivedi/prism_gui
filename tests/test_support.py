"""Can somebody get themselves unstuck without telephoning anyone?

`test_ux.py` defends the same property for the messages Prism shows when it
notices a problem. This defends it for the larger case: the customer who is
not looking at an error at all, and has gone looking for help.

Three things are easy to lose here, and all of them are silent:

  · the ANSWERS drift into our vocabulary. Every one of them is written for
    somebody who runs a fabrication shop, has never used ChatGPT, and did not
    choose any of this. The moment one says "endpoint" it has stopped working
    and nothing will tell us.
  · the GATE stops being honest. Holding the written answers in front of
    somebody before offering the assistant is only defensible while it
    opens the instant it has nothing for them. A change that makes it need
    two refusals instead of one turns a helpful screen into the kind people
    complain about, and it would not fail any other test.
  · the ASSISTANT starts answering from its imagination. It is only allowed
    to work from the written material — a made-up menu item costs the
    customer more than an admitted "I don't know" — and that rule lives in
    a prompt, which nothing but a test can hold in place.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import plans  # noqa: E402
import support_kb as KB  # noqa: E402

_app = QApplication.instance() or QApplication([])

# The same list friendly.py is held to. "api" is deliberately NOT here, unlike
# the guide's stricter list: the customer has to find a button that is labelled
# "API key" on our own Settings screen and on Groq's website, and refusing to
# print the words that are actually on the button helps nobody.
JARGON = ("traceback", "exception", "stacktrace", "selector", "webdriver",
          "selenium", "http ", "json", "null", "none type", "stderr",
          "api endpoint", "token expired", "oauth", "regex", "sys.")


def _panel():
    from widgets.support_panel import SupportPanel
    return SupportPanel()


def _said(panel) -> str:
    """Everything currently written in the transcript, flattened.

    Read from the widgets rather than from any internal log, because the
    widgets are what the customer sees — a message that was 'posted' but not
    rendered would pass a log-based check and still be a dead button."""
    texts = []
    box = panel._thread_box
    for i in range(box.count()):
        w = box.itemAt(i).widget()
        if w is not None:
            for label in w.findChildren(QLabel):
                texts.append(label.text())
    return " ".join(texts)


class TheAnswersAreUsable(unittest.TestCase):
    def test_there_are_enough_of_them_to_be_worth_showing(self):
        """A help screen with a dozen answers is a menu, not a help screen —
        it sends everybody to the contact form anyway."""
        self.assertGreaterEqual(len(KB.all_questions()), 40)
        self.assertGreaterEqual(len(KB.TOPICS), 6)

    def test_every_question_has_a_real_answer(self):
        for q in KB.all_questions():
            self.assertTrue(q.text, q.qid)
            self.assertGreater(len(q.answer.what), 40, q.qid)

    def test_every_answer_tells_them_what_to_do(self):
        """A message with no next action is a phone call — which is the exact
        thing this screen exists to prevent."""
        for q in KB.all_questions():
            self.assertTrue(q.answer.steps, f"no steps for {q.qid}")

    def test_the_words_are_ones_a_business_owner_uses(self):
        for q in KB.all_questions():
            text = (f"{q.text} {q.answer.what} {' '.join(q.answer.steps)} "
                    f"{q.answer.note}").lower()
            for word in JARGON:
                self.assertNotIn(word, text, f"{word!r} in {q.qid}")

    def test_steps_read_as_instructions_not_descriptions(self):
        starts_badly = ("the ", "this ", "there ", "it ", "prism's ")
        for q in KB.all_questions():
            for step in q.answer.steps:
                self.assertFalse(
                    step.lower().startswith(starts_badly),
                    f"{q.qid}: reads as a description, not an instruction: "
                    f"{step}")

    def test_nothing_blames_the_customer(self):
        for q in KB.all_questions():
            text = f"{q.text} {q.answer.what}".lower()
            for blame in ("you failed", "invalid input", "you must",
                          "illegal", "you should have"):
                self.assertNotIn(blame, text, q.qid)

    def test_questions_are_phrased_the_way_somebody_would_ask_them(self):
        """Filed our way ("Licence expiry handling") they are unfindable by
        the person who has the problem. Asked their way, the search works and
        the list can be skimmed."""
        for q in KB.all_questions():
            self.assertGreater(len(q.text.split()), 3, q.qid)


class TheAnswersPointSomewhereReal(unittest.TestCase):
    def test_every_button_goes_somewhere_the_window_understands(self):
        """An action key the dispatcher has no branch for is a button that
        silently does nothing — and nothing else in the app would catch it."""
        import main_window
        src = inspect.getsource(main_window.MainWindow._handle_command)
        for q in KB.all_questions():
            if q.answer.action:
                self.assertIn(f'"{q.answer.action}"', src,
                              f"{q.qid} points at {q.answer.action!r}, which "
                              f"_handle_command does not dispatch")

    def test_the_pointers_from_elsewhere_are_dispatchable_too(self):
        """friendly's catch-all and the guide's last topic both send people
        here — checked against the same dispatcher, for the same reason."""
        import friendly
        import main_window
        from dialogs.guide_dialog import TOPICS
        src = inspect.getsource(main_window.MainWindow._handle_command)
        pointers = [t.action for t in TOPICS if t.action]
        generic = friendly.explain("something entirely unrecognised")
        if generic.action:
            pointers.append(generic.action)
        for action in pointers:
            self.assertIn(f'"{action}"', src, action)

    def test_support_itself_is_reachable_without_knowing_where_it_went(self):
        """It left the rail for Settings when the rail was cut back to Home,
        the add-ons and Settings. What matters is that a stuck customer can
        still get to it, so this asserts reachability rather than a location:
        it is in the rail, or it is in the Settings screen the rail still has.
        """
        from widgets.sidebar import MORE, SECONDARY
        from widgets.settings_panel import MORE_LINKS
        rail = [key for key, _l, _i, _t in MORE]
        settings = [key for key, _l, _b in MORE_LINKS]
        self.assertIn("config", rail, "Settings must stay in the rail")
        self.assertIn("support", settings + [k for k, _l, _i, _t in SECONDARY])
        self.assertIn("support", settings, "and be listed on that screen")

    def test_the_window_has_a_screen_for_it(self):
        import main_window
        src = inspect.getsource(main_window.MainWindow._show_screen)
        self.assertIn('"support"', src)

    def test_every_topic_icon_actually_draws(self):
        """icons.pixmap raises on a name it doesn't know — at runtime that
        would happen while building the topic list, taking the screen down."""
        from widgets import icons
        for t in KB.TOPICS:
            self.assertTrue(icons.pixmap(t.icon, 16), t.key)

    def test_every_add_on_answer_names_a_feature_that_exists(self):
        for q in KB.all_questions():
            if q.answer.feature:
                self.assertIn(q.answer.feature, plans.FEATURES, q.qid)

    def test_related_questions_all_resolve(self):
        for q in KB.all_questions():
            for other in q.related:
                self.assertIsNotNone(KB.question(other),
                                     f"{q.qid} points at missing {other!r}")

    def test_no_question_points_at_itself(self):
        for q in KB.all_questions():
            self.assertNotIn(q.qid, q.related, q.qid)

    def test_ids_are_unique(self):
        ids = [q.qid for t in KB.TOPICS for q in t.questions]
        self.assertEqual(len(ids), len(set(ids)))


class SearchFindsTheRightThing(unittest.TestCase):
    """The phrasings are real ones — what somebody types is rarely our
    heading, and a search that only matches our own wording is a search that
    sends everybody to the contact form."""

    CASES = [
        ("captcha keeps appearing", "robot-check"),
        ("gmail rejected my app password", "email-password"),
        ("how many computers can I install this on", "how-many-computers"),
        ("my laptop was stolen and the seat is stuck", "dead-laptop"),
        ("it cant read my dwg", "boq-dwg"),
        ("can I read it in gujarati", "change-language"),
        ("no space left on device", "disk-full"),
        ("can i close the lid while it runs", "walk-away"),
        ("where is my data stored", "where-data"),
        ("windows protected your pc", "os-warning"),
        ("step came back empty", "empty-step"),
        ("chrome wont start", "chrome-wont-open"),
        ("whats the difference between studio and quick", "reel-or-studio"),
        ("can it read two mailboxes at once", "many-mailboxes"),
        ("how does the whole team see one sheet", "shared-register"),
    ]

    def test_the_right_answer_is_in_the_top_few(self):
        for typed, expected in self.CASES:
            hits = [q.qid for q in KB.search(typed)]
            self.assertIn(expected, hits, f"{typed!r} -> {hits}")

    def test_the_best_match_is_usually_first(self):
        first = sum(1 for typed, expected in self.CASES
                    if (h := KB.search(typed)) and h[0].qid == expected)
        self.assertGreaterEqual(first, len(self.CASES) - 2,
                                "ranking has drifted")

    def test_something_we_have_no_answer_for_returns_nothing(self):
        """This is what opens the route to a person, so it has to stay
        decisive. A weak guess here traps somebody in the menu."""
        for nonsense in ("quantum blockchain integration",
                         "refund my order 12345", "zzzzz"):
            self.assertEqual(KB.search(nonsense), [], nonsense)

    def test_an_empty_query_is_not_a_match_for_everything(self):
        self.assertEqual(KB.search(""), [])
        self.assertEqual(KB.search("   the it is"), [])


class TheGateIsShutButNotLocked(unittest.TestCase):
    """The heart of it. Both halves matter and they pull against each other:
    shut, so the written answers get read; never locked, so nobody whose
    problem is not in the book is trapped behind answers that cannot help."""

    def test_both_routes_out_start_shut(self):
        p = _panel()
        self.assertFalse(p._ai_btn.isEnabled())
        self.assertFalse(p._contact_btn.isEnabled())

    def test_it_says_what_opens_them(self):
        """A disabled button with no reason beside it is indistinguishable
        from a broken one."""
        p = _panel()
        self.assertTrue(p._foot_note.text())
        self.assertTrue(p._ai_btn.toolTip())

    def test_reading_an_answer_alone_does_not_open_them(self):
        p = _panel()
        p._show_answer("empty-step")
        self.assertIn("empty-step", p._seen)
        self.assertFalse(p._contact_btn.isEnabled(),
                         "reading an answer is not the same as it failing")

    def test_one_answer_that_did_not_help_opens_both(self):
        p = _panel()
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=False)
        self.assertTrue(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled())

    def test_an_answer_that_worked_leaves_them_shut(self):
        p = _panel()
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=True)
        self.assertFalse(p._contact_btn.isEnabled())

    def test_a_question_we_cannot_answer_opens_them_immediately(self):
        """Nobody is made to read irrelevant answers to earn a person."""
        p = _panel()
        p._entry.setText("my invoice printer is jamming")
        p._on_typed()
        self.assertTrue(p._contact_btn.isEnabled())
        self.assertTrue(p._ai_btn.isEnabled())

    def test_saying_none_of_these_is_what_i_meant_also_opens_them(self):
        p = _panel()
        p._no_answer("something we do not cover")
        self.assertTrue(p._contact_btn.isEnabled())

    def test_a_typed_question_we_do_answer_stays_in_the_written_tier(self):
        p = _panel()
        p._entry.setText("captcha keeps appearing")
        p._on_typed()
        self.assertFalse(p._contact_btn.isEnabled())


class TheTranscriptStaysReadable(unittest.TestCase):
    """The UX complaint the first version earned: every menu stayed in the
    thread for ever, so ten topics plus ten questions plus ten topics again
    read as a form that kept growing. Menus retire once the conversation
    moves past them; the pick survives as the customer's own bubble."""

    def test_a_menu_is_retired_once_something_is_picked_from_it(self):
        p = _panel()
        self.assertEqual(len(p._live), 1, "the greeting should offer topics")
        p._show_topic("running")
        # The topic chips are gone; what is live now is the question list
        # (and the way back to the topics).
        self.assertEqual(len(p._live), 2)
        p._show_answer("empty-step")
        self.assertEqual(len(p._live), 0,
                         "old menus left live in the scrollback fork the "
                         "conversation")

    def test_the_pick_survives_as_the_customers_own_words(self):
        p = _panel()
        p._show_topic("running")
        self.assertIn(("you", "Running a job"), p._log)

    def test_typing_also_moves_past_the_menus(self):
        p = _panel()
        p._entry.setText("captcha keeps appearing")
        p._on_typed()
        self.assertEqual(len(p._live), 1, "only the search hits stay live")

    def test_start_over_forgets_everything(self):
        p = _panel()
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=False)
        p._start_over()
        self.assertEqual(p._seen, [])
        self.assertEqual(p._unsolved, [])
        self.assertEqual(p._stage, "triage")
        self.assertFalse(p._contact_btn.isEnabled(), "the gate reopened shut")


class WhatTheAssistantIsTold(unittest.TestCase):
    def test_it_is_given_the_shape_of_the_whole_product(self):
        """Without every heading it cannot say "that's under Licence" — it
        invents a menu instead, which is worse than admitting ignorance."""
        context = KB.as_context("licence")
        for q in KB.all_questions():
            self.assertIn(q.text, context, q.qid)

    def test_it_is_given_the_full_answer_for_what_was_asked(self):
        context = KB.as_context("my app password was refused")
        self.assertIn("myaccount.google.com/apppasswords", context)

    def test_it_is_told_what_they_have_already_read(self):
        context = KB.as_context("still stuck", seen=("dead-laptop",))
        self.assertIn("device code", context.lower())

    def test_it_stays_small_enough_to_send_every_turn(self):
        biggest = max(len(KB.as_context(q.text, seen=(q.qid,)))
                      for q in KB.all_questions())
        self.assertLess(biggest, 14000, "context has grown past its budget")

    def test_the_assistant_is_told_to_refuse_rather_than_guess(self):
        from widgets.support_panel import _SYSTEM
        self.assertIn("Contact the team", _SYSTEM)
        for rule in ("ONLY", "Never guess"):
            self.assertIn(rule, _SYSTEM)


class TheAssistantTier(unittest.TestCase):
    def _open(self, **cfg):
        from widgets.support_panel import SupportPanel
        p = SupportPanel(cfg)
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=False)
        return p

    def test_it_starts_when_asked(self):
        p = self._open(api_key="gsk_test")
        p._start_ai()
        self.assertEqual(p._stage, "ai")

    def test_its_own_button_locks_while_talking_to_it(self):
        """Pressing "Ask the assistant" mid-conversation with the assistant
        would restart an introduction nobody asked for."""
        p = self._open(api_key="gsk_test")
        p._start_ai()
        self.assertFalse(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled(),
                        "the person must stay reachable from the assistant")

    def test_without_a_key_it_says_so_instead_of_failing(self):
        """The customer least likely to have a key is the one who has not
        finished setting up — exactly who needs help most."""
        p = self._open()
        p._start_ai()
        self.assertEqual(p._stage, "triage")
        self.assertIn("key", " ".join(t for _w, t in p._log).lower())

    def test_contacting_a_person_still_works_without_a_key(self):
        p = self._open()
        self.assertTrue(p._contact_btn.isEnabled())

    def test_the_prompt_carries_the_manual_and_the_conversation(self):
        p = self._open(api_key="gsk_test")
        prompt = p._prompt("it is still empty")
        self.assertIn("A step came back empty", prompt)
        self.assertIn("it is still empty", prompt)
        self.assertIn("Already read", prompt)

    def test_a_failure_is_explained_the_way_the_rest_of_the_app_does(self):
        p = self._open(api_key="gsk_test")
        p._ai_failed("Groq is rate-limiting your API key.")
        self.assertIn("allowance", " ".join(t for _w, t in p._log).lower())

    def test_the_worker_asks_groq_with_the_cautious_temperature(self):
        """Support answers are quotations from the manual — a model feeling
        creative about which menu an option lives in is the one failure this
        tier cannot afford."""
        import core_bridge as CB
        from workers import SupportWorker
        seen = {}

        def fake_chat(key, model, prompt, **kwargs):
            seen.update(key=key, prompt=prompt, **kwargs)
            return "Open Settings and check the key."

        answers = []
        worker = SupportWorker({"api_key": "gsk_test"}, "PROMPT TEXT")
        worker.done.connect(answers.append)
        with mock.patch.object(CB.router, "groq_chat", fake_chat):
            worker.run()
        self.assertEqual(answers, ["Open Settings and check the key."])
        self.assertEqual(seen["key"], "gsk_test")
        self.assertLessEqual(seen["temperature"], 0.2)


class ContactingUs(unittest.TestCase):
    def setUp(self):
        """Held on `self`, not returned from a helper — a QDialog with no
        Python reference is collected immediately and every later call raises
        "C++ object already deleted"."""
        from dialogs.contact_dialog import ContactDialog
        self.sheet = ContactDialog("Me: it broke\n\nPrism: sorry")

    def test_the_draft_already_contains_what_we_would_ask_for(self):
        import app_meta
        body = self.sheet._body.toPlainText()
        self.assertIn(app_meta.VERSION, body)
        self.assertIn("it broke", body,
                      "the conversation should not have to be retyped")

    def test_it_names_an_address_a_person_reads(self):
        import app_meta
        self.assertIn("@", app_meta.SUPPORT_EMAIL)
        self.assertTrue(self.sheet.windowTitle())

    def test_the_draft_carries_no_secrets(self):
        """They cannot reasonably check this before sending it, so it has to
        be true by construction."""
        self.sheet._name.setText("Ravi")
        text = self.sheet._full_text().lower()
        for secret in ("gsk_", "password", "api key", "licence key"):
            self.assertNotIn(secret, text)

    def test_the_device_code_is_there_because_seat_problems_need_it(self):
        body = self.sheet._body.toPlainText().lower()
        self.assertIn("device code", body)


class ItAllBuilds(unittest.TestCase):
    def test_the_screen_builds_with_no_licence_and_no_key(self):
        """The worst-served customer is a brand-new one whose activation
        failed — help must open for them above all."""
        from unittest import mock
        import licensing
        with mock.patch.object(licensing, "has", return_value=False):
            p = _panel()
            p._show_answer("boq-file")        # a locked add-on answer
            self.assertIn("boq-file", p._seen)

    def test_every_answer_renders(self):
        p = _panel()
        for q in KB.all_questions():
            p._show_answer(q.qid)
        self.assertEqual(len(p._seen), len(KB.all_questions()))

    def test_every_topic_opens(self):
        p = _panel()
        for topic in KB.TOPICS:
            p._show_topic(topic.key)

    def test_the_conversation_survives_leaving_the_screen(self):
        """It is a screen, not a dialog: following an answer's button to
        Settings and coming back must land on the same thread, or the button
        that helps costs the conversation that led to it."""
        p = _panel()
        p._show_answer("empty-step")
        p._take_action("login")               # what the answer's button does
        self.assertIn("empty-step", p._seen, "state was reset by the action")


if __name__ == "__main__":
    unittest.main(verbosity=2)
