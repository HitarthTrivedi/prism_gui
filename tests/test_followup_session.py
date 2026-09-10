"""Follow-ups: more than one, and a reel's go back to its own design chat.

Two faults, both reported on 2026-09-07:

  · "follow up is one time only" — a follow-up runs a single stage, and its
    completion handed THAT stage's responses and links to the next offer
    alone. The second follow-up knew nothing of the other stages, their
    tabs, or the reel, and there was no third. Now one session per task is
    merged across follow-ups.
  · a follow-up on a Studio reel never reached the conversation that
    designed it: the classifier picked the local renderer (a file for a
    link, no chat) or the writer in a fresh tab. Now a filmed reel's
    follow-up goes straight to the saved design URL.

Built on test_gates' harness because that is the one place a real
MainWindow is constructed without touching the developer's ~/.prism.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402
import test_gates  # noqa: E402


def _dialog(text="", files=()):
    """A FollowupDialog that answers without a window."""
    class Fake:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 0

        def submitted(self):
            return bool(text)

        def followup_text(self):
            return text

        def file_paths(self):
            return list(files)
    return Fake


class FollowupBase(test_gates.GateTest):

    def _win(self, query="make a reel for instagram"):
        self.grant(["core"])
        win = self._window()
        win.cfg["api_key"] = "k"
        win._last_query = query
        self.art = os.path.join(self.tmp, "art")
        os.makedirs(self.art, exist_ok=True)
        return win

    def _offer(self, win, responses, links, text="", call=None):
        import main_window
        with mock.patch("dialogs.followup_dialog.FollowupDialog", _dialog(text)), \
             mock.patch.object(CB.config, "artifact_task_dir", return_value=self.art), \
             mock.patch.object(main_window, "StudioFollowupWorker") as studio, \
             mock.patch.object(main_window, "FollowupRouteWorker") as classifier, \
             mock.patch.object(main_window, "AutomationWorker") as auto:
            if call is not None:
                call()
            else:
                win._offer_followup(responses, links)
            # The classifier is a thread; here it answers at once, and with
            # an empty plan — "unsure" — which is the window's decision to
            # make (a reel task → the reel; otherwise the last step).
            if classifier.called:
                classifier.return_value.done.connect.call_args[0][0]({})
        return studio, classifier, auto

    def _filmed(self):
        mp4 = os.path.join(self.tmp, "reel_1.mp4")
        open(mp4, "wb").close()
        with open(os.path.join(self.tmp, "reel_1.json"), "w", encoding="utf-8") as f:
            json.dump({"design": {"css": ":root{}"},
                       "scenes": [{"html": "<p>x</p>", "seconds": 4}]}, f)
        return mp4


class TheSessionOutlivesOneFollowup(FollowupBase):

    def test_a_second_follow_up_still_sees_every_stage(self):
        win = self._win()
        win._stage_agents = {"brains": "ChatGPT", "content": "Claude"}
        self._offer(win, {"brains": ["plan"], "content": ["copy"]},
                    {"brains": "https://chat/1", "content": "https://claude/2"})
        # The follow-up run reports only the stage it re-ran.
        self._offer(win, {"content": ["copy v2"]}, {"content": "https://claude/2"})
        self.assertEqual(sorted(win._followup_links), ["brains", "content"])
        self.assertEqual(win._followup_links["brains"], "https://chat/1")
        sess = win._followup_session
        self.assertEqual(sess["responses"]["content"], ["copy v2"])
        self.assertEqual(sess["responses"]["brains"], ["plan"])
        self.assertEqual(sess["agents"]["brains"], "ChatGPT")

    def test_a_new_task_starts_afresh(self):
        win = self._win()
        win._stage_agents = {"brains": "ChatGPT"}
        self._offer(win, {"brains": ["plan"]}, {"brains": "https://chat/1"})
        win._last_query = "write a tender"
        win._stage_agents = {"content": "Claude"}
        self._offer(win, {"content": ["doc"]}, {"content": "https://claude/9"})
        self.assertEqual(list(win._followup_links), ["content"])


class TheFollowupPrompt(FollowupBase):

    def test_leads_with_the_new_instruction_not_the_old_result(self):
        win = self._win()
        win._followup_text = "Make the mushroom farming plan suitable for Gujarat."
        prompt = win._followup_prompt("content", {"content": ["old plan"]}, True)
        self.assertIn(win._followup_text, prompt)
        self.assertLess(prompt.index(win._followup_text), prompt.index("old plan"))
        self.assertIn("Do the change now", prompt)

    def test_keeps_a_long_prior_result_small_enough_for_a_web_composer(self):
        win = self._win()
        win._followup_text = "Use a smaller greenhouse."
        prior = "START " + ("x" * 12_000) + " END"
        prompt = win._followup_prompt("content", {"content": [prior]}, True)
        self.assertLessEqual(len(prompt), 8_500)
        self.assertIn("START", prompt)
        self.assertIn("END", prompt)
        self.assertIn("Earlier result shortened", prompt)


class AReelGoesBackToItsDesignChat(FollowupBase):

    def test_failed_export_recovers_project_and_uses_studio_worker(self):
        win = self._win()
        win._stage_agents = {"design": "ChatGPT", "media": "Prism Studio"}
        project = {"design": {"css": ""},
                   "_studio": {"design_url": "https://chatgpt.com/c/2"},
                   "scenes": [{"html": "<p>Recover me</p>", "seconds": 4}]}
        with open(os.path.join(self.tmp, "reel_failed.json"), "w") as f:
            json.dump(project, f)
        # Neither a broken record nor a newer, unrelated project may win.
        with open(os.path.join(self.tmp, "reel_broken.json"), "w") as f:
            f.write("{")
        project["_studio"]["design_url"] = "https://chatgpt.com/c/other"
        with open(os.path.join(self.tmp, "reel_unrelated.json"), "w") as f:
            json.dump(project, f)
        with mock.patch.object(CB.config, "RUNS_DIR", self.tmp):
            studio, _, auto = self._offer(
                win, {"design": ["storyboard"]},
                {"design": "https://chatgpt.com/c/2/"}, text="fix and render")
        self.assertTrue(studio.called)
        auto.assert_not_called()
        self.assertEqual(studio.call_args[0][1]["scenes"][0]["html"], "<p>Recover me</p>")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "reel_failed.mp4")))

    def test_missing_matching_project_does_not_recover_some_other_task(self):
        win = self._win()
        self._filmed()
        with mock.patch.object(CB.config, "RUNS_DIR", self.tmp):
            self.assertIsNone(win._studio_reel_in({"design": "https://chatgpt.com/c/unknown"}))

    def _links(self, mp4, design=True):
        links = {"content": "https://chatgpt.com/c/1", "media": mp4}
        if design:
            links["design"] = "https://chatgpt.com/c/2"
        return links

    def test_the_change_is_asked_in_the_design_conversation(self):
        win = self._win()
        mp4 = self._filmed()
        win._stage_agents = {"content": "ChatGPT", "design": "ChatGPT",
                             "media": "Prism Studio"}
        studio, classifier, auto = self._offer(
            win, {"content": ["script"], "design": ["look"], "media": ["filmed"]},
            self._links(mp4), text="make scene 1 warmer")
        self.assertTrue(studio.called)
        auto.assert_not_called()
        cfg, spec, agent, url, change, atts = studio.call_args[0]
        self.assertEqual(url, "https://chatgpt.com/c/2")
        self.assertEqual(agent, "ChatGPT")
        self.assertEqual(change, "make scene 1 warmer")
        self.assertEqual(spec["scenes"][0]["html"], "<p>x</p>")

    def test_naming_another_tool_still_wins(self):
        win = self._win()
        mp4 = self._filmed()
        win._stage_agents = {"content": "Claude", "design": "ChatGPT",
                             "media": "Prism Studio"}
        studio, classifier, auto = self._offer(
            win, {"content": ["script"], "design": ["look"], "media": ["filmed"]},
            self._links(mp4), text="ask Claude to shorten the script")
        studio.assert_not_called()
        self.assertTrue(auto.called)
        self.assertEqual(auto.call_args.kwargs["custom_stages"][0][0], "content")

    def test_without_a_saved_design_tab_the_classifier_decides(self):
        win = self._win()
        mp4 = self._filmed()
        win._stage_agents = {"content": "ChatGPT", "media": "Prism Studio"}
        studio, classifier, _ = self._offer(
            win, {"content": ["script"], "media": ["filmed"]},
            self._links(mp4, design=False), text="make it warmer")
        studio.assert_not_called()
        self.assertTrue(classifier.called)

    def test_a_quick_reel_is_not_a_studio_reel(self):
        """The template renderer's spec carries no HTML; nothing to ask a
        design chat for."""
        win = self._win()
        mp4 = os.path.join(self.tmp, "reel_2.mp4")
        open(mp4, "wb").close()
        with open(os.path.join(self.tmp, "reel_2.json"), "w", encoding="utf-8") as f:
            json.dump({"scenes": [{"type": "statement", "lines": ["Hi"]}]}, f)
        win._stage_agents = {"content": "ChatGPT", "design": "ChatGPT"}
        studio, classifier, _ = self._offer(
            win, {"content": ["script"]}, {"content": "https://c/1",
                                           "design": "https://c/2",
                                           "media": mp4}, text="warmer")
        studio.assert_not_called()
        self.assertTrue(classifier.called)


class FromHistory(FollowupBase):
    """A past run's record holds everything a follow-up session is made of,
    so History can start one — a reel's goes to its design chat as well."""

    def _record(self, mp4=None, agents=True):
        rec = {"query": "make a reel for instagram",
               "responses": {"content": ["script"], "design": ["look"],
                             "media": ["filmed"]},
               "links": {"content": "https://chatgpt.com/c/1",
                         "design": "https://chatgpt.com/c/2"}}
        if agents:
            rec["agents"] = {"content": "ChatGPT", "design": "ChatGPT",
                             "media": "Prism Studio"}
        if mp4:
            rec["links"]["media"] = mp4
        return rec

    def _history(self):
        from dialogs.history_dialog import HistoryDialog
        with mock.patch.object(CB.config, "load", return_value={}):
            return HistoryDialog(None)

    def _item(self, name, record):
        from PySide6.QtWidgets import QListWidgetItem
        from dialogs.history_dialog import _PATH_ROLE
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f)
        item = QListWidgetItem()
        item.setData(_PATH_ROLE, path)
        return item

    def test_the_dialog_offers_a_follow_up_for_a_run_with_output(self):
        d = self._history()
        d._show(self._item("run_9.json", self._record()))
        self.assertTrue(d.follow_up_btn.isVisibleTo(d))
        seen = []
        d.follow_up.connect(seen.append)
        with mock.patch.object(d, "accept") as accept:
            d._follow_up_current()
        accept.assert_called_once()
        self.assertEqual(seen[0]["query"], "make a reel for instagram")

    def test_a_run_with_no_output_offers_none(self):
        d = self._history()
        d._show(self._item("run_10.json", {"query": "x", "responses": {},
                                           "links": {}}))
        self.assertFalse(d.follow_up_btn.isVisibleTo(d))
        d._follow_up_current()            # nothing to emit, must not raise

    def test_the_window_rebuilds_the_session_from_the_record(self):
        win = self._win(query="something else entirely")
        win._followup_session = {"query": "something else entirely",
                                 "responses": {"brains": ["old"]},
                                 "links": {"brains": "https://old"},
                                 "agents": {"brains": "ChatGPT"}}
        record = self._record(self._filmed())
        studio, classifier, _ = self._offer(
            win, None, None, text="make scene 1 warmer",
            call=lambda: win._follow_up_from_history(record))
        self.assertTrue(studio.called)
        self.assertEqual(studio.call_args[0][3], "https://chatgpt.com/c/2")
        self.assertEqual(win._last_query, "make a reel for instagram")
        self.assertNotIn("brains", win._followup_links, "the record is the truth")

    def test_an_old_record_without_agents_uses_the_configured_tools(self):
        win = self._win()
        record = self._record(agents=False)
        with mock.patch.object(CB.config, "active_agents",
                               return_value={"content": "Claude",
                                             "design": "ChatGPT"}):
            _, _, auto = self._offer(
                win, None, None, text="ask Claude to shorten the script",
                call=lambda: win._follow_up_from_history(record))
        self.assertTrue(auto.called)
        stage, agent, _ = auto.call_args.kwargs["custom_stages"][0]
        self.assertEqual((stage, agent), ("content", "Claude"))

    def test_a_follow_up_from_history_attaches_that_runs_files_only(self):
        """The record remembers its own run folder; the dialog shows and
        attaches what THAT run produced — not every file ever made under the
        same words, which is what filing by task text did."""
        import main_window
        this_run = os.path.join(self.tmp, "runs", "2026-09-07 16-18")
        other_run = os.path.join(self.tmp, "runs", "2026-09-03 12-52")
        for d in (this_run, other_run):
            os.makedirs(d)
            with open(os.path.join(d, "Reel.mp4"), "wb") as f:
                f.write(b"\x00")
        with open(os.path.join(this_run, CB.config.ABOUT_FILE), "w") as f:
            f.write("about")
        record = self._record()
        record["artifacts"] = this_run
        win = self._win()
        seen = {}

        class Dialog(_dialog("")):
            def __init__(self, *a, **k):
                seen["artifacts"] = list(k.get("artifacts") or [])
        with mock.patch("dialogs.followup_dialog.FollowupDialog", Dialog):
            win._follow_up_from_history(record)
        self.assertEqual(seen["artifacts"], [os.path.join(this_run, "Reel.mp4")])

    def test_the_run_record_remembers_its_folder(self):
        win = self._win()
        # Production writes artifacts to Desktop; tests must not assume the
        # runner has a writable Desktop (CI and sandboxes usually do not).
        old_dir = CB.config.ARTIFACTS_DIR
        CB.config.ARTIFACTS_DIR = self.art
        try:
            folder = CB.config.begin_run("make a reel for instagram")
            with mock.patch.object(CB.config, "save_run") as saved:
                win._save_run({"content": ["x"]}, {})
            self.assertEqual(saved.call_args[0][0]["artifacts"], folder)
        finally:
            CB.config.ARTIFACTS_DIR = old_dir

    def test_history_is_wired_from_both_entrances(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "main_window.py"), encoding="utf-8").read()
        self.assertIn("dialog.follow_up.connect(self._follow_up_from_history)", src)
        self.assertIn("self._history_dialog().exec()", src)


