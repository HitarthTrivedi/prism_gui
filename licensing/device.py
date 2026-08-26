"""Machine fingerprint — one machine, one seat.

Seats are counted per computer, not per user account: a shared workstation in a
drawing office is one seat no matter how many people log into it.

What we send is a salted hash, never the raw hardware id. The salt means that
even if the licence database leaks, it contains nothing that identifies a
customer's actual hardware.

The identifiers below change when a machine is reimaged or its OS reinstalled.
That is not a bug we can fix here — it is why seat release has to be easy, both
self-service in Setup and manually from admin. Expect it to be the most common
support ticket.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import uuid

# Bump only if the fingerprinting scheme itself changes — every existing
# activation would need re-doing, so this is close to a one-way door.
SALT = b"PRISM-DEVICE-V1"

# Which source produced the id. Logged and reported, because the `random` tier
# means a reinstall silently consumes a new seat and we want that visible
# rather than mysterious.
TIER_PLATFORM = "platform"
TIER_MAC = "mac"
TIER_RANDOM = "random"

_cache: tuple[str, str] | None = None


def _read_first(*paths: str) -> str:
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                value = f.read().strip()
            if value:
                return value
        except OSError:
            continue
    return ""


def _linux_id() -> str:
    return _read_first("/etc/machine-id", "/var/lib/dbus/machine-id")


def _macos_id() -> str:
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if "IOPlatformUUID" in line:
            _, _, tail = line.partition("=")
            return tail.strip().strip('"')
    return ""


def _windows_id() -> str:
    try:
        import winreg
    except ImportError:
        return ""
    try:
        # KEY_WOW64_64KEY matters: a 32-bit Python on 64-bit Windows is
        # otherwise redirected to the WOW6432Node view, which has no
        # MachineGuid — the fingerprint would silently fall through to the MAC
        # tier on exactly the machines least likely to be tested.
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip()
    except OSError:
        return ""


def _mac_address() -> str:
    node = uuid.getnode()
    # getnode() sets the multicast bit when it had to invent a random address,
    # which would give us a different "machine" on every launch. Refuse it and
    # fall through to the persisted tier, which at least stays put.
    if node >> 40 & 0x01:
        return ""
    return f"{node:012x}"


def _persisted_random(user_dir: str) -> str:
    """A random id, written once and read back on every later launch.

    The write is retried and verified rather than fired-and-forgotten: on this
    tier there is no OS-given identity to fall back to, so if this id does not
    actually make it to disk, the NEXT launch cannot find it either, mints a
    fresh uuid4 of its own, and this machine's fingerprint changes on every
    single start — which is indistinguishable, from the customer's chair, from
    "Prism keeps asking for the licence key". That failure mode is worth a
    retry and a log line; it is not worth refusing to start over.
    """
    path = os.path.join(user_dir, "device_id")
    existing = _read_first(path)
    if existing:
        return existing
    value = uuid.uuid4().hex
    last_error = ""
    # Two attempts, with a short pause between them: the usual cause of a
    # failure here is something transient holding the file for a moment — an
    # antivirus scan, a backup agent, a sync client — not a genuinely
    # unwritable directory, and those clear up in well under a second.
    for attempt in range(2):
        try:
            os.makedirs(user_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(value)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(path, 0o600)
        except OSError as e:
            last_error = str(e)
        else:
            # Read it back rather than trusting the write call succeeding —
            # a redirected or virtualised filesystem can accept a write and
            # silently not persist it, which a bare `except OSError` would
            # never catch.
            if _read_first(path) == value:
                return value
            last_error = "file did not read back with the value just written"
        if attempt == 0:
            time.sleep(0.1)
    # Both attempts failed. Returning the value anyway keeps THIS launch
    # working — refusing to start over a storage problem would be a worse bug
    # than the one being worked around — but every future launch will mint
    # ANOTHER new random id and see this as a new device, silently spending a
    # seat each time. Unlike the old silent `except OSError: pass`, that is
    # now at least knowable after the fact rather than a mystery support
    # ticket with no trail.
    try:
        import diagnostics
        diagnostics.write(
            "WARN",
            f"device id: could not persist {path} ({last_error}) — this "
            "machine's licence fingerprint will change on every launch, "
            "which looks like the licence needing re-entry each time.")
    except Exception:                                   # noqa: BLE001
        pass
    return value


def raw_identity(user_dir: str) -> tuple[str, str]:
    """The unhashed machine id and which tier produced it."""
    if sys.platform.startswith("linux"):
        native = _linux_id()
    elif sys.platform == "darwin":
        native = _macos_id()
    elif os.name == "nt":
        native = _windows_id()
    else:
        native = ""

    if native:
        return native, TIER_PLATFORM
    mac = _mac_address()
    if mac:
        return mac, TIER_MAC
    return _persisted_random(user_dir), TIER_RANDOM


def fingerprint(user_dir: str) -> tuple[str, str]:
    """Salted, truncated hash of this machine's id, plus its tier.

    16 hex characters (64 bits): collisions are not a practical concern at this
    scale, and it stays short enough to read out in a support call.
    """
    global _cache
    if _cache is None:
        native, tier = raw_identity(user_dir)
        digest = hashlib.sha256(SALT + native.encode("utf-8")).hexdigest()
        _cache = (digest[:16], tier)
    return _cache


def reset_cache() -> None:
    """Tests only — the fingerprint is stable for a process's lifetime."""
    global _cache
    _cache = None
