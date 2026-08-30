"""Tests for packaging/flatten_update_assets.py — the CI-side half of the
flattened-asset naming scheme updater.py's _file_url() fetches by.

The two must never drift apart independently: this asserts against the exact
`<platform_tag>__<path with / as __>` shape, not just "some file got copied".
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
sys.path.insert(0, GUI)

# packaging/ has no __init__.py, and collides with the installed `packaging`
# library under `import packaging.flatten_update_assets` — loaded by file
# path instead, same reasoning as the script's own docstring.
_spec = importlib.util.spec_from_file_location(
    "flatten_update_assets", os.path.join(GUI, "packaging", "flatten_update_assets.py"))
flatten_update_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flatten_update_assets)


class FlatteningABuildDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "Prism")
        os.makedirs(os.path.join(self.root, "_internal"))
        with open(os.path.join(self.root, "Prism"), "w") as f:
            f.write("binary")
        with open(os.path.join(self.root, "_internal", "base_library.zip"), "w") as f:
            f.write("zip-contents")
        self.out = os.path.join(self.tmp.name, "out")

    def test_names_match_platform_tag_double_underscore_scheme(self):
        count = flatten_update_assets.flatten(self.root, self.out, "linux-x64")
        self.assertEqual(count, 2)
        self.assertEqual(
            set(os.listdir(self.out)),
            {"linux-x64__Prism", "linux-x64___internal__base_library.zip"})

    def test_different_platforms_never_collide_on_the_same_relative_path(self):
        # The whole reason for the platform prefix: two platforms sharing a
        # relative path (different bytes each time) must never produce the
        # same output filename in the same directory.
        flatten_update_assets.flatten(self.root, self.out, "linux-x64")
        flatten_update_assets.flatten(self.root, self.out, "windows-x64")
        names = os.listdir(self.out)
        self.assertIn("linux-x64__Prism", names)
        self.assertIn("windows-x64__Prism", names)
        self.assertEqual(len(names), 4)  # 2 files x 2 platforms, none clobbered

    def test_symlinks_are_skipped_not_copied(self):
        os.symlink("Prism", os.path.join(self.root, "prism-link"))
        count = flatten_update_assets.flatten(self.root, self.out, "linux-x64")
        self.assertEqual(count, 2)  # the symlink itself doesn't count
        self.assertNotIn("linux-x64__prism-link", os.listdir(self.out))


if __name__ == "__main__":
    unittest.main()