class TheFollowupWaitsLonger(FollowupBase):
    """A follow-up redoes a whole deliverable; the tool's everyday budget
    (ChatGPT: 300s) was cutting those off mid-way."""

    def test_the_ceiling(self):
        from core import automation as AU
        self.assertEqual(AU.followup_wait({"wait_time": 300}), 480)
        self.assertEqual(AU.followup_wait({"wait_time": 600}), 600)
        self.assertEqual(AU.followup_wait({}), 480)

    def test_a_follow_up_run_asks_the_engine_for_it(self):
        from workers import AutomationWorker
        w = AutomationWorker({}, {"agents": {}}, [], "q",
                             custom_stages=[("content", "ChatGPT", ["x"])],
                             followup=True)
        fake = mock.MagicMock()
        fake.run.return_value = ({}, {})
        fake.FOLLOWUP_MIN_WAIT = 480
        with mock.patch.object(CB, "automation_available", return_value=(True, "")), \
             mock.patch.object(CB, "get_automation", return_value=fake):
            w.run()
        self.assertEqual(fake.run.call_args.kwargs["min_wait"], 480)
        plain = AutomationWorker({}, {"agents": {}}, [], "q",
                                 custom_stages=[("content", "ChatGPT", ["x"])])
        with mock.patch.object(CB, "automation_available", return_value=(True, "")), \
             mock.patch.object(CB, "get_automation", return_value=fake):
            plain.run()
        self.assertNotIn("min_wait", fake.run.call_args.kwargs)

    def test_the_workbench_marks_its_follow_up_runs(self):
        win = self._win()
        win._stage_agents = {"content": "Claude"}
        _, _, auto = self._offer(win, {"content": ["copy"]},
                                 {"content": "https://claude/2"},
                                 text="ask Claude to shorten it")
        self.assertTrue(auto.call_args.kwargs["followup"])


if __name__ == "__main__":
    unittest.main()
