"""
Prism GUI — bridge into the existing CLI engine
────────────────────────────────────────────────
The GUI has NO business logic of its own. Every routing decision, every
Selenium/browser action, every Groq call already lives in
prism_terminal/core/*.py — this module just puts that package on sys.path and
re-exports it so the GUI's widgets can call the exact same functions the CLI
does. Both apps read/write the same ~/.prism/config.json, so signing in once
(either app) carries over to the other.
"""
from __future__ import annotations
import os
import sys

_TERMINAL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "prism_terminal"))
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
