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
`git clone --recurse-submodules` gets a fully self-contained checkout.

**The submodule always wins.** This docstring used to claim the opposite — that
a sibling ../prism_terminal checkout took priority "so you're always working
against the copy you're editing" — and it was wrong, because `paths.resource()`
resolves to ./prism_terminal when running from source and is checked first. A
sibling checkout was never reached.

The behaviour is right and the sentence was wrong, so the sentence went. The
submodule is the copy that gets committed and the copy that gets built; a
sibling silently overriding it would mean shipping code that was never tested
against what is actually in the tree. But a stale sentence is worse than
either, because somebody edits the sibling, sees nothing change, and loses an
afternoon to it — which is why _warn_about_sibling() below says so out loud.
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
    #
    # Running from source this resolves to ./prism_terminal, the submodule,
    # which is deliberately the winner: it is what gets committed and what
    # gets built. See the module docstring.
    paths.resource("prism_terminal"),
    os.path.join(_HERE, "prism_terminal"),         # standalone clone (submodule)
    os.path.join(_HERE, "..", "prism_terminal"),   # sibling, last resort only
]

if paths.is_frozen():
    # Nothing goes on sys.path. core.* lives in the archive, named by
    # prism.spec's enumerated hiddenimports, and a directory of loose .py files
    # inserted at position 0 is exactly how an edited engine silently overrode
    # the compiled one — the sources are no longer shipped, and this is what
    # makes sure they could not win even if something put them back.
    _TERMINAL_DIR = paths.resource("prism_terminal")

    # Prism Studio's Chromium lives INSIDE the playwright package
    # (playwright/driver/package/.local-browsers/…), because that's the only
    # location prism.spec's collect_data_files(playwright) can bundle — it
    # got there because .github/workflows/build.yml ran `playwright install
    # chromium` with this exact same variable set. Playwright's own default,
    # unset, is the OS cache dir (~/.cache/ms-playwright or the Windows/macOS
    # equivalent) — real for a developer who ran `playwright install`
    # themselves, empty on a customer's machine, which is what "the web
    # renderer needs Playwright" was actually reporting even after the
    # browser shipped in the build right next to it. setdefault, not a flat
    # assignment: a build/test environment that already set this on purpose
    # keeps winning.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
else:
    _TERMINAL_DIR = next(
        (os.path.abspath(c) for c in _CANDIDATES
         if os.path.isdir(os.path.join(c, "core"))), None)

    if _TERMINAL_DIR is None:
        raise ImportError(
            "Can't find prism_terminal's core/ package. Expected either a "
            "sibling '../prism_terminal' folder, or the submodule at "
            "'./prism_terminal' (run 'git submodule update --init' if you "
            "cloned without --recurse-submodules).")

    if _TERMINAL_DIR not in sys.path:
        sys.path.insert(0, _TERMINAL_DIR)


def _warn_about_sibling() -> None:
    """Say so when a sibling checkout exists and is being ignored.

    The failure it prevents: two checkouts of the engine on one machine, edits
    going into the one that is not loaded, and no signal at all — the app runs,
    the tests pass, and the change simply is not there. Cheap to print, and it
    is the sentence that ends the confusion.
    """
    if getattr(sys, "frozen", False):
        return
    sibling = os.path.abspath(os.path.join(_HERE, "..", "prism_terminal"))
    if not os.path.isdir(os.path.join(sibling, "core")):
        return
    if sibling == _TERMINAL_DIR:
        return
    print(f"note: two copies of the engine are on this machine.\n"
          f"      loaded : {_TERMINAL_DIR}   <- edit this one\n"
          f"      ignored: {sibling}",
          file=sys.stderr)


_warn_about_sibling()

from core import config as config          # noqa: E402
from core import agents as agents          # noqa: E402
from core import bom as bom                # noqa: E402
from core import lang as lang              # noqa: E402
from core import router as router          # noqa: E402

# Count Groq tokens for licence metering. Installed here, from the GUI side,
# rather than in core/router.py: prism_terminal is a submodule shared with the
# CLI, which carries no licence and must keep running standalone. Wrapping the
# `requests` name the module already looks up catches all three of its call
# sites without editing a line of it, and degrades to "no token counts" rather
# than an error if the engine is ever refactored.
try:
    import licensing.meter as _meter       # noqa: E402
    _meter.install_groq_meter(router)
except Exception:                          # noqa: BLE001
    pass    # metering is never worth breaking the engine over
from core import pathfinder as pathfinder  # noqa: E402
from core import files as files            # noqa: E402
from core import voice as voice            # noqa: E402
from core import mailer as mailer          # noqa: E402


