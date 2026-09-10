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

    def test_the_tools_own_filename_is_kept_after_the_runs_label(self):
        """A harvested "Quotation - JK Cement.xlsx" used to be filed as
        "<task> — Content.xlsx": the run's label survived, the name the
        customer asked for did not. Both now."""
        dest = self.CFG.save_artifact(self._src.name, "quote the OBMS job",
                                      kind="content", task="quote the OBMS job",
                                      name="Quotation - JK Cement.xlsx")
        base = os.path.basename(dest)
        self.assertIn("Content", base)
        self.assertIn("Quotation - JK Cement", base)
        self.assertTrue(base.endswith(".png"), "the extension is the real file's")
        # No name: exactly as before.
        plain = self.CFG.save_artifact(self._src.name, "quote the OBMS job",
                                       kind="content", task="quote the OBMS job")
        self.assertNotIn("—  ", os.path.basename(plain))

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

    def test_inside_a_run_the_file_is_named_by_the_job_and_its_kind(self):
        self.CFG.begin_run("the nova launch")
        a = self.CFG.save_artifact(self._src.name, "the nova launch", kind="artwork",
                                   task="the nova launch")
        b = self.CFG.save_artifact(self._src.name, "the nova launch", kind="artwork",
                                   task="the nova launch")
        self.assertEqual(os.path.basename(a), "the nova launch — Artwork.png")
        self.assertEqual(os.path.basename(b), "the nova launch — Artwork 2.png")

    def test_a_titled_run_is_filed_and_named_by_its_title(self):
        folder = self.CFG.begin_run("make a reel for instgram for this brand",
                                    title="Instagram reel · brand guide")
        self.assertEqual(os.path.basename(os.path.dirname(folder)),
                         "Instagram reel · brand guide")
        a = self.CFG.save_artifact(self._src.name, "x", kind="reel",
                                   task="make a reel for instgram for this brand")
        self.assertEqual(os.path.basename(a), "Instagram reel · brand guide — Reel.png")
        with open(os.path.join(folder, self.CFG.ABOUT_FILE), encoding="utf-8") as f:
            about = f.read()
        self.assertIn("Instagram reel · brand guide", about)
        self.assertIn("make a reel for instgram for this brand", about)
        self.assertEqual(self.CFG.current_run_title(), "Instagram reel · brand guide")

    def test_the_fallback_title_is_the_first_words_never_cut_on_a_joining_word(self):
        self.assertEqual(self.CFG.fallback_title("make a reel for instgram for this brand"),
                         "make a reel for instgram for this brand")
        self.assertEqual(self.CFG.fallback_title("make me a poster of a spring"),
                         "make me a poster of a spring")
        self.assertEqual(self.CFG.fallback_title("can we make a platform like github but "
                                                  "more personalized for developers"),
                         "can we make a platform like github")
        self.assertEqual(self.CFG.fallback_title("write it up for the board and for "
                                                  "the auditors and the bank"),
                         "write it up for the board")
        self.assertEqual(self.CFG.fallback_title(""), "Task")

    def test_a_models_title_is_tidied(self):
        self.assertEqual(self.CFG.tidy_title('  "Instagram Reel — Brand Guide." '),
                         "Instagram Reel — Brand Guide")
        self.assertEqual(self.CFG.tidy_title("Two\nlines"), "Two")
        self.assertEqual(len(self.CFG.tidy_title("x" * 90)), 60)

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


class TheFolderThatCanBeWritten(unittest.TestCase):
    """artifacts_root(): the Desktop folder when it can be written, and a
    findable fallback -- said out loud -- when it cannot. "Studio makes
    artwork on Linux but not on my Mac": the pictures were made, the copy
    to ~/Desktop was refused (macOS folder permission), and nothing said
    so. On Windows with OneDrive the Desktop is not ~/Desktop at all."""

    def setUp(self):
        from core import config as CFG
        self.CFG = CFG
        self._real = (CFG.ARTIFACTS_DIR, CFG.FALLBACK_ARTIFACTS_DIR,
                      dict(CFG._root_cache))
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        (self.CFG.ARTIFACTS_DIR, self.CFG.FALLBACK_ARTIFACTS_DIR, cache) = self._real
        self.CFG._root_cache.clear()
        self.CFG._root_cache.update(cache)
        self._tmp.cleanup()

    def test_the_desktop_folder_is_used_when_it_can_be_written(self):
        want = os.path.join(self._tmp.name, "Desktop", "Prism Artifacts")
        self.CFG.ARTIFACTS_DIR = want
        self.assertEqual(self.CFG.artifacts_root(), want)
        self.assertTrue(os.path.isdir(want))
        self.assertEqual(os.listdir(want), [], "the write probe leaves nothing behind")

    def test_an_unwritable_desktop_falls_back_to_the_home_folder_and_says_so(self):
        from unittest import mock
        blocker = os.path.join(self._tmp.name, "Desktop")
        with open(blocker, "w") as f:          # a FILE where the folder should be
            f.write("no")
        self.CFG.ARTIFACTS_DIR = os.path.join(blocker, "Prism Artifacts")
        fallback = os.path.join(self._tmp.name, "home", "Prism Artifacts")
        self.CFG.FALLBACK_ARTIFACTS_DIR = fallback
        said = []
        from core import ui
        with mock.patch.object(ui, "warn", said.append):
            root = self.CFG.artifacts_root()
            again = self.CFG.artifacts_root()
        self.assertEqual(root, fallback)
        self.assertEqual(again, fallback)
        self.assertTrue(os.path.isdir(fallback))
        self.assertEqual(len(said), 1, "decided once, said once")
        self.assertIn("instead", said[0])
        # And everything filed from here on lands in the fallback.
        dest = self.CFG.save_artifact(__file__, "x", kind="visual", task="a task")
        self.assertTrue(dest.startswith(fallback))

    def test_windows_asks_the_shell_where_the_desktop_is(self):
        import sys
        import types
        from unittest import mock
        moved = os.path.join(self._tmp.name, "OneDrive", "Desktop")
        os.makedirs(moved)

        fake = types.ModuleType("winreg")
        fake.HKEY_CURRENT_USER = object()
        fake.OpenKey = lambda root, sub: "key"
        fake.QueryValueEx = lambda key, name: (moved, 1)
        with mock.patch.dict(sys.modules, {"winreg": fake}), \
                mock.patch.object(self.CFG.os, "name", "nt"):
            self.assertEqual(self.CFG._desktop_dir(), moved)

    def test_off_windows_the_desktop_is_under_home(self):
        self.assertEqual(self.CFG._desktop_dir(),
                         os.path.join(os.path.expanduser("~"), "Desktop"))
