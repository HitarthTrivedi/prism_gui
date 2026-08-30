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
        self.assertIn("make me a poster of a spring",
                      os.path.basename(os.path.dirname(dest)))

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
