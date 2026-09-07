"""save_artifact()/artifact_task_dir() — grouping one task's output into one
folder under Artifacts, instead of every run's files landing loose together.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)


class GroupingByTask(unittest.TestCase):

    def setUp(self):
        from core import config as CFG
        self.CFG = CFG
        self._real_dir = CFG.ARTIFACTS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        CFG.ARTIFACTS_DIR = self._tmp.name
        self._src = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        self._src.write(b"fake image bytes")
        self._src.close()

    def tearDown(self):
        self.CFG.ARTIFACTS_DIR = self._real_dir
        self._tmp.cleanup()
        os.unlink(self._src.name)

    def test_no_task_lands_at_the_top_level_as_before(self):
        dest = self.CFG.save_artifact(self._src.name, "a poster", kind="visual")
        self.assertEqual(os.path.dirname(dest), self._tmp.name)
        self.assertTrue(os.path.isfile(dest))

    def test_a_task_creates_its_own_subfolder(self):
        dest = self.CFG.save_artifact(self._src.name, "a poster", kind="visual",
                                      task="make me a poster of a spring")
        self.assertNotEqual(os.path.dirname(dest), self._tmp.name)
        self.assertTrue(os.path.isfile(dest))
        # Task folder, then a run folder inside it: <task>/<stamp>/<file>.
        run_dir = os.path.dirname(dest)
        self.assertIn("make me a poster of a spring",
                      os.path.basename(os.path.dirname(run_dir)))
        self.assertRegex(os.path.basename(run_dir), r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2}")

    def test_running_the_same_task_again_gets_a_new_folder(self):
        """"Use again", a re-film, a follow-up: the same words, a new run —
        not the same pile. Twelve files from four runs was the bug."""
        first = self.CFG.begin_run("make a reel for instgram for this brand")
        a = self.CFG.save_artifact(self._src.name, "x", kind="reel",
                                   task="make a reel for instgram for this brand")
        second = self.CFG.begin_run("make a reel for instgram for this brand")
        b = self.CFG.save_artifact(self._src.name, "x", kind="reel",
                                   task="make a reel for instgram for this brand")
        self.assertNotEqual(first, second)
        self.assertEqual(os.path.dirname(a), first)
        self.assertEqual(os.path.dirname(b), second)
        self.assertEqual(os.path.dirname(first), os.path.dirname(second),
                         "both runs sit under the one task folder")
        self.assertEqual(self.CFG.current_run_dir(), second)

    def test_a_run_folder_says_what_it_is(self):
        folder = self.CFG.begin_run("make a reel for instgram for this brand")
        about = os.path.join(folder, self.CFG.ABOUT_FILE)
        self.assertTrue(os.path.isfile(about))
        with open(about, encoding="utf-8") as f:
            self.assertIn("make a reel for instgram for this brand", f.read())

    def test_inside_a_run_the_file_is_named_by_kind(self):
        self.CFG.begin_run("the nova launch")
        a = self.CFG.save_artifact(self._src.name, "the nova launch", kind="artwork",
                                   task="the nova launch")
        b = self.CFG.save_artifact(self._src.name, "the nova launch", kind="artwork",
                                   task="the nova launch")
        self.assertEqual(os.path.basename(a), "Artwork.png")
        self.assertEqual(os.path.basename(b), "Artwork 2.png")

    def test_a_caller_that_never_announced_its_run_still_gets_a_folder(self):
        self.CFG.begin_run("")
        dest = self.CFG.save_artifact(self._src.name, "x", kind="boq",
                                      task="quote for RS Infotech")
        self.assertRegex(os.path.basename(os.path.dirname(dest)),
                         r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2}")
        self.assertEqual(self.CFG.current_run_dir(), os.path.dirname(dest))

    def test_two_artifacts_from_the_same_task_share_a_folder(self):
        first = self.CFG.save_artifact(self._src.name, "a poster", kind="visual",
                                       task="the nova launch")
        second = self.CFG.save_artifact(self._src.name, "a caption", kind="content",
                                        task="the nova launch")
        self.assertEqual(os.path.dirname(first), os.path.dirname(second))

    def test_different_tasks_get_different_folders(self):
        first = self.CFG.save_artifact(self._src.name, "a poster", kind="visual",
                                       task="task one")
        second = self.CFG.save_artifact(self._src.name, "a poster", kind="visual",
                                        task="task two")
        self.assertNotEqual(os.path.dirname(first), os.path.dirname(second))

    def test_task_dir_is_created_even_with_no_artifact_yet(self):
        folder = self.CFG.artifact_task_dir("a job with no output yet")
        self.assertTrue(os.path.isdir(folder))

    def test_an_empty_task_is_the_top_level_directory_itself(self):
        self.assertEqual(self.CFG.artifact_task_dir(""), self._tmp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
