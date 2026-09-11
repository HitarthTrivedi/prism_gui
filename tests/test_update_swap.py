"""The update that downloads, restarts, and is still the old version.

Three causes, all on the swap step, and none of them left a trace:

1. On Windows the swap helper was Prism.exe itself, started from inside the
   folder it then tried to rename. Windows refuses that while an executable
   in the folder is running, so no Windows in-app update could ever swap.
2. The new version was recorded as "seen" when it finished DOWNLOADING, so a
   swap that then failed made the next check report "nothing newer" and send
   the customer to the browser — the "takes me to GitHub" report.
3. Staging under ~/.prism/updates meant the final rename crossed volumes for
   a portable install on another drive, and failed.

Plus the one that hid all three: the helper wrote no log.

And what review of the first fix found: a copy-and-delete fallback that ran
on ANY failed rename would delete most of a live install when one file was
locked; a script that inherited Prism's own working folder could not move
that folder either.

The Windows script is checked by reading what it will do; it cannot be run
here. Everything else runs for real on this machine.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("PRISM_APPLY_LOG", os.path.join(
    tempfile.mkdtemp(prefix="prism-apply-log-"), "update-apply.log"))

import apply_update as AU   # noqa: E402
import updater              # noqa: E402


def _tree(root: str, marker: str) -> None:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "marker.txt"), "w") as f:
        f.write(marker)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


class TheWindowsSwapRunsFromOutsideTheFolder(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-swap-win-")
        self.install = os.path.join(self.tmp, "Prism")
        self.staged = os.path.join(self.tmp, ".prism-update-staging", "1.5.7")
        self.backup = self.install + ".old"
        self.exe = os.path.join(self.install, "Prism.exe")
        helper_dir = os.path.join(self.tmp, "home", ".prism", "updates")
        patcher = mock.patch.object(AU, "_windows_helper_dir", return_value=helper_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def script(self) -> str:
        return AU.write_windows_helper(4242, self.install, self.staged,
                                       self.backup, self.exe)

    def test_the_script_does_not_live_in_the_folder_it_renames(self):
        path = self.script()
        self.assertTrue(path)
        self.assertFalse(os.path.abspath(path).startswith(
            os.path.abspath(self.install) + os.sep))

    def test_it_leaves_the_install_folder_before_it_moves_it(self):
        """Windows will not rename a folder that is a process's current
        directory, and cmd.exe would otherwise inherit Prism's."""
        body = _read(self.script())
        self.assertIn('cd /d "%~dp0"', body)
        self.assertLess(body.index('cd /d "%~dp0"'), body.index("move "))

    def test_it_reads_its_own_paths_as_utf8(self):
        body = _read(self.script())
        self.assertIn("chcp 65001", body)
        self.assertLess(body.index("chcp 65001"), body.index("move "))

    def test_it_waits_for_the_old_prism_then_swaps_and_starts_the_new_one(self):
        body = _read(self.script())
        self.assertIn('tasklist /FI "PID eq 4242"', body)
        self.assertIn(f'move "{self.install}" "{self.backup}"', body)
        self.assertIn(f'move "{self.staged}" "{self.install}"', body)
        self.assertIn(AU.confirm_marker_path(self.install), body)
        self.assertIn(f'start "" "{self.exe}"', body)

    def test_a_failed_second_move_puts_the_old_version_back(self):
        self.assertIn(f'move "{self.backup}" "{self.install}"', _read(self.script()))

    def test_a_folder_that_will_not_move_starts_the_old_version_again(self):
        """The customer already closed Prism; leaving no window is worse."""
        stuck = _read(self.script()).split(":stuck", 1)[1].split("exit /b 2", 1)[0]
        self.assertIn(f'start "" "{self.exe}"', stuck)

    def test_it_writes_to_the_same_log_as_everything_else(self):
        self.assertIn(AU.log_path(), _read(self.script()))

    def test_begin_apply_on_windows_hands_the_swap_to_a_hidden_cmd(self):
        spawned = []
        with mock.patch.object(AU.sys, "platform", "win32"), \
                mock.patch.object(AU, "spawn_detached",
                                  side_effect=lambda argv, **kw: spawned.append((argv, kw))):
            AU.begin_apply(4242, self.install, self.staged, self.backup, [self.exe])
        self.assertEqual(1, len(spawned))
        argv, kw = spawned[0]
        self.assertEqual("cmd.exe", argv[0])
        self.assertNotIn("--prism-apply-update", argv)
        self.assertFalse(argv[-1].startswith(self.install + os.sep))
        self.assertEqual(os.path.dirname(argv[-1]), kw["cwd"])
        self.assertTrue(kw["no_window"])

    def test_linux_and_macos_keep_the_in_process_helper(self):
        spawned = []
        with mock.patch.object(AU.sys, "platform", "linux"), \
                mock.patch.object(AU, "spawn_detached",
                                  side_effect=lambda argv, **kw: spawned.append(argv)):
            AU.begin_apply(4242, self.install, self.staged, self.backup,
                           ["/opt/Prism/Prism"])
        self.assertIn("--prism-apply-update", spawned[0])

    def test_the_working_folder_reaches_the_process(self):
        with mock.patch.object(AU.subprocess, "Popen") as popen:
            AU.spawn_detached(["true"], cwd="/tmp")
        self.assertEqual("/tmp", popen.call_args.kwargs["cwd"])


