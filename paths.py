"""Where Prism's files live, in both of the two worlds it runs in.

Run from a checkout, everything sits next to this module. Run from a packaged
app, PyInstaller has unpacked the same files into a temporary folder it points
at with sys._MEIPASS, and __file__ no longer says anything useful about where
the data went. Every read of a bundled asset — fonts, the stylesheet, the logo,
the engine's notes files — has to go through resource() so the same code works
frozen and unfrozen.

Note the split this module keeps honest:
  · resource()  — read-only things we ship. Inside the app bundle. Wiped and
                  re-extracted on every launch of a onefile build, so nothing
                  written here survives.
  · user_dir()  — everything the user owns (config, runs, the Chrome profile).
                  Always ~/.prism, identical for the CLI and the packaged app,
                  so installing the app doesn't orphan a CLI user's setup.
"""
from __future__ import annotations
import os
import sys


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> str:
    """Root of the read-only payload: _MEIPASS when frozen, else the repo."""
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def resource(*parts: str) -> str:
    """Absolute path to a file we ship, e.g. resource('assets', 'fonts')."""
    return os.path.join(bundle_dir(), *parts)


def user_dir(*parts: str) -> str:
    """Absolute path inside ~/.prism — the user's own state, never bundled."""
    return os.path.join(os.path.expanduser("~"), ".prism", *parts)


def app_root() -> str:
    """The directory holding the executable (frozen) or the sources (dev).
    Used for logs and for telling the user where the app actually is."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
