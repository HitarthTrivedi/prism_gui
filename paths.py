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
    """True in ANY packaged build — PyInstaller or Nuitka.

    Deliberately not `hasattr(sys, "_MEIPASS")`: that marker is PyInstaller's
    alone, so a Nuitka build reported "running from source" and switched on
    three bypasses at once — the DEVELOPMENT signing key (licensing/keys.py,
    which calls it "a universal skeleton key for the whole product"),
    PRISM_LICENSE_OFFLINE_DEV (licensing/__init__.py) and PRISM_LICENSE_SERVER
    (licensing/client.py). The app would start and run normally, which is what
    made it dangerous. build.py recommends Nuitka *for tamper resistance*, so
    the engine someone reaches for to harden the app was the one that opened it.
    """
    if "__compiled__" in globals():                 # Nuitka standalone
        return True
    return bool(getattr(sys, "frozen", False))      # PyInstaller


def bundle_dir() -> str:
    """Root of the read-only payload: _MEIPASS when frozen, else the repo.

    Must not read sys._MEIPASS unconditionally on the frozen branch — under
    Nuitka is_frozen() is now True and that attribute does not exist.
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def resource(*parts: str) -> str:
    """Absolute path to a file we ship, e.g. resource('assets', 'fonts')."""
    return os.path.join(bundle_dir(), *parts)


def user_dir(*parts: str) -> str:
    """Absolute path inside ~/.prism — the user's own state, never bundled."""
    return os.path.join(os.path.expanduser("~"), ".prism", *parts)


def ensure_user_dir() -> str:
    """Create ~/.prism owner-only, and tighten it if an older build did not.

    Call once at startup. Tightening the ROOT is the whole fix: a 0700 parent
    cannot be traversed by anyone else, so runs/, logs/, workspace/ and
    gui_favorites.json are covered without chasing each writer — every one of
    them creates its directory with the default mode, which under the usual
    0002 umask is 0775.

    The credentials themselves were never the problem: config.json,
    license.json, authorization.json and device_id are all written 0600. What
    sat at 0664 was the work — customer queries, BOQ outputs, run records —
    and device.py names shared workstations as a target deployment.

    Best-effort by design. A failure here must not stop the app starting; on
    Windows the mode is largely advisory anyway.
    """
    path = user_dir()
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)       # exist_ok=True ignores mode on an existing dir
    except OSError:
        pass
    return path


def is_local_result(url: str) -> bool:
    """A stage result that is a FILE on this machine, not a tool's tab.

    Local agents (the reel renderer) hand back a path where every scraped
    stage hands back a URL, and the UI treats the two the same everywhere —
    so a path was being fed to QUrl(), which has no scheme to open and fails
    silently. Anything that opens a result has to ask this first.
    """
    return bool(url) and "://" not in url and os.path.exists(url)


def open_result(url: str) -> None:
    """Open a stage result — a file with its default app, a URL in Chrome."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(
        QUrl.fromLocalFile(url) if is_local_result(url) else QUrl(url))


def reveal_result(path: str) -> None:
    """Show the file in Finder/Explorer. Worth its own button because output
    lands in ~/.prism/runs, and a dot-folder is invisible in Finder — a user
    who is told the path still cannot get to it."""
    import subprocess
    folder = os.path.dirname(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        open_result(folder)


def app_root() -> str:
    """The directory holding the executable (frozen) or the sources (dev).
    Used for logs and for telling the user where the app actually is."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
