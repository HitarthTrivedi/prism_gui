"""What Prism's children inherit.

Pressing Play on a finished reel, on 2026-09-07, produced:

    vlc: symbol lookup error: /snap/core20/current/lib/x86_64-linux-gnu/
    libpthread.so.0: undefined symbol: __libc_pthread_init, version GLIBC_PRIVATE

The deb VLC works. Prism works. What broke was the environment between
them: Prism had been started from a VS Code-snap terminal, which exports
GTK_PATH (and friends) pointing into the snap, and VLC — a child of a child
of that terminal — loaded the snap's GTK modules, built against the snap's
glibc. Measured directly: `env -u GTK_PATH vlc reel.mp4` plays; as-is it
dies. The packaged build has the same shape of problem from PyInstaller's
LD_LIBRARY_PATH, which core.browser already undoes for Chromium alone.

These pin paths.scrub_environment(), which runs once at startup so every
child — xdg-open, the player, Chrome, Qt's own openUrl() — starts clean.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paths  # noqa: E402

SNAP_TERMINAL = {
    "HOME": "/home/p",
    "SNAP_NAME": "code",
    "SNAP": "/snap/code/259",
    "GTK_PATH": "/snap/code/259/usr/lib/x86_64-linux-gnu/gtk-3.0",
    "GIO_MODULE_DIR": "/home/p/snap/code/common/.cache/gio-modules",
    "LOCPATH": "/snap/code/259/usr/lib/locale",
    "XDG_DATA_DIRS": "/home/p/snap/code/259/.local/share:/snap/code/259/usr/share:/usr/share",
    "XDG_DATA_DIRS_VSCODE_SNAP_ORIG": "/usr/share/ubuntu:/usr/share",
    "LD_LIBRARY_PATH": "/snap/core20/current/lib/x86_64-linux-gnu:/opt/lib",
}


def _linux():
    return mock.patch.object(paths.sys, "platform", "linux")


class StartedFromASnapTerminal(unittest.TestCase):

    def test_the_snaps_gtk_and_module_paths_are_dropped(self):
        with mock.patch.dict(os.environ, SNAP_TERMINAL, clear=True), _linux(), \
                mock.patch.object(paths.sys, "executable", "/usr/bin/python3"):
            changed = paths.scrub_environment()
            for var in ("GTK_PATH", "GIO_MODULE_DIR", "LOCPATH"):
                self.assertNotIn(var, os.environ, var)
                self.assertIn(var, changed)

    def test_xdg_data_dirs_go_back_to_the_pre_snap_value(self):
        with mock.patch.dict(os.environ, SNAP_TERMINAL, clear=True), _linux(), \
                mock.patch.object(paths.sys, "executable", "/usr/bin/python3"):
            paths.scrub_environment()
            self.assertEqual(os.environ["XDG_DATA_DIRS"],
                             "/usr/share/ubuntu:/usr/share")
            self.assertNotIn("XDG_DATA_DIRS_VSCODE_SNAP_ORIG", os.environ)

    def test_only_the_snap_entries_leave_a_library_path(self):
        with mock.patch.dict(os.environ, SNAP_TERMINAL, clear=True), _linux(), \
                mock.patch.object(paths.sys, "executable", "/usr/bin/python3"):
            paths.scrub_environment()
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/opt/lib")

    def test_the_snap_identity_itself_is_left_alone(self):
        with mock.patch.dict(os.environ, SNAP_TERMINAL, clear=True), _linux(), \
                mock.patch.object(paths.sys, "executable", "/usr/bin/python3"):
            paths.scrub_environment()
            self.assertEqual(os.environ["SNAP_NAME"], "code")

    def test_when_prism_is_the_snap_nothing_is_touched(self):
        with mock.patch.dict(os.environ, SNAP_TERMINAL, clear=True), _linux(), \
                mock.patch.object(paths.sys, "executable",
                                  "/snap/prism/1/bin/python3"):
            self.assertEqual(paths.scrub_environment(), [])
            self.assertEqual(os.environ["GTK_PATH"], SNAP_TERMINAL["GTK_PATH"])


class TheFrozenBuild(unittest.TestCase):

    def test_the_real_library_path_is_put_back_for_children(self):
        env = {"LD_LIBRARY_PATH": "/tmp/_MEI123", "LD_LIBRARY_PATH_ORIG": "/opt/lib"}
        with mock.patch.dict(os.environ, env, clear=True), _linux(), \
                mock.patch.object(paths, "is_frozen", return_value=True):
            self.assertEqual(paths.scrub_environment(), ["LD_LIBRARY_PATH"])
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/opt/lib")
            self.assertNotIn("LD_LIBRARY_PATH_ORIG", os.environ)

    def test_with_nothing_stashed_the_bundle_path_is_simply_dropped(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI123"},
                             clear=True), _linux(), \
                mock.patch.object(paths, "is_frozen", return_value=True):
            paths.scrub_environment()
            self.assertNotIn("LD_LIBRARY_PATH", os.environ)


class NothingToDo(unittest.TestCase):

    def test_a_clean_environment_is_reported_as_unchanged(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/p", "PATH": "/usr/bin"},
                             clear=True), _linux(), \
                mock.patch.object(paths, "is_frozen", return_value=False):
            self.assertEqual(paths.scrub_environment(), [])
            self.assertEqual(sorted(os.environ), ["HOME", "PATH"])

    def test_other_platforms_are_left_entirely_alone(self):
        with mock.patch.dict(os.environ, SNAP_TERMINAL, clear=True), \
                mock.patch.object(paths.sys, "platform", "win32"):
            self.assertEqual(paths.scrub_environment(), [])
            self.assertEqual(os.environ["GTK_PATH"], SNAP_TERMINAL["GTK_PATH"])


if __name__ == "__main__":
    unittest.main()
