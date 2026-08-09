"""Keep the machine awake while a run is going.

A Prism run is twenty to forty minutes of browser automation, and the whole
pitch is that you start it and walk away. A MacBook's default display sleep is
well under that, and when the machine sleeps the browser session goes with it
— the customer comes back to a half-finished run and no explanation.

So a run holds a wake lock for its duration and drops it at the end, whether
it finished, failed or was stopped.

Deliberately narrow: this prevents IDLE sleep only. Closing the lid still
sleeps the machine on every platform, and it should — nobody wants a laptop
cooking in a bag because Prism forgot to let go.
"""
from __future__ import annotations

import subprocess
import sys

_holder = None          # the caffeinate process on macOS
_depth = 0              # nested runs (a queue) release once, at the end


def _start() -> None:
    global _holder
    if sys.platform == "darwin":
        # -i idle, -m disk. Not -d: the display may sleep, and should — the
        # user has walked away and the automation does not need the screen.
        try:
            _holder = subprocess.Popen(
                ["caffeinate", "-i", "-m"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError):
            _holder = None
    elif sys.platform == "win32":
        try:
            import ctypes
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED — hold until told otherwise.
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
            _holder = "win"
        except Exception:                               # noqa: BLE001
            _holder = None
    # Linux is left alone on purpose: the answer differs per desktop
    # environment (systemd-inhibit, xdg-screensaver, GNOME's own D-Bus API),
    # and guessing wrong either does nothing or leaves an inhibitor behind.


def _stop() -> None:
    global _holder
    if _holder is None:
        return
    if sys.platform == "darwin":
        try:
            _holder.terminate()
        except Exception:                               # noqa: BLE001
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # release
        except Exception:                               # noqa: BLE001
            pass
    _holder = None


def acquire() -> None:
    """Hold the machine awake. Safe to nest — a queue of five tasks acquires
    five times and only really releases after the fifth."""
    global _depth
    _depth += 1
    if _depth == 1:
        _start()


def release() -> None:
    global _depth
    _depth = max(0, _depth - 1)
    if _depth == 0:
        _stop()


def release_all() -> None:
    """Drop the lock no matter how deep. For app shutdown, where an unbalanced
    acquire would otherwise leave `caffeinate` running after Prism is gone."""
    global _depth
    _depth = 0
    _stop()


def held() -> bool:
    return _depth > 0