class ASwapAcrossVolumes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-swap-xdev-")
        self.install = os.path.join(self.tmp, "Prism")
        self.staged = os.path.join(self.tmp, "staged")
        self.backup = self.install + ".old"
        _tree(self.install, "old")
        _tree(self.staged, "new")

    def test_a_rename_that_cannot_cross_volumes_falls_back_to_a_copy(self):
        # EXDEV, as os.rename raises it between two drives.
        with mock.patch.object(AU.os, "rename",
                               side_effect=OSError(18, "Invalid cross-device link")):
            AU.perform_swap(self.install, self.staged, self.backup, retry_seconds=1)
        self.assertEqual("new", _read(os.path.join(self.install, "marker.txt")))
        self.assertEqual("old", _read(os.path.join(self.backup, "marker.txt")))


class ALockedFileNeverCostsTheInstall(unittest.TestCase):
    """The review's finding: a copy-and-delete on a LOCKED rename deleted
    every file of a live install except the locked one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-swap-locked-")
        self.install = os.path.join(self.tmp, "Prism")
        self.staged = os.path.join(self.tmp, "staged")
        self.backup = self.install + ".old"
        _tree(self.install, "old")
        _tree(self.staged, "new")

    def test_a_refused_rename_moves_nothing(self):
        with mock.patch.object(AU.os, "rename",
                               side_effect=PermissionError(13, "in use")):
            with self.assertRaises(PermissionError):
                AU._move(self.install, self.backup)
        self.assertEqual("old", _read(os.path.join(self.install, "marker.txt")))
        self.assertFalse(os.path.exists(self.backup))

    def test_the_swap_gives_up_and_leaves_everything_as_it_was(self):
        with mock.patch.object(AU.os, "rename",
                               side_effect=PermissionError(13, "in use")):
            with self.assertRaises(AU.ApplyError):
                AU.perform_swap(self.install, self.staged, self.backup,
                                retry_seconds=0.3, retry_interval=0.1)
        self.assertEqual("old", _read(os.path.join(self.install, "marker.txt")))
        self.assertEqual("new", _read(os.path.join(self.staged, "marker.txt")))
        self.assertFalse(os.path.exists(self.backup))


class TheSwapSaysWhatHappened(unittest.TestCase):

    def setUp(self):
        self.log = AU.log_path()
        if os.path.exists(self.log):
            os.remove(self.log)
        self.tmp = tempfile.mkdtemp(prefix="prism-swap-log-")

    def logged(self) -> str:
        return _read(self.log) if os.path.exists(self.log) else ""

    def test_a_line_is_written(self):
        AU.note("hello from the test")
        self.assertIn("hello from the test", self.logged())

    def test_a_failed_swap_is_recorded_and_the_old_version_stays(self):
        install = os.path.join(self.tmp, "Prism")
        _tree(install, "old")
        code = AU.perform_apply_and_relaunch(
            999999999, install, os.path.join(self.tmp, "missing"),
            install + ".old", ["true"])
        self.assertEqual(2, code)
        self.assertIn("swap failed", self.logged())
        self.assertEqual("old", _read(os.path.join(install, "marker.txt")))

    def test_a_good_swap_is_recorded_and_tidies_what_staging_left(self):
        install = os.path.join(self.tmp, "Prism")
        staging = os.path.join(self.tmp, ".prism-update-staging")
        staged = os.path.join(staging, "1.5.7")
        _tree(install, "old")
        _tree(staged, "new")
        with open(staged + ".VERSION", "w") as f:
            f.write("1.5.7")
        with mock.patch.object(AU, "spawn_detached"):
            code = AU.perform_apply_and_relaunch(
                999999999, install, staged, install + ".old", ["true"])
        self.assertEqual(0, code)
        self.assertEqual("new", _read(os.path.join(install, "marker.txt")))
        self.assertIn("1.5.7", _read(AU.confirm_marker_path(install)))
        self.assertFalse(os.path.exists(staged + ".VERSION"))
        self.assertFalse(os.path.exists(staging))
        self.assertIn("swapped in 1.5.7", self.logged())


class StagingHappensWhereTheSwapCanFinish(unittest.TestCase):

    def test_beside_an_install_that_can_be_written(self):
        tmp = tempfile.mkdtemp(prefix="prism-stage-root-")
        install = os.path.join(tmp, "Prism")
        os.makedirs(install)
        self.assertEqual(os.path.join(tmp, ".prism-update-staging"),
                         updater.stage_root(install))

    def test_in_the_profile_when_the_install_folder_cannot_be_written(self):
        with mock.patch.object(updater, "_writable_dir", return_value=False), \
                mock.patch.object(updater, "updates_root",
                                  return_value="/profile/updates"):
            self.assertEqual("/profile/updates", updater.stage_root("/opt/Prism"))

    def test_the_probe_really_writes_rather_than_asking(self):
        """os.access says yes for any folder on Windows; only a write tells."""
        tmp = tempfile.mkdtemp(prefix="prism-probe-")
        self.assertTrue(updater._writable_dir(os.path.join(tmp, "stage")))
        self.assertEqual([], os.listdir(os.path.join(tmp, "stage")))
        blocker = os.path.join(tmp, "a-file")
        with open(blocker, "w") as f:
            f.write("x")
        self.assertFalse(updater._writable_dir(os.path.join(blocker, "stage")))


if __name__ == "__main__":
    unittest.main()
