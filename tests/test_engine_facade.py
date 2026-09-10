"""`core_bridge` is the only module that may import the engine.

The GUI sits on top of `prism_terminal`, a git submodule shared with the
unlicensed CLI. `core_bridge.py` exists to adapt one to the other: it puts the
engine on `sys.path`, decides which of three possible checkouts wins, installs
the Groq token meter from the GUI side so the submodule stays licence-free, and
wraps every heavy module in a lazy getter with an availability probe.

All of that is worth nothing if a widget can write `from core import gerber` and
skip it. Today none do -- this test is here to keep it that way, because the
add-ons restructure depends on the boundary holding while files move.

Why the exceptions are what they are:

  · core_bridge.py itself is the bridge.
  · tests/ may import the engine directly; a test that had to go through the
    bridge could not test the bridge.
  · devtools/ and examples/ are developer scripts that are never packaged
    (packaging/prism.spec excludes the whole directory) and deliberately
    re-implement the sys.path dance so they can run standalone.
"""
from __future__ import annotations

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "build", "dist", "release", "prism_terminal",
             ".venv", "node_modules", "tests", "devtools", "examples", "videos"}

# Relative paths allowed to import the engine directly.
ALLOWED = {"core_bridge.py"}

# The engine's top-level package name. It is the very generic `core`, because
# prism_terminal/ has no __init__.py and is put on sys.path wholesale -- which
# is precisely why an accidental `from core import x` is easy to write and hard
# to notice.
ENGINE_ROOTS = {"core"}


def _sources():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            if rel in ALLOWED:
                continue
            yield rel, path


def _engine_imports(path: str) -> list[str]:
    """Every `import core...` / `from core... import ...` in one file.

    Parsed rather than grepped: a docstring that says "from core import reel"
    -- and several in this repo do, explaining this very rule -- must not fail
    the suite.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError):
        return []

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ENGINE_ROOTS:
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import; it cannot reach the engine.
            if node.level == 0 and node.module:
                if node.module.split(".")[0] in ENGINE_ROOTS:
                    names = ", ".join(a.name for a in node.names)
                    found.append(f"from {node.module} import {names}")
    return found


class OnlyTheBridgeImportsTheEngine(unittest.TestCase):

    def test_no_app_module_imports_the_engine_directly(self):
        offenders = []
        for rel, path in _sources():
            for line in _engine_imports(path):
                offenders.append(f"{rel} → {line}")
        self.assertEqual(
            offenders, [],
            "These modules import the engine directly instead of going "
            "through core_bridge:\n  " + "\n  ".join(offenders)
            + "\n\nUse `import core_bridge as CB` and one of its accessors "
              "(CB.config, CB.get_gerber(), CB.reel_available(), ...). The "
              "bridge is what puts the engine on sys.path in the first place, "
              "so a direct import also depends on something else having "
              "imported it first -- which works until the import order "
              "changes.")

    def test_the_bridge_itself_still_exists_where_the_build_expects_it(self):
        """packaging/prism.spec reaches the engine through this file's
        sys.path work; if it moves, the frozen build stops resolving core.*."""
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "core_bridge.py")),
                        "core_bridge.py must stay at the repo root")


if __name__ == "__main__":
    unittest.main()
