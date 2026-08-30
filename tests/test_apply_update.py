"""Tests for apply_update.py — the swap-on-restart mechanics.

Linux is the platform actually exercised here (see apply_update.py's own
banner docstring): renaming a directory out from under a running process
works with no special handling on POSIX, which is what makes an end-to-end
test of the real swap+rollback path possible on this machine at all. The
Windows/macOS code paths are not covered by anything here — they need real
hardware, not a unit test, per update-research-inapp-download.md §2.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply_update as AU


def _reap_in_background(proc: subprocess.Popen) -> None:
    """pid_alive()'s POSIX branch (os.kill(pid, 0)) reports a zombie — a
    child that has exited but whose PARENT hasn't reaped it yet — as still
    alive; that's correct POSIX behaviour, not a bug in pid_alive(). It only
    matters to these tests because the TEST process happens to be the
    parent of the stand-in "old Prism" process. In the real deployment the
    process doing the waiting (the detached apply helper) is never the
    parent of the process it's waiting on — it's waiting on the process
    that spawned IT — so this reaping race doesn't occur there. Here, a
    background thread reaps promptly so the polling loop sees the exit
    without an artificial delay."""
    threading.Thread(target=proc.wait, daemon=True).start()


def _make_tree(root: str, marker: str) -> None:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "marker.txt"), "w") as f:
        f.write(marker)


class PerformSwap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-apply-")
        self.install_dir = os.path.join(self.tmp, "Prism")
        self.staged_dir = os.path.join(self.tmp, "staged")
        self.backup_dir = os.path.join(self.tmp, "Prism.old")
        _make_tree(self.install_dir, "old-version")
        _make_tree(self.staged_dir, "new-version")

    def _read_marker(self, d: str) -> str:
        with open(os.path.join(d, "marker.txt")) as f:
            return f.read()

    def test_swaps_staged_into_install_dir(self):
        AU.perform_swap(self.install_dir, self.staged_dir, self.backup_dir)
        self.assertEqual(self._read_marker(self.install_dir), "new-version")
        self.assertEqual(self._read_marker(self.backup_dir), "old-version")
        self.assertFalse(os.path.isdir(self.staged_dir))

    def test_a_running_process_does_not_block_the_swap(self):
        """The Linux-specific property this whole design leans on: you can
        rename a directory a live process has open. Proven here, not
        assumed — the child keeps a file handle open inside install_dir
        throughout the swap."""
        held_file = os.path.join(self.install_dir, "marker.txt")
        proc = subprocess.Popen(
            [sys.executable, "-c",
            f"f=open({held_file!r}); import time; time.sleep(5)"])
        try:
            time.sleep(0.3)  # let the child actually open the file
            AU.perform_swap(self.install_dir, self.staged_dir, self.backup_dir)
            self.assertEqual(self._read_marker(self.install_dir), "new-version")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_stale_backup_is_cleared_before_swap(self):
        _make_tree(self.backup_dir, "stale-backup")
        AU.perform_swap(self.install_dir, self.staged_dir, self.backup_dir)
        self.assertEqual(self._read_marker(self.backup_dir), "old-version")

    def test_missing_staged_dir_restores_the_original(self):
        os.rename(self.staged_dir, self.staged_dir + "-moved-away")
        with self.assertRaises(AU.ApplyError):
            AU.perform_swap(self.install_dir, self.staged_dir, self.backup_dir)
        # install_dir must not be left missing just because the second
        # rename failed — the whole point of the try/restore in perform_swap.
        self.assertTrue(os.path.isdir(self.install_dir))
        self.assertEqual(self._read_marker(self.install_dir), "old-version")


class ConfirmAndRollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-apply-confirm-")
        self.install_dir = os.path.join(self.tmp, "Prism")
        self.backup_dir = os.path.join(self.tmp, "Prism.old")
        _make_tree(self.install_dir, "new-version")
        _make_tree(self.backup_dir, "old-version")

    def test_marker_lifecycle(self):
        self.assertFalse(AU.is_pending_confirm(self.install_dir))
        AU.mark_pending_confirm(self.install_dir, "1.4.0")
        self.assertTrue(AU.is_pending_confirm(self.install_dir))
        AU.confirm_startup_success(self.install_dir, self.backup_dir)
        self.assertFalse(AU.is_pending_confirm(self.install_dir))

    def test_confirm_success_removes_the_backup(self):
        AU.mark_pending_confirm(self.install_dir, "1.4.0")
        AU.confirm_startup_success(self.install_dir, self.backup_dir)
        self.assertFalse(os.path.isdir(self.backup_dir))

    def test_pending_marker_at_next_launch_triggers_rollback(self):
        AU.mark_pending_confirm(self.install_dir, "1.4.0")
        rolled_back = AU.check_and_rollback_if_pending(self.install_dir, self.backup_dir)
        self.assertTrue(rolled_back)
        with open(os.path.join(self.install_dir, "marker.txt")) as f:
            self.assertEqual(f.read(), "old-version")
        self.assertFalse(AU.is_pending_confirm(self.install_dir))

    def test_no_marker_means_no_rollback(self):
        rolled_back = AU.check_and_rollback_if_pending(self.install_dir, self.backup_dir)
        self.assertFalse(rolled_back)
        with open(os.path.join(self.install_dir, "marker.txt")) as f:
            self.assertEqual(f.read(), "new-version")

    def test_orphaned_marker_with_no_backup_does_not_destroy_the_install(self):
        import shutil
        shutil.rmtree(self.backup_dir)
        AU.mark_pending_confirm(self.install_dir, "1.4.0")
        rolled_back = AU.check_and_rollback_if_pending(self.install_dir, self.backup_dir)
        self.assertFalse(rolled_back)
        self.assertTrue(os.path.isdir(self.install_dir))


class PidLifecycle(unittest.TestCase):
    def test_pid_alive_true_for_self(self):
        self.assertTrue(AU.pid_alive(os.getpid()))

    def test_pid_alive_false_for_a_pid_that_has_exited(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=5)
        # Give the OS a moment to actually reap/release the pid on slower CI.
        deadline = time.monotonic() + 2
        while AU.pid_alive(proc.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(AU.pid_alive(proc.pid))

    def test_wait_for_exit_returns_true_once_the_process_exits(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        _reap_in_background(proc)
        self.assertTrue(AU.wait_for_exit(proc.pid, timeout=5.0))

    def test_wait_for_exit_times_out_on_a_long_lived_process(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            self.assertFalse(AU.wait_for_exit(proc.pid, timeout=0.3))
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class EndToEndApplyHelper(unittest.TestCase):
    """The one full-loop test: a child process stands in for "the old
    Prism", perform_apply_and_relaunch waits for it, swaps, marks pending,
    and spawns a fresh stand-in process — all without needing the real GUI
    app, exercising exactly the sequence apply_update.py's docstring
    describes for Linux."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-apply-e2e-")
        self.install_dir = os.path.join(self.tmp, "Prism")
        self.staged_dir = os.path.join(self.tmp, "staged")
        self.backup_dir = os.path.join(self.tmp, "Prism.old")
        _make_tree(self.install_dir, "old-version")
        _make_tree(self.staged_dir, "new-version")

    def test_full_wait_swap_relaunch_sequence(self):
        old_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
        _reap_in_background(old_proc)
        relaunch_marker = os.path.join(self.tmp, "relaunched.txt")
        relaunch_argv = [sys.executable, "-c",
                        f"open({relaunch_marker!r}, 'w').write('up')"]

        rc = AU.perform_apply_and_relaunch(
            old_proc.pid, self.install_dir, self.staged_dir, self.backup_dir,
            relaunch_argv)

        self.assertEqual(rc, 0)
        with open(os.path.join(self.install_dir, "marker.txt")) as f:
            self.assertEqual(f.read(), "new-version")
        self.assertTrue(AU.is_pending_confirm(self.install_dir))

        # The relaunch is itself a detached, fire-and-forget process — give
        # it a moment to actually run before checking it did.
        deadline = time.monotonic() + 5
        while not os.path.exists(relaunch_marker) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(os.path.exists(relaunch_marker),
                        "spawn_detached's relaunch never ran")


if __name__ == "__main__":
    unittest.main()
