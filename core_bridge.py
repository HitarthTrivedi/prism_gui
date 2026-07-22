"""
Prism GUI — bridge into the existing CLI engine
────────────────────────────────────────────────
The GUI has NO business logic of its own. Every routing decision, every
Selenium/browser action, every Groq call already lives in
prism_terminal/core/*.py — this module just puts that package on sys.path and
re-exports it so the GUI's widgets can call the exact same functions the CLI
does. Both apps read/write the same ~/.prism/config.json, so signing in once
(either app) carries over to the other.

prism_terminal is a git submodule at ./prism_terminal (see .gitmodules) —
`git clone --recurse-submodules` gets a fully self-contained checkout. If
you're instead developing prism_terminal and prism_gui side by side in the
same monorepo (a sibling ../prism_terminal folder, not the submodule), that
takes priority so you're always working against the copy you're editing.
"""
from __future__ import annotations
import os
import sys

import paths

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    # Packaged app: the spec copies prism_terminal/ into the bundle root, so
    # this is the only one that exists (and it must be checked first — the dev
    # paths below would resolve to nothing useful inside _MEIPASS).
    paths.resource("prism_terminal"),
    os.path.join(_HERE, "..", "prism_terminal"),   # local monorepo dev
    os.path.join(_HERE, "prism_terminal"),         # standalone clone (submodule)
]

_TERMINAL_DIR = next(
    (os.path.abspath(c) for c in _CANDIDATES
     if os.path.isdir(os.path.join(c, "core"))), None)

if _TERMINAL_DIR is None:
    raise ImportError(
        "Can't find prism_terminal's core/ package. Expected either a sibling "
        "'../prism_terminal' folder, or the submodule at './prism_terminal' "
        "(run 'git submodule update --init' if you cloned without "
        "--recurse-submodules).")

if _TERMINAL_DIR not in sys.path:
    sys.path.insert(0, _TERMINAL_DIR)

from core import config as config          # noqa: E402
from core import agents as agents          # noqa: E402
from core import router as router          # noqa: E402
from core import pathfinder as pathfinder  # noqa: E402
from core import files as files            # noqa: E402
from core import voice as voice            # noqa: E402
from core import mailer as mailer          # noqa: E402


def automation_available() -> tuple[bool, str]:
    """Selenium/undetected-chromedriver are optional/heavy — probe lazily so
    the GUI can start and show a clear message instead of crashing on import."""
    try:
        from core import automation  # noqa: F401
        return True, ""
    except Exception as e:
        return False, str(e)


def get_automation():
    from core import automation
    return automation
