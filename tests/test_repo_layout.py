"""The build reaches into this repo by path. These are the paths.

Most of the codebase can be moved around freely -- imports break loudly and the
suite says so. A short list of files cannot, because the things that depend on
them are not Python imports at all: a PyInstaller spec, a Nuitka command line,
and a few lines of YAML. Move one of these and nothing fails until a release.

    main.py                 packaging/prism.spec's Analysis() entry point, and
                            packaging/build.py's Nuitka entry too
    app_meta.py             read by prism.spec, packaging/smoke_test.py, and
                            .github/workflows inline, from the repo root
    updater.py              imported inline by .github/workflows to compute the
                            platform tag for release asset names
    apply_update.py         the swap helper the updater launches
    update_manifest.py      manifest signing and verification
    paths.py                resource() resolves every shipped asset RELATIVE TO
                            ITS OWN __file__ -- see below, this is the subtle one
    licensing/              prism.spec imports licensing.keys at build time and
                            SystemExits without it, and rewrites
                            licensing/client.py by regex
    packaging/              smoke_test.py derives the repo root as its own
                            parent directory

The paths.py case deserves its own paragraph, because it fails in the least
helpful way available. bundle_dir() returns sys._MEIPASS when frozen and
os.path.dirname(os.path.abspath(__file__)) otherwise. Move paths.py one
directory deeper and every resource() call in a SOURCE checkout starts resolving
one directory too high -- fonts, the stylesheet, the logo, the engine -- while
every frozen build keeps working perfectly, because frozen builds never take
that branch. So CI stays green and only developers see it, which is exactly
backwards from how you would want to find out.
"""
from __future__ import annotations

import os
import unittest

import paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# path -> why it cannot move
PINNED = {
    "main.py": "packaging/prism.spec Analysis() entry, and build.py's Nuitka entry",
    "app_meta.py": "prism.spec, packaging/smoke_test.py and .github/workflows "
                   "all import it as a bare name from the repo root",
    "updater.py": ".github/workflows imports it inline to build asset names",
    "apply_update.py": "launched by the updater to perform the swap",
    "update_manifest.py": "manifest signing and verification",
    "paths.py": "resource() resolves shipped assets relative to its own "
                "__file__ -- moving it breaks source checkouts silently",
    "core_bridge.py": "the only module that may import the engine; it is what "
                      "puts prism_terminal on sys.path at all",
    "licensing": "prism.spec imports licensing.keys at build time and exits "
                 "without it, and regex-rewrites licensing/client.py",
    "packaging": "smoke_test.py derives the repo root as its own parent",
}

# Things prism.spec copies into the bundle, whose destination names have to keep
# matching what paths.resource() is called with. The Google Drive client json is
# deliberately absent: it is gitignored, so it exists on some machines and not
# others, and asserting on it would fail for the wrong reason.
SHIPPED = ["assets", "style.qss", "TERMS_OF_USE.md", "PRIVACY_POLICY.md",
           "lang", os.path.join("licensing", "testdata", "vector.json"),
           "prism_terminal"]


class TheBuildContractSurface(unittest.TestCase):

    def test_nothing_on_the_pinned_list_has_moved(self):
        missing = ["%s  (%s)" % (name, why)
                   for name, why in sorted(PINNED.items())
                   if not os.path.exists(os.path.join(ROOT, name))]
        self.assertEqual(
            missing, [],
            "These must stay at the repo root -- the build and CI name them by "
            "path, so moving one fails at release time rather than here:\n  "
            + "\n  ".join(missing))


class PathsResolvesFromTheRepoRoot(unittest.TestCase):

    def test_paths_itself_still_sits_at_the_root(self):
        self.assertEqual(
            os.path.dirname(os.path.abspath(paths.__file__)), ROOT,
            "paths.py has moved. Every resource() call now resolves relative to "
            "its new home, in source checkouts only -- frozen builds use "
            "sys._MEIPASS and will not show the problem. If it really must "
            "move, give bundle_dir() an explicit repo-root anchor first.")

    def test_the_unfrozen_bundle_dir_is_the_repo_root(self):
        self.assertFalse(paths.is_frozen(), "the test suite is not a frozen build")
        self.assertEqual(paths.bundle_dir(), ROOT)
        self.assertEqual(paths.app_root(), ROOT)

    def test_everything_the_spec_ships_actually_resolves(self):
        for name in SHIPPED:
            with self.subTest(resource=name):
                self.assertTrue(
                    os.path.exists(paths.resource(name)),
                    "paths.resource(%r) does not exist. Either the file moved "
                    "and packaging/prism.spec's datas still promises it, or "
                    "paths.py moved and everything resolves from the wrong "
                    "place." % name)

    def test_user_state_is_not_affected_by_any_of_this(self):
        """The reassuring half. user_dir() is anchored on the home directory,
        not on the layout, so moving modules cannot orphan a shipped customer's
        licence, workspace or settings."""
        self.assertTrue(paths.user_dir().endswith(".prism"))
        self.assertNotIn(ROOT, paths.user_dir())


if __name__ == "__main__":
    unittest.main()
