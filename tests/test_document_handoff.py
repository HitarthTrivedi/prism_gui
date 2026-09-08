"""
Passing a produced DOCUMENT to the next agent
─────────────────────────────────────────────
The pipeline had two channels between stages and they were very unequal:

  · text  — the previous stage's reply, capped at 8000 chars
  · files — `_harvest_images()`, which reads <img> elements

So a picture reached the next agent and a deck did not. A .pptx, .docx or
.xlsx an agent produces is a DOWNLOAD, not something on the page, and there
was no download handling in the module at all: no download directory, no wait
for one to finish, nothing looking for new files. The next stage received the
model's prose ABOUT the file, and the file itself existed in one browser tab
and nowhere else.

Two more holes went with it:

  · `presentation` and `development` were in the list of stages that RECEIVE
    generated files but not in the list that can CONTRIBUTE one, so a deck
    builder was a dead end by construction.
  · a LOCAL stage — Prism's own reel/BOQ/studio — wrote a real file to this
    disk and passed on only a one-line note about it. The easiest case there
    is, and the one that was missed.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prism_terminal"))

from core import automation  # noqa: E402


class HarvestingWhatAStageDownloaded(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, body: bytes = b"x" * 64) -> str:
        path = os.path.join(self.folder, name)
        with open(path, "wb") as f:
            f.write(body)
        return path

    def test_a_deck_is_picked_up(self):
        self._write("Quarterly Review.pptx")
        found = automation._harvest_downloads(self.folder, set(), "presentation")
        self.assertEqual([f["name"] for f in found], ["Quarterly Review.pptx"])

    def test_documents_and_spreadsheets_too(self):
        for name in ("Report.docx", "Costing.xlsx", "Brief.pdf"):
            self._write(name)
        found = automation._harvest_downloads(self.folder, set(), "format")
        self.assertEqual(len(found), 3)

    def test_it_is_marked_as_generated_not_as_the_customers_own_file(self):
        """A logo the client owns and a picture a model drew are not
        interchangeable, and neither are their documents."""
        self._write("Deck.pptx")
        found = automation._harvest_downloads(self.folder, set(), "presentation")
        self.assertTrue(found[0]["_generated"])
        self.assertEqual(found[0]["_stage"], "presentation")

    def test_a_half_written_download_is_never_handed_on(self):
        """Chrome writes .crdownload while the file is still arriving. Handing
        that to the next agent gives it a corrupt file, which is worse than
        giving it nothing."""
        self._write("Deck.pptx.crdownload")
        with mock.patch.object(automation, "_wait_for_downloads"):
            found = automation._harvest_downloads(self.folder, set(), "presentation")
        self.assertEqual(found, [])

    def test_an_empty_file_is_not_a_deliverable(self):
        self._write("Empty.pptx", b"")
        found = automation._harvest_downloads(self.folder, set(), "presentation")
        self.assertEqual(found, [])

    def test_a_file_is_handed_on_once_not_by_every_later_stage(self):
        self._write("Deck.pptx")
        seen = set()
        first = automation._harvest_downloads(self.folder, seen, "presentation")
        second = automation._harvest_downloads(self.folder, seen, "review")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [], "the same deck must not re-upload for ever")

    def test_a_previous_runs_output_is_not_adopted(self):
        """The folder persists between runs. Yesterday's deck is not this
        run's work."""
        self._write("Yesterdays.pptx")
        already = {os.path.join(self.folder, n) for n in os.listdir(self.folder)}
        self._write("Todays.pptx")
        found = automation._harvest_downloads(self.folder, already, "presentation")
        self.assertEqual([f["name"] for f in found], ["Todays.pptx"])

    def test_the_text_comes_with_it(self):
        """attach() extracts what it can, so a reasoning stage that cannot
        open a document still gets its words."""
        path = self._write("Notes.txt", b"the agreed scope is 5000 units")
        found = automation._harvest_downloads(self.folder, set(), "research")
        self.assertIn("5000 units", found[0]["text"])

    def test_a_missing_folder_is_not_a_crash(self):
        self.assertEqual(
            automation._harvest_downloads(
                os.path.join(self.folder, "nope"), set(), "x"), [])

    def test_an_unreadable_file_does_not_take_the_run_down(self):
        self._write("Deck.pptx")
        with mock.patch("core.files.attach", side_effect=OSError("locked")), \
                mock.patch.object(automation.ui, "warn") as warned:
            found = automation._harvest_downloads(self.folder, set(), "x")
        self.assertEqual(found, [])
        self.assertTrue(warned.called, "silently losing it is the bug")

    def test_it_does_not_hand_on_an_unbounded_pile(self):
        for i in range(12):
            self._write(f"file{i}.pptx")
        found = automation._harvest_downloads(self.folder, set(), "x")
        self.assertLessEqual(len(found), automation.MAX_HANDOFF_FILES)


