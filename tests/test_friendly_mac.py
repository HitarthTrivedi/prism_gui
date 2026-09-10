"""The Mac driver failures reach the screen as themselves.

A client's M2 (10 Sep 2026): the engine raised a careful message -- an
Intel driver, a Mac with no Rosetta -- and friendly.py's version-mismatch
rule, whose pattern is "chromedriver", rewrote it into "Chrome updated
itself, update Chrome". The customer did what the screen said and nothing
changed. Pinned here: each engine message lands on its own rule, and the
"leftover Chrome" rules tell a Mac user to quit Chrome, not close windows.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import friendly  # noqa: E402
import core_bridge as CB  # noqa: F401,E402
from core import automation as AU  # noqa: E402


class TheEngineMessagesSurvive(unittest.TestCase):

    def test_an_intel_driver_is_not_a_version_mismatch(self):
        error = RuntimeError("Prism couldn't start Chrome.\n\n" + AU._INTEL_DRIVER_HELP
                             + "\n\nTechnical detail: [Errno 86] Bad CPU type in "
                             "executable: '/Users/om/Library/Application Support/"
                             "undetected_chromedriver/undetected_chromedriver'")
        problem = friendly.explain(error, "run")
        self.assertIn("Intel", problem.title)
        self.assertNotIn("update", problem.what.lower())
        self.assertTrue(any("rm -rf" in s for s in problem.steps))

    def test_a_bare_errno_86_is_explained_too(self):
        problem = friendly.explain(OSError(86, "Bad CPU type in executable"), "run")
        self.assertIn("Intel", problem.title)

    def test_a_missing_arm64_driver_says_online_not_update_chrome(self):
        error = RuntimeError("Prism couldn't start Chrome.\n\n" + AU._NO_ARM64_DRIVER_HELP)
        problem = friendly.explain(error, "run")
        self.assertIn("Apple silicon", problem.title)
        self.assertTrue(any("online" in s for s in problem.steps))
        self.assertFalse(any("About Google Chrome" in s for s in problem.steps))

    def test_the_version_mismatch_rule_still_catches_a_real_mismatch(self):
        problem = friendly.explain(
            "session not created: This version of ChromeDriver only supports "
            "Chrome version 152", "run")
        self.assertEqual(problem.title, "Prism couldn't open Chrome")


class AMacUserIsToldToQuitChrome(unittest.TestCase):

    def test_cannot_connect(self):
        problem = friendly.explain(
            "session not created: cannot connect to chrome at 127.0.0.1:53695", "run")
        self.assertTrue(any("⌘Q" in s for s in problem.steps))

    def test_profile_in_use(self):
        problem = friendly.explain("The profile appears to be in use", "run")
        self.assertTrue(any("⌘Q" in s for s in problem.steps))


if __name__ == "__main__":
    unittest.main()
