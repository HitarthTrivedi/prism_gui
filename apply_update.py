"""Swap a staged update into place — the one step in the whole in-app-update
design that runs OUTSIDE the process being replaced.

Nothing in this module downloads or verifies anything; by the time any
function here runs, updater.py has already: verified the manifest's
signature, checked it isn't expired, checked it's for a version newer than
anything seen before, downloaded every changed file, verified every file's
hash, and re-verified the WHOLE staged tree against the manifest one more
time. This module's only job is the mechanical part: get the running Prism
out of the way, move the verified tree into its place, and come back up as
the new version — or put everything back exactly as it was if that doesn't
work cleanly.

Why this can't happen inside the process being replaced: on Windows, a
running .exe and every DLL it has loaded are locked by the OS for as long as
the process is alive (see update-research-inapp-download.md §2) — nothing
running AS that process can rename its own directory out from under itself.
The fix used here, and by every serious self-updater surveyed in
update-research.md (Squirrel, Sparkle, electron-updater, Firefox), is the
same: the running app relaunches ITSELF with a hidden flag, in a NEW detached
process, then quits; the new process waits for the old PID to actually exit,
does the swap, then relaunches the real app fresh. See main.py's
`--prism-apply-update` handling, right at the top before QApplication exists.

╔══════════════════════════════════════════════════════════════════════════╗
║ UNVERIFIED ON REAL WINDOWS/macOS HARDWARE — read before touching this.    ║
║                                                                            ║
║ This module was written and tested on Linux only. The Linux swap path    ║
║ (rename a directory out from under a running process) is genuinely       ║
║ tested here — Linux lets you do that, no special handling needed. The    ║
║ Windows and macOS code paths below are implemented per the design in     ║
║ update-research-inapp-download.md §2/§5.4, but TWO assumptions they      ║
║ depend on have never been exercised on real hardware:                    ║
║                                                                            ║
║   Windows: does the OS release the folder/file locks on Prism.exe and    ║
║   its DLLs promptly after the process exits, or does antivirus real-time ║
║   scanning (or the PyInstaller bootloader itself) hold them a while      ║
║   longer? The retry loop in perform_swap() exists for exactly this, but  ║
║   the right retry window is a guess until someone runs the ~30-minute    ║
║   experiment update-plan.md §9 calls for.                                ║
║                                                                            ║
║   macOS: does a .app bundle written to disk by another running app       ║
║   (rather than downloaded via a browser) pick up the same Gatekeeper/    ║
║   quarantine treatment a browser download gets? Untested.                ║
║                                                                            ║
║ Do not remove this banner or treat either path as proven until both      ║
║ have actually been run on the hardware in question.                      ║
╚══════════════════════════════════════════════════════════════════════════╝

Known scope cut (documented, not hidden): startup-success confirmation here
is self-reported — the newly-relaunched Prism has to run far enough to call
confirm_startup_success() before its next restart, or the next launch treats
it as failed and rolls back. This catches "the new version starts and then
crashes" and "the new version never gets past licensing/import". It does NOT
catch "the OS refuses to start the new executable at all" (e.g. a missing
shared library making the process exit before a single line of Python
runs) — that would need a supervisor process watching the relaunched PID's
exit code, which is deferred; see update-plan.md's Phase 3 list.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

PENDING_MARKER = ".prism_update_pending"


class ApplyError(Exception):
    """The swap itself failed — the old tree is put back if at all
    possible before this is raised, so a bad update degrades to "nothing
    happened" rather than "Prism is now broken until reinstalled"."""


# ── is a process still alive? ───────────────────────────────────────────────
def pid_alive(pid: int) -> bool:
    """True if `pid` is a live process on this machine.

    Windows and POSIX genuinely need different mechanisms here — os.kill's
    signal-0 trick (POSIX: "would this signal be delivered") has no Windows
    equivalent, and os.kill on Windows only supports terminating a process,
    not probing one. The Windows branch below is part of the UNVERIFIED
    Windows path this module's docstring warns about; the POSIX branch is
    the one exercised by this module's own tests.
    """
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.wintypes.DWORD()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just owned by someone else — still "alive" for our purposes.
        return True
    return True