class WaitingForTheDownloadToFinish(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_arriving_file_is_detected(self):
        with open(os.path.join(self.tmp.name, "a.pptx.crdownload"), "w") as f:
            f.write("...")
        self.assertTrue(automation._downloads_in_flight(self.tmp.name))

    def test_a_finished_folder_is_not(self):
        with open(os.path.join(self.tmp.name, "a.pptx"), "w") as f:
            f.write("...")
        self.assertFalse(automation._downloads_in_flight(self.tmp.name))

    def test_waiting_returns_as_soon_as_it_settles(self):
        started = time.monotonic()
        automation._wait_for_downloads(self.tmp.name, timeout=5)
        self.assertLess(time.monotonic() - started, 2,
                        "an empty folder must not be waited on")

    def test_a_stuck_download_gives_up_and_says_so(self):
        with open(os.path.join(self.tmp.name, "a.pptx.crdownload"), "w") as f:
            f.write("...")
        with mock.patch.object(automation.ui, "warn") as warned:
            automation._wait_for_downloads(self.tmp.name, timeout=1)
        self.assertTrue(warned.called,
                        "carrying on silently hides why a file is missing")


class ChromeIsToldWhereToPutThem(unittest.TestCase):
    """None of the above can work if the download lands in the customer's own
    Downloads folder, which is where it went."""

    def test_a_download_directory_is_configured(self):
        import inspect
        source = inspect.getsource(automation._setup_chrome_driver)
        self.assertIn("download.default_directory", source)
        self.assertIn("download.prompt_for_download", source)

    def test_and_again_over_the_devtools_protocol(self):
        """undetected-chromedriver rebuilds its options object in places, and
        a download that quietly goes elsewhere is invisible rather than
        noisy."""
        import inspect
        source = inspect.getsource(automation._setup_chrome_driver)
        self.assertIn("Page.setDownloadBehavior", source)

    def test_it_is_not_the_customers_downloads_folder(self):
        self.assertIn(".prism", automation.DOWNLOAD_DIR)


class TheRunLoopPassesThemOn(unittest.TestCase):
    """Read from the source of run(), because standing a whole pipeline up
    needs a browser. Each assertion names a specific wiring that was absent."""

    def setUp(self):
        import inspect
        self.source = inspect.getsource(automation.run)

    def test_every_stage_is_checked_for_downloads_not_only_image_stages(self):
        self.assertIn("_harvest_downloads(DOWNLOAD_DIR, downloaded, stage)",
                      self.source)

    def test_what_a_stage_made_is_uploaded_to_the_next_one(self):
        self.assertIn("handoff_files", self.source)
        self.assertIn("(pipeline_files if producer else []) + \\", self.source)

    def test_the_same_file_is_not_uploaded_twice(self):
        self.assertIn('{f["path"]: f for f in send_files}', self.source)

    def test_the_handoff_is_one_hop_only(self):
        """Left set, a deck from stage 2 would still be uploading at stage 5."""
        self.assertIn("handoff_files = fresh_files", self.source)

    def test_a_local_stages_file_is_passed_on_too(self):
        """Prism's own reel/BOQ/studio write a real file and used to hand on
        a one-line note about it."""
        self.assertIn("record[\"_generated\"] = True", self.source)
        self.assertIn("handoff_files = [record]", self.source)

    def test_the_next_agent_is_told_what_the_file_is(self):
        """Handed an unexplained .pptx, a tool summarises it back instead of
        continuing it."""
        self.assertIn("PRODUCED", self.source)
        self.assertIn("build on what is already there", self.source)

    def test_the_deliverable_is_reported_so_it_is_not_lost_with_the_tab(self):
        self.assertIn('"files": [{"name": f["name"], "path": f["path"]}',
                      self.source)

    def test_a_run_does_not_adopt_the_previous_runs_downloads(self):
        self.assertIn("downloaded = {os.path.join(DOWNLOAD_DIR, n)", self.source)


if __name__ == "__main__":
    unittest.main()