def resolved_agents(chosen: dict) -> list[tuple[str, str]]:
    """(tool name, sign-in URL) for a {category: tool} mapping, de-duplicated
    by tool and kept in mapping-iteration order.

    The one place this dedupe-and-look-up loop lives — the Settings screen's
    Agents section, the wizard, and MainWindow's own "Login tabs" all need the
    same answer to "which tools, which URLs" and used to each write their own
    copy of this loop.
    """
    out, seen = [], set()
    for name in chosen.values():
        if name and name not in seen:
            seen.add(name)
            out.append((name, (agents.AGENT_REGISTRY.get(name) or {}).get("url", "")))
    return out


def login_tab_urls(chosen: dict) -> list[str]:
    return [url for _name, url in resolved_agents(chosen) if url]


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


def boq_available() -> tuple[bool, str]:
    """core.boq needs ezdxf, which is optional — probe it the same way as
    automation so the BOQ add-on can explain itself instead of the whole app
    failing to start on a machine that never uses it."""
    try:
        import ezdxf  # noqa: F401
        from core import boq  # noqa: F401
        return True, ""
    except Exception as e:
        return False, str(e)


def get_boq():
    from core import boq
    return boq


def gerber_available() -> tuple[bool, str]:
    """core.gerber has no hard dependency of its own — shapely is optional,
    same as ezdxf is for BOQ, and the module degrades rather than fails
    without it (four of the five numbers still come out; only track spacing
    needs it). So this only needs to confirm the module itself imports."""
    try:
        from core import gerber  # noqa: F401
        return True, ""
    except Exception as e:
        return False, str(e)


def get_gerber():
    from core import gerber
    return gerber


def get_gerber_clean():
    from core import gerber_clean
    return gerber_clean


# ── Inquiry automation ───────────────────────────────────────────────────────
# Imported on demand like the rest: the engine's mail modules pull in imaplib
# and the CSV machinery, and a customer who never buys this add-on should not
# pay for that at every launch.

def get_inbox():
    from core import inbox
    return inbox


def get_triage():
    from core import triage
    return triage


def get_register():
    from core import register
    return register


def get_quoting():
    from core import quoting
    return quoting


def get_sop():
    from core import sop
    return sop


def get_po():
    from core import po
    return po


def get_mailflow():
    from core import mailflow
    return mailflow


def get_worklist():
    from core import worklist
    return worklist


def get_history():
    from core import history
    return history


def get_files():
    from core import files
    return files


def get_drafting():
    from core import drafting
    return drafting


def reel_available() -> tuple[bool, str]:
    """Pillow draws the frames, FFmpeg encodes them. Probe both so the add-on
    can explain what is missing instead of failing mid-render."""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return False, "Pillow is needed to draw the frames:\n\n    pip install pillow"
    try:
        from core import reel
        reel.ffmpeg_path()
    except Exception as e:
        return False, str(e)
    return True, ""


def get_reel():
    from core import reel
    return reel


def _no_pip_in_a_frozen_build(why: str) -> str:
    """core.reel_web.available() and core.motion.is_available() are shared
    with the CLI, where "pip install playwright && playwright install
    chromium" is a real instruction — the person reading it has a shell and
    the same Python that raised the message. Someone who downloaded the
    Windows/macOS installer has neither: no pip on PATH, and even a pip that
    happened to exist wouldn't touch the frozen app's bundled interpreter.
    Telling them to run it is not a workaround, it's a dead end dressed up
    as one — so a frozen build gets the plain fact instead."""
    if paths.is_frozen() and "pip install playwright" in why:
        return ("The web renderer (Playwright) isn't included in this "
                "installer build yet.")
    return why


def studio_available() -> tuple[bool, str]:
    """Prism Studio films an HTML page, so it needs a browser engine on top of
    FFmpeg. Probed separately from the template renderer: a machine can have
    one and not the other, and the pipeline picks accordingly."""
    try:
        from core import reel_web
    except Exception as e:
        return False, f"The web renderer isn't available ({e})."
    ok, why = reel_web.available()
    return ok, why if ok else _no_pip_in_a_frozen_build(why)


def get_studio():
    from core import reel_web
    return reel_web


def get_reel_edit():
    """The browser layout editor for Studio reels."""
    from core import reel_edit
    return reel_edit


def get_assets():
    """Brand marks and artwork, cut out of whatever the client attached."""
    from core import assets
    return assets


def get_ffmpeg():
    from core import ffmpeg
    return ffmpeg


def motion_available() -> tuple[bool, str]:
    """Probes whether FFmpeg and the browser runtime are available."""
    try:
        from core import motion
    except Exception as e:
        return False, f"Motion Graphics engine not installed ({e})."
    ok, why = motion.is_available()
    return ok, why if ok else _no_pip_in_a_frozen_build(why)


def get_motion():
    from core import motion
    return motion


def get_motion_generate():
    """The scene-at-a-time generation loop — storyboard turn, then one
    browser turn per scene. See core.reel_web's build_spec() for the
    pattern this mirrors."""
    from core.motion import generate
    return generate