def wait_for_exit(pid: int, timeout: float = 30.0, poll: float = 0.2) -> bool:
    """Block until `pid` is gone or `timeout` elapses. Returns whether it
    actually exited — a caller must not proceed to swap files a still-live
    process might have open."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(poll)
    return not pid_alive(pid)


# ── the swap itself ──────────────────────────────────────────────────────
def perform_swap(install_dir: str, staged_dir: str, backup_dir: str, *,
                 retry_seconds: float = 30.0, retry_interval: float = 1.0) -> None:
    """Rename `install_dir` to `backup_dir`, then `staged_dir` to
    `install_dir`. Two renames, not one atomic operation — the same
    limitation every folder-swap updater surveyed in update-research.md
    accepts, because there is no cross-platform atomic "swap two
    directories" primitive. The retry loop is what update-plan.md §9 calls
    out for Windows specifically (antivirus or a lingering handle can hold a
    rename briefly); on Linux this normally succeeds on the first try.

    Raises ApplyError, with the old tree restored to `install_dir` if the
    second rename is what failed (the first rename succeeding but the second
    failing is the one partial-failure state this function must not leave on
    disk — "old build gone, new build not in place" is worse than either
    all-old or all-new).
    """
    if os.path.exists(backup_dir):
        # A backup from a previous update that was never cleaned up (e.g. the
        # confirm step never ran and a rollback already happened once) —
        # clear it rather than fail the whole swap over stale housekeeping.
        shutil.rmtree(backup_dir, ignore_errors=True)

    deadline = time.monotonic() + retry_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            os.rename(install_dir, backup_dir)
            break
        except OSError as e:
            last_error = e
            time.sleep(retry_interval)
    else:
        raise ApplyError(f"Could not move aside {install_dir!r} after "
                         f"{retry_seconds:.0f}s (still in use?): {last_error}")

    try:
        os.rename(staged_dir, install_dir)
    except OSError as e:
        # The one bad partial state: put the old tree straight back.
        try:
            os.rename(backup_dir, install_dir)
        except OSError as restore_error:
            raise ApplyError(
                f"Update swap failed AND could not restore the previous "
                f"install: {e}; restore error: {restore_error}. The install "
                f"at {install_dir!r} may be missing — reinstall from "
                f"{staged_dir!r} or a fresh download.") from e
        raise ApplyError(f"Could not move the new version into place "
                         f"({e}); restored the previous version.") from e


# ── startup-success confirmation & rollback ────────────────────────────────
def confirm_marker_path(install_dir: str) -> str:
    return os.path.join(install_dir, PENDING_MARKER)


def mark_pending_confirm(install_dir: str, from_version: str) -> None:
    """Written right after a successful swap, before relaunching. Its mere
    presence at the NEXT startup means the version that was just swapped in
    never confirmed it started cleanly."""
    with open(confirm_marker_path(install_dir), "w", encoding="utf-8") as f:
        f.write(from_version)


def is_pending_confirm(install_dir: str) -> bool:
    return os.path.isfile(confirm_marker_path(install_dir))


def confirm_startup_success(install_dir: str, backup_dir: str) -> None:
    """Call once the new version has gotten far enough to trust — main.py
    calls this after the main window is up. Clears the marker and drops the
    kept-for-one-launch backup; never raises, since failing to tidy up a
    backup must not be treated as a startup failure."""
    try:
        os.remove(confirm_marker_path(install_dir))
    except OSError:
        pass
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)


def check_and_rollback_if_pending(install_dir: str, backup_dir: str) -> bool:
    """Call at the very start of a normal launch, before anything else that
    could fail. If the previous launch swapped in a version and never
    confirmed it started, put the backup back and report True so the caller
    can surface a "the last update didn't take, we rolled it back" banner.

    A failed update must never be worse than never having offered the
    update-plan.md's S5 — this is what makes that true.
    """
    if not is_pending_confirm(install_dir):
        return False
    try:
        os.remove(confirm_marker_path(install_dir))
    except OSError:
        pass
    if not os.path.isdir(backup_dir):
        # Nothing to roll back to — the marker is stale/orphaned. Leave the
        # (apparently working, since we got this far) current install alone.
        return False
    broken_dir = install_dir + ".failed-update"
    shutil.rmtree(broken_dir, ignore_errors=True)
    try:
        os.rename(install_dir, broken_dir)
        os.rename(backup_dir, install_dir)
    except OSError:
        # Could not even roll back — leave things as they are rather than
        # risk destroying the one tree that might still work.
        return False
    shutil.rmtree(broken_dir, ignore_errors=True)
    return True


# ── spawning the detached apply helper ─────────────────────────────────────
def spawn_detached(argv: list[str]) -> None:
    """Launch `argv` as a process with no lifetime tie to the current one —
    get this wrong (e.g. a plain subprocess.Popen with no flags, whose child
    is killed alongside its parent's process group on some platforms/shells)
    and the swap helper dies the instant Prism calls QApplication.quit(),
    before it has waited for the PID or moved anything. See this module's
    top docstring for why POSIX is the branch actually exercised by tests
    here and Windows is not.
    """
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kwargs)


def begin_apply(pid_to_wait: int, install_dir: str, staged_dir: str,
                backup_dir: str, relaunch_argv: list[str]) -> None:
    """Called by the OLD (currently running) Prism, right before it quits.
    Spawns a detached copy of itself with the special flag; does not wait for
    anything itself — the caller must call QApplication.quit() (or exit)
    immediately after this returns, so the old process's own locks/handles
    are released for the new one to wait on.
    """
    helper_argv = [*relaunch_argv, "--prism-apply-update", str(pid_to_wait),
                  install_dir, staged_dir, backup_dir]
    spawn_detached(helper_argv)


def perform_apply_and_relaunch(pid_to_wait: int, install_dir: str,
                               staged_dir: str, backup_dir: str,
                               relaunch_argv: list[str]) -> int:
    """The detached helper's entire job, called from main.py's
    `--prism-apply-update` branch before QApplication is constructed.
    Returns a process exit code; never raises past this function (a helper
    that crashes with a traceback and no rollback is the worst outcome this
    whole design exists to avoid).
    """
    try:
        if not wait_for_exit(pid_to_wait, timeout=30.0):
            return 1  # old process never exited; leave everything alone.

        # updater.stage_update() writes the outgoing version to a sibling
        # `<staged_dir>.VERSION` file — not inside staged_dir itself, since
        # everything inside staged_dir is about to become the new
        # install_dir and must match the manifest's file list exactly.
        version = ""
        try:
            with open(staged_dir.rstrip(os.sep) + ".VERSION", "r",
                     encoding="utf-8") as f:
                version = f.read().strip()
        except OSError:
            pass

        perform_swap(install_dir, staged_dir, backup_dir)
        mark_pending_confirm(install_dir, version)
        spawn_detached(relaunch_argv)
        return 0
    except ApplyError:
        return 2
    except Exception:  # noqa: BLE001 - this process has no UI to report to
        return 3
