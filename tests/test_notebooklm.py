"""NotebookLM makes the video (or the podcast) from the run's own material.

The owner's run of 13 Sep 2026 -- "summarize this all in one ideation and
generate me a google notebook lm video" -- opened NotebookLM, created an
empty notebook and typed nothing: the runner looked for "Copied text"
without pressing "Add source" first, and NotebookLM was not offered for
the video step at all. Pinned here, against the UI read live that day
(see the notes above _run_notebooklm):

  · NotebookLM is a choice for the Video & Reels step, a maker, with no
    upload field (it takes its files as pasted sources);
  · the person's words decide video vs audio, over the step;
  · long-form is the default: a video is an Explainer unless the words
    say short; an audio is Long when the words say so;
  · the sources are every earlier step's FULL answer and every readable
    attachment -- not the four-line hand-off;
  · the render wait ends on "generating" turning into a listed item, or on
    a Stop, never on a hang;
  · the run passes the runner what it needs and keeps the file it saved.

No browser: drivers are fakes, the rest is source inspection.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import agents as A          # noqa: E402
from core import automation as AU     # noqa: E402

OWNER = "summarize this all in one ideation and generate me a google notebook lm video"


class WhereNotebookLMIsOffered(unittest.TestCase):

    def test_it_is_a_video_tool_and_still_an_audio_tool(self):
        self.assertIn("NotebookLM", A.CATEGORIES["media"]["agents"])
        self.assertIn("NotebookLM", A.CATEGORIES["audio"]["agents"])

    def test_it_is_a_maker_that_produces_video(self):
        cfg = A.AGENT_REGISTRY["NotebookLM"]
        self.assertTrue(A.is_maker(cfg))
        self.assertIn("video", A.profile_for("NotebookLM").get("produces", ()))

    def test_the_page_moved_and_has_no_upload_field(self):
        cfg = A.AGENT_REGISTRY["NotebookLM"]
        self.assertEqual(cfg["url"], "https://notebook.google.com")
        self.assertEqual(cfg["upload_selector"], "")
        self.assertIn("Query box", cfg["textarea_selector"])
        self.assertGreaterEqual(int(cfg["generate_wait"]), 900)

    def test_an_empty_upload_selector_means_no_upload_and_no_warning(self):
        class Driver:
            def __getattr__(self, name):
                raise AssertionError(f"the driver must not be touched ({name})")
        n = AU._upload_files(Driver(), {"upload_selector": ""}, [{"path": "/x.pdf"}], "NotebookLM")
        self.assertEqual(n, 0)


class WhatToMake(unittest.TestCase):

    def test_the_persons_words_win_over_the_step(self):
        line = "Create a clear voice-over audio file for the video script."
        self.assertEqual(AU._nb_wants("audio", line, OWNER), "video")
        self.assertEqual(AU._nb_wants("media", "make the video", "turn this into a podcast"), "audio")

    def test_the_step_decides_when_the_words_do_not(self):
        self.assertEqual(AU._nb_wants("media", "", "summarise everything"), "video")
        self.assertEqual(AU._nb_wants("audio", "", "summarise everything"), "audio")
        self.assertEqual(AU._nb_wants("brains", "For this step: answer the question", "summarise"), "chat")
        self.assertEqual(AU._nb_wants("brains", "For this step: make a video", ""), "video")

    def test_long_form_is_the_default(self):
        self.assertEqual(AU._nb_format("video", "", OWNER), ("Explainer", ""))
        self.assertEqual(AU._nb_format("video", "", "a short reel from this"), ("Short", ""))
        self.assertEqual(AU._nb_format("video", "", "a long form video, not a short"), ("Explainer", ""))
        self.assertEqual(AU._nb_format("audio", "", "a long podcast"), ("Deep Dive", "Long"))
        self.assertEqual(AU._nb_format("audio", "", "a quick brief"), ("Deep Dive", "Short"))
        self.assertEqual(AU._nb_format("audio", "", "a podcast"), ("Deep Dive", ""))

    def test_the_focus_is_the_words_then_the_bare_line(self):
        focus = AU._nb_focus("For this step: make the video from the summary.", OWNER)
        self.assertTrue(focus.startswith(OWNER))
        self.assertIn("make the video from the summary.", focus)
        self.assertNotIn("For this step", focus)
        self.assertLessEqual(len(AU._nb_focus("x" * 5000, "y" * 5000)), 1500)


class TheSourcesAreTheMaterial(unittest.TestCase):

    def test_full_answers_and_readable_attachments(self):
        prior = [("brains", ["first answer " * 50]), ("content", ["", "the script"])]
        atts = [{"name": "a.pdf", "text": "pdf text"}, {"name": "pic.png", "text": ""},
                {"path": "/tmp/b.md", "text": "notes"}]
        sources, unreadable = AU._nb_sources(prior, atts)
        self.assertEqual([t for t, _ in sources],
                         ["Prism — Think it through", "Prism — Write it up", "a.pdf", "b.md"])
        self.assertIn("first answer", sources[0][1])
        self.assertEqual(sources[1][1], "the script")
        self.assertEqual(unreadable, ["pic.png"])

    def test_nothing_in_nothing_out(self):
        self.assertEqual(AU._nb_sources([], []), ([], []))
        self.assertEqual(AU._nb_sources([("brains", ["  "])], None), ([], []))


class _Driver:
    def __init__(self, states):
        self.states = list(states)

    def execute_script(self, js, *a):
        # The last state holds: a page that says "generating" keeps saying
        # it until the render is done.
        return self.states.pop(0) if len(self.states) > 1 else (self.states[0] if self.states else {})


class TheRenderWait(unittest.TestCase):

    def test_generating_then_listed_is_done(self):
        d = _Driver([{"generating": True}, {"generating": True}, {"generating": False}])
        self.assertTrue(AU._nb_wait_generated(d, cap=30, halted=lambda: False, poll=0))

    def test_a_new_menu_or_download_is_done(self):
        d = _Driver([{"generating": False, "menus": 1}, {"generating": False, "menus": 2}])
        self.assertTrue(AU._nb_wait_generated(d, cap=30, halted=lambda: False,
                                              baseline_menus=1, poll=0))
        d = _Driver([{"generating": False, "downloads": 1}])
        self.assertTrue(AU._nb_wait_generated(d, cap=30, halted=lambda: False, poll=0))

    def test_a_stop_ends_it(self):
        d = _Driver([{"generating": True}] * 5)
        self.assertFalse(AU._nb_wait_generated(d, cap=30, halted=lambda: True, poll=0))

    def test_the_cap_ends_it(self):
        d = _Driver([{"generating": True}])
        self.assertFalse(AU._nb_wait_generated(d, cap=0.05, halted=lambda: False, poll=0))


class WiredIntoTheRun(unittest.TestCase):

    def test_the_runner_gets_sources_the_words_and_the_stop_hook(self):
        src = inspect.getsource(AU.run)
        self.assertIn("_nb_sources(prior, send_files)", src)
        i = src.index("stage_responses, nb_files = _run_notebooklm(")
        call = src[i:i + 400]
        for arg in ("sources=nb_sources", "query=query", "should_stop=stage_halt"):
            self.assertIn(arg, call)
        self.assertNotIn("nb_prompt", src, "the old prompt-as-source path is gone")

    def test_the_file_it_saved_is_kept_and_handed_on(self):
        src = inspect.getsource(AU.run)
        self.assertIn("_save_artifacts(nb_files, query, stage", src)
        self.assertIn("pipeline_files[:] = (pipeline_files + nb_files)[-6:]", src)

    def test_the_runner_presses_add_source_before_looking_for_copied_text(self):
        src = inspect.getsource(AU._nb_add_text_source)
        self.assertLess(src.index("aria-label='Add source'"), src.index('"copied text"'))
        self.assertIn("aria-label='Pasted text'", src)
        self.assertIn("'Insert'", src)

    def test_the_customize_dialog_is_driven_by_what_the_page_showed(self):
        src = inspect.getsource(AU._nb_generate)
        for needle in (".option-icon", "'Generate now'", "@role='radio'", "label[starts-with"):
            self.assertIn(needle, src)

    def test_the_generic_download_capture_is_shared(self):
        self.assertTrue(callable(AU._capture_download))
        src = inspect.getsource(AU._harvest_via_download)
        self.assertIn("_capture_download(driver, stage", src)
        self.assertIn("_capture_download(driver, stage, click", inspect.getsource(AU._nb_download))


if __name__ == "__main__":
    unittest.main()
