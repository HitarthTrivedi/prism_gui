"""Everything .github/workflows names must still be there.

CI reaches into this repo by string, from YAML, in ways no import graph knows
about:

    PLATFORM_TAG=$(python -c "import sys; sys.path.insert(0, '.'); import updater; ...")
    VERSION=$(python -c "import sys; sys.path.insert(0, '.'); import app_meta; ...")
    python packaging/build.py --clean
    python packaging/smoke_test.py
    python packaging/manifest.py ...
    python packaging/flatten_update_assets.py ...

Those two `python -c` snippets are the sharp end. They import `updater` and
`app_meta` as bare top-level names from the repo root, so moving either module
into a package breaks the release pipeline -- and breaks it *only in CI*, on a
tagged build, at the manifest step, long after a green local test run said the
change was fine. `packaging/prism.spec` has the same shape of dependency and the
same failure mode (see its DEFAULT_SERVER patching, which only runs when
PRISM_SERVER_URL is set and once failed on all three platforms while every local
build passed).

This test drags those failures forward to the desk of whoever makes the change.
It is deliberately dumb: it does not run CI, it just holds the workflow and the
repo to the same set of names.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")


def _workflow_text() -> str:
    parts = []
    for name in sorted(os.listdir(WORKFLOWS)):
        if name.endswith((".yml", ".yaml")):
            with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
                parts.append(f.read())
    return "\n".join(parts)


class TheWorkflowsStillPointAtRealThings(unittest.TestCase):

    def setUp(self):
        self.text = _workflow_text()

    def test_every_module_imported_inline_is_importable_from_the_repo_root(self):
        """`python -c "... import updater ..."` must actually work."""
        # Capture the whole -c payload first. It contains single quotes --
        # sys.path.insert(0, '.') -- inside a double-quoted shell string, so a
        # character class that excludes both quote kinds stops at the wrong one
        # and finds nothing.
        payloads = re.findall(r'python -c "([^"]*)"', self.text)
        modules = {name for payload in payloads
                   for name in re.findall(r"\bimport (\w+)", payload)}
        modules.discard("sys")
        self.assertTrue(modules, "no inline imports found -- has the workflow "
                                 "changed shape? Update this test with it.")
        for module in sorted(modules):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; sys.path.insert(0, '.'); import %s" % module],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(
                    result.returncode, 0,
                    "`import %s` from the repo root fails, but "
                    ".github/workflows runs exactly that during a release:\n%s"
                    % (module, result.stderr.strip()))

    def test_every_script_the_workflow_runs_exists(self):
        scripts = set(re.findall(r"python3? ((?:packaging|devtools)/[\w./-]+\.py)",
                                 self.text))
        self.assertTrue(scripts, "no scripts found -- has the workflow changed "
                                 "shape? Update this test with it.")
        missing = [s for s in sorted(scripts)
                   if not os.path.isfile(os.path.join(ROOT, s))]
        self.assertEqual(missing, [],
                         "the workflow runs scripts that are not in the tree: "
                         + ", ".join(missing))

    def test_the_spec_entry_point_is_where_the_build_expects_it(self):
        """packaging/prism.spec hardcodes main.py as the Analysis entry, and
        packaging/build.py does the same for the Nuitka path."""
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "main.py")),
                        "main.py must stay at the repo root -- prism.spec's "
                        "Analysis() and build.py both name it by path")


if __name__ == "__main__":
    unittest.main()
