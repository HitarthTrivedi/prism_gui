"""In-app updates.

Phase 0 (shipped 1.3.1, still exactly as it was): know that a newer Prism
exists, and say so. The licence server tells every client, on every lease,
two things it already knew — `latest_version` (advisory) and
`min_supported_version` (enforced server-side). That pair becomes a banner
with a Download button that opens a fixed vendor address. Nothing is fetched
or run.

Phase 1 (this file, added 2026-08-30, see update-research-inapp-download.md):
the real updater — a signed manifest, a staged copy of the new build hash-
verified file by file, a swap on restart via apply_update.py, a rollback if
the new version never confirms it started. Still Qt-free, like licensing/,
so the CLI and tests can use it.

Trust
─────
Phase 0's trust statement still holds for the banner: the two version
strings arrive UNSIGNED beside the signed lease, so they can only ever
*suggest* an update, never cause one. Phase 1 adds a second, separate trust
boundary for the update itself, and it does NOT extend the licence server's
authority to cover it:

  - The manifest is fetched from a FIXED host constant (UPDATE_HOST below),
    never from a URL the licence server or anything else hands us — exactly
    the same rule DEFAULT_SERVER follows in licensing/client.py. The per-file
    assets live in a SEPARATE release, one per (version, platform) — see
    _assets_release_tag — because GitHub caps a release at 1000 assets and
    three platforms' worth of files sharing the manifest's release blew
    past that. Still the same fixed repo (UPDATE_REPO), still never a URL
    handed to us by anything — the tag is derived from the version the
    manifest itself already claims, not a second trust input.
  - The manifest is signed with a key that is NOT the licence server's
    signing key (licensing/keys.py's UPDATE_PRODUCTION/UPDATE_DEVELOPMENT,
    separate from PRODUCTION/DEVELOPMENT) — a licence-server compromise must
    not, by itself, be able to push a malicious "update". See
    update_manifest.py's docstring and update-research-inapp-download.md §4.
  - Nothing downloaded is trusted until its hash matches the manifest, and
    the manifest itself isn't trusted until it verifies AND is newer than
    anything this machine has ever accepted AND hasn't expired. Every one of
    those checks happens before a single byte is written where the running
    install can see it (see stage_update() below) — verify-then-fetch, not
    fetch-then-verify.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import app_meta
import licensing
import paths
import update_manifest
from licensing import store
from licensing.status import LicenseState, newer

STATE_FILENAME = "update_state.json"

_DEFAULT: dict[str, Any] = {
    # The version the customer pressed "Not now" on. Compared exactly: a
    # newer release than the one dismissed shows the banner again, which is
    # the point — "not now" means this one, not for ever.
    "dismissed": "",
    "dismissed_at": 0,
    # Phase 1 — the highest manifest version this machine has ever accepted.
    # A manifest for anything at or below this is refused outright, signature
    # or no signature: this is what stops a captured, still-validly-signed
    # manifest for an old, vulnerable version being replayed to force a
    # downgrade (update-research-inapp-download.md §4 requirement #4).
    "highest_seen_version": "",
    # Set by apply_update.check_and_rollback_if_pending() (called from
    # main.py at startup) when the previous launch's update never confirmed
    # it started and had to be rolled back. Surfaced as a banner once, then
    # cleared — see acknowledge_rollback() below.
    "pending_rollback": False,
    "rolled_back_from": "",
}

# Fixed at build time, exactly like licensing/client.py's DEFAULT_SERVER —
# never overridable at runtime in a frozen build, and never a value taken
# from a server response. GitHub's "latest release" direct-download path
# (releases/latest/download/<asset>) always resolves to whatever the CI
# workflow most recently published, the same way app_meta.DOWNLOAD_URL's
# releases/latest page does today.
UPDATE_REPO = "HitarthTrivedi/prism_gui"
UPDATE_HOST = f"https://github.com/{UPDATE_REPO}/releases/latest/download"

# The per-file assets do NOT live in the same release as the manifest and
# the human-facing archives. GitHub caps a release at 1000 assets — a
# real limit, hit for real shipping v1.4.0 (linux-x64 alone needs 966
# individual files once Playwright's Chromium is in the bundle, and all
# three platforms together need ~2600, nearly 3x the cap, if hosted in
# one release). Each platform's flattened files get their OWN release
# instead, one per (version, platform), tagged deterministically from the
# manifest's own `version` field — never "latest", since three releases
# can't all BE "latest" at once. RELEASING-UPDATES.md's publish step
# creates these alongside the main tagged release.
def _assets_release_tag(version: str, tag: str) -> str:
    return f"v{version}-assets-{tag}"

# Manifest fetch is a background/launch-time check, same spirit as the
# licence server's default TIMEOUT — fail fast, never make launch wait.
MANIFEST_TIMEOUT = 8
# A manifest is a JSON file list, never a payload — a few hundred files at
# ~150 bytes of JSON each is nowhere near this. Generous on purpose (a big
# release with thousands of files must not trip it) while still bounding a
# compromised/misconfigured host to something Prism can safely buffer at
# every launch's background check.
MANIFEST_MAX_BYTES = 4 * 1024 * 1024
# A file download is not something the customer is passively waiting through
# the way an authorize call is; it has a progress indicator. Generous, but
# still bounded — a hung connection must eventually give up.
FILE_TIMEOUT = 60


# ── the state file (unchanged shape, Phase 1 fields added to _DEFAULT) ──────
def state_path() -> str:
    """~/.prism/update_state.json. Beside license.json, through the same
    user_dir() the tests redirect, so a test can never dismiss a real
    customer's banner."""
    return os.path.join(licensing.user_dir(), STATE_FILENAME)


def _load() -> dict[str, Any]:
    return store.read_json(state_path(), _DEFAULT)


def _save(data: dict[str, Any]) -> None:
    store.write_json(state_path(), {**_DEFAULT, **data})


# ── what the server said, against what is running (Phase 0, unchanged) ─────
def available(state: LicenseState | None = None,
              running: str | None = None) -> str:
    """The newer version the server knows about, or "" if this IS the newest
    (or nobody has told us otherwise). Never raises: an unparseable answer
    is "no advice", not "update now"."""
    state = licensing.state() if state is None else state
    running = app_meta.VERSION if running is None else running
    latest = (state.latest_version or "").strip()
    return latest if newer(latest, running) else ""


def required(state: LicenseState | None = None,
             running: str | None = None) -> bool:
    """Has the server's floor moved above this build?

    True means the server has ALREADY stopped leasing to this build — the
    refusal is theirs, this only repeats it. The app still opens and History
    still works; what changes is the banner's wording, from "there is a newer
    one" to "update to continue".
    """
    state = licensing.state() if state is None else state
    running = app_meta.VERSION if running is None else running
    return newer((state.min_supported_version or "").strip(), running)


def target(state: LicenseState | None = None,
           running: str | None = None) -> str:
    """The version to tell the customer to get: the newest we know of, or
    failing that the floor itself — a floor with no `latest` beside it is a
    misconfigured server, and the banner should still name a number."""
    state = licensing.state() if state is None else state
    return (available(state, running)
            or (state.min_supported_version or "").strip())


# ── "Not now" (Phase 0, unchanged) ──────────────────────────────────────────
def dismissed(version: str) -> bool:
    """Has the customer already waved THIS version away?"""
    version = (version or "").strip()
    return bool(version) and _load().get("dismissed") == version


def dismiss(version: str) -> None:
    """Hide the banner for this version. Never raises — a full disk must not
    turn "Not now" into a crash; the worst case is the banner coming back."""
    version = (version or "").strip()
    if not version:
        return
    try:
        _save({**_load(), "dismissed": version, "dismissed_at": int(time.time())})
    except Exception:                               # noqa: BLE001
        pass


def download_url() -> str:
    """Where the Download button falls back to when Phase 1 can't run (no
    manifest, download failed, unsupported platform). Fixed at build time on
    purpose."""
    return app_meta.DOWNLOAD_URL


# ══════════════════════════════════════════════════════════════════════════
# Phase 1 — the real updater
# ══════════════════════════════════════════════════════════════════════════

class UpdateError(Exception):
    """Anything in the Phase 1 pipeline that stops an update from being
    fetched, verified, or staged. Never a reason to crash Prism — every
    caller in main_window.py must catch this and fall back to the Phase 0
    "open the download page" behaviour."""


@dataclass
class UpdateCheck:
    """The result of check_for_update() — a verified, not-yet-downloaded
    manifest. Safe to hold onto and show in a banner; nothing has been
    fetched or written yet beyond the manifest itself."""
    version: str
    manifest: dict[str, Any]


@dataclass
class StagedUpdate:
    """The result of stage_update() — a complete, hash-verified copy of the
    new version sitting under ~/.prism/updates/<version>/, ready to apply.
    Nothing in the running install has been touched."""
    version: str
    stage_dir: str
    manifest: dict[str, Any]


def updates_root() -> str:
    # licensing.user_dir() takes no arguments — it's a zero-arg wrapper
    # around paths.user_dir(). The variadic one that takes a subdirectory
    # is paths.user_dir(*parts) itself, which every other caller in this
    # codebase (workspace.py, diagnostics.py, i18n.py, integrations/
    # gdrive.py) already uses this way. Calling licensing.user_dir("updates")
    # here was a straight mix-up between the two — TypeError, unconditionally,
    # on every single stage_update() call, since this is the first line it
    # runs. UpdateWorker's blanket `except Exception` then routed that
    # crash into the same "just open the browser" fallback as a genuine
    # "no update available", which is exactly why this went unnoticed: the
    # symptom looked identical to the ordinary no-op case.
    return paths.user_dir("updates")


def _highest_seen_version() -> str:
    return str(_load().get("highest_seen_version") or "")


def _record_seen_version(version: str) -> None:
    current = _highest_seen_version()
    if not current or newer(version, current):
        try:
            _save({**_load(), "highest_seen_version": version})
        except Exception:                           # noqa: BLE001
            pass


def acknowledge_rollback() -> None:
    """Clear the one-time 'we rolled back a failed update' banner state."""
    try:
        _save({**_load(), "pending_rollback": False, "rolled_back_from": ""})
    except Exception:                                # noqa: BLE001
        pass


def note_rollback(from_version: str) -> None:
    """Called from main.py right after apply_update reports a rollback
    happened, so the banner can say so once."""
    try:
        _save({**_load(), "pending_rollback": True,
              "rolled_back_from": from_version})
    except Exception:                                # noqa: BLE001
        pass


def _get(url: str, *, timeout: int, fetch: Callable[..., Any] | None = None,
        max_bytes: int | None = None) -> bytes:
    """The one place Phase 1 touches the network for a GET. `fetch` is an
    injection point for tests — production callers leave it unset and get a
    real `requests.get`, the same local-import-of-requests style
    licensing/client.py uses so `import updater` stays cheap at startup.

    `max_bytes`, when given, bounds only the real-network path: the response
    is streamed and cut off the instant more than `max_bytes` has actually
    arrived, rather than buffered to `.content` first and measured after —
    the latter would still let a compromised or misconfigured host exhaust
    memory/bandwidth before the post-hoc size check ever runs, which is
    exactly the "don't trust Content-Length alone" resource-exhaustion vector
    update-research-inapp-download.md §4 requirement #3 calls out. `fetch`
    test doubles are unaffected — a test already controls exactly what bytes
    come back, so there's nothing for a cap to protect against there."""
    if fetch is not None:
        return fetch(url, timeout=timeout)
    import requests  # local import: see module docstring / client.py parity
    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    if max_bytes is None:
        return response.content
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise UpdateError(
                f"Response from {url} exceeded the expected size "
                f"({max_bytes} bytes) — aborted before reading the rest.")
        chunks.append(chunk)
    return b"".join(chunks)


def platform_tag() -> str:
    """The exact `<os>-<arch>` string packaging/build.py's STEM uses
    (its OS_TAG-ARCH). Duplicated here rather than imported — build.py is a
    packaging-time script that pulls in PyInstaller/Nuitka machinery and has
    no business being importable from the shipped app.

    Namespaces the manifest and every asset URL below so Linux, Windows and
    macOS — which all publish to the SAME GitHub Release, per build.yml's
    `release` job — never collide on a flattened filename that happens to
    match across OSes. Every platform's build has a file at, say,
    `_internal/base_library.zip`, with completely different bytes each time;
    without this prefix the three platforms' CI jobs would overwrite each
    other's asset of the same flattened name.
    """
    if sys.platform.startswith("win"):
        os_tag = "windows"
    elif sys.platform == "darwin":
        os_tag = "macos"
    else:
        os_tag = "linux"
    arch = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64",
           "arm64": "arm64"}.get(platform.machine(), platform.machine())
    return f"{os_tag}-{arch}"


def _manifest_url() -> str:
    return f"{UPDATE_HOST}/manifest.{platform_tag()}.signed"


def _file_url(version: str, relpath: str) -> str:
    # GitHub release assets can't contain "/" in their filename, so a
    # relative path is flattened for the wire and restored on write. This is
    # a hosting-layer detail, not a security one — the manifest's own `path`
    # field (unflattened) is what every hash check and staged-tree layout is
    # keyed on. Platform-prefixed for the same reason _manifest_url() is.
    #
    # update_manifest.flat_name(), not an inline f-string here: past 255
    # bytes (a real case — Chromium's macOS Framework path) the flattened
    # name has to fall back to a hash, and packaging/flatten_update_assets.py
    # (which wrote the file under this exact name at build time) needs to
    # compute the identical fallback. One function, not two that have to
    # agree by convention.
    #
    # A DIFFERENT release from _manifest_url()'s (see _assets_release_tag
    # above) — `releases/download/<tag>/<asset>`, an explicit tag, never
    # "latest": three platforms' per-file assets living in the shared
    # "latest" release is what hit GitHub's 1000-assets-per-release cap in
    # the first place. `version` comes from the manifest THIS SAME CALLER
    # already verified (see stage_update's `check.version`), never from
    # anywhere else — the tag is derived data, not a second trust input.
    tag = _assets_release_tag(version, platform_tag())
    return (f"https://github.com/{UPDATE_REPO}/releases/download/{tag}/"
           f"{update_manifest.flat_name(platform_tag(), relpath)}")


def check_for_update(*, running: str | None = None,
                     fetch: Callable[..., Any] | None = None) -> UpdateCheck | None:
    """Fetch and verify the manifest; return it if it describes a version
    newer than what's running AND newer than anything this machine has ever
    accepted. Cheap and safe to call at every launch or on a timer — this
    downloads one small signed JSON blob, nothing more, and never raises for
    an ordinary "no update" or "server unreachable" outcome (returns None).

    Raises UpdateError only for something worth logging (a manifest that
    exists but fails verification) — not for "there is no update".
    """
    running = app_meta.VERSION if running is None else running
    try:
        raw = _get(_manifest_url(), timeout=MANIFEST_TIMEOUT, fetch=fetch,
                  max_bytes=MANIFEST_MAX_BYTES)
    except Exception:                                # noqa: BLE001 — no network is routine
        return None

    try:
        token = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        payload = update_manifest.verify(
            token, public_keys=licensing.keys.update_public_keys())
    except update_manifest.ManifestError as e:
        raise UpdateError(f"Update manifest failed verification: {e}") from e

    version = payload["version"]
    highest = _highest_seen_version()
    if highest and not newer(version, highest):
        return None  # not newer than something we've already accepted — ignore
    if not newer(version, running):
        return None  # not newer than what's running — nothing to offer

    return UpdateCheck(version=version, manifest=payload)


def _local_file_matches(install_dir: str, entry: dict[str, Any]) -> bool:
    full = os.path.join(install_dir, entry["path"])
    if "symlink" in entry:
        return os.path.islink(full) and os.readlink(full) == entry["symlink"]
    if not os.path.isfile(full):
        return False
    try:
        if os.path.getsize(full) != entry["size"]:
            return False
        return update_manifest.sha256_file(full) == entry["sha256"]
    except OSError:
        return False


def _files_to_fetch(manifest: dict[str, Any], install_dir: str) -> list[dict[str, Any]]:
    """Files whose manifest entry the local install doesn't already satisfy —
    this is the whole size win (update-research-inapp-download.md §1/§3): a
    code-only release only needs the handful of files that actually changed,
    not the ~210+ MB archive."""
    return [entry for entry in manifest["files"]
           if not _local_file_matches(install_dir, entry)]


def stage_update(check: UpdateCheck, install_dir: str, *,
                 fetch: Callable[..., Any] | None = None,
                 on_progress: Callable[[int, int], None] | None = None) -> StagedUpdate:
    """Download whatever changed, copy the rest from the current install,
    and verify the WHOLE staged tree against the manifest before returning —
    only a StagedUpdate this function itself has fully re-checked is ever
    handed back. Nothing under `install_dir` is modified; everything happens
    under a fresh directory in updates_root().

    Raises UpdateError on any verification failure, including partway
    through a download — a half-verified stage is never left "armed" for
    apply_update to pick up.
    """
    import shutil

    manifest = check.manifest
    stage_dir = os.path.join(updates_root(), check.version)
    if os.path.isdir(stage_dir):
        shutil.rmtree(stage_dir, ignore_errors=True)
    os.makedirs(stage_dir, exist_ok=True)

    to_fetch = {e["path"] for e in _files_to_fetch(manifest, install_dir)}
    files = manifest["files"]
    total = len(files)

    try:
        for i, entry in enumerate(files):
            dest = os.path.join(stage_dir, entry["path"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            if "symlink" in entry:
                if os.path.islink(dest) or os.path.exists(dest):
                    os.remove(dest)
                try:
                    os.symlink(entry["symlink"], dest)
                except OSError as e:
                    # Windows treats creating a symlink as a PRIVILEGE: without
                    # Administrator or Developer Mode it raises WinError 1314,
                    # "A required privilege is not held by the client".
                    #
                    # A Windows bundle should contain no symlinks, so this
                    # should never fire there — but "should" is doing a lot of
                    # work in the one code path that rewrites a customer's
                    # installation, and the alternative is a bare OSError
                    # surfacing after the whole update has been downloaded,
                    # with nothing to tell them what to do. Surfaced on the
                    # first Windows CI run of the suite, as four tests that
                    # create a symlink to exercise this branch.
                    raise UpdateError(
                        f"{entry['path']}: this computer would not let Prism "
                        f"create a shortcut file ({e}). On Windows that needs "
                        "Administrator rights or Developer Mode. Nothing has "
                        "been changed — the update was staged, not applied."
                    ) from e
            elif entry.get("size") == 0:
                # GitHub Releases refuses to host a zero-byte asset at all
                # ("size must be greater than or equal to 1") — confirmed
                # against the real API while publishing 1.3.1's assets, not
                # theorised. There is nothing ambiguous about an empty
                # file's content, so there is nothing to fetch: create it
                # directly. Without this, any release containing so much as
                # one empty file (a Python `py.typed` marker, for instance)
                # would 404 on this path and fail every customer's update.
                open(dest, "wb").close()
                if entry.get("mode"):
                    os.chmod(dest, 0o644 | entry["mode"])
            elif entry["path"] in to_fetch:
                url = _file_url(check.version, entry["path"])
                # max_bytes cuts the stream off the instant more than the
                # manifest's declared size has arrived — see _get()'s
                # docstring for why this is done during the read, not as a
                # check on the fully-buffered result.
                data = _get(url, timeout=FILE_TIMEOUT, fetch=fetch,
                           max_bytes=entry["size"])
                # Exact-size check BEFORE trusting anything else about the
                # payload — never rely on a Content-Length header alone (a
                # compromised or misconfigured host could lie about it); this
                # checks the bytes actually received (max_bytes above only
                # rejects TOO MANY; a short/truncated download still needs
                # catching here).
                if len(data) != entry["size"]:
                    raise UpdateError(
                        f"{entry['path']}: downloaded {len(data)} bytes, "
                        f"manifest says {entry['size']}.")
                import hashlib
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise UpdateError(f"{entry['path']}: hash mismatch after download.")
                with open(dest, "wb") as f:
                    f.write(data)
                if entry.get("mode"):
                    os.chmod(dest, 0o644 | entry["mode"])
            else:
                src = os.path.join(install_dir, entry["path"])
                shutil.copy2(src, dest)
                if entry.get("mode"):
                    os.chmod(dest, 0o644 | entry["mode"])

            if on_progress:
                on_progress(i + 1, total)

        # Re-verify the ENTIRE staged tree, including files that were just
        # copied unchanged from the current install — cheap, and it's what
        # catches a corrupted local copy that happened to match on size
        # alone, or a manifest/build mismatch, before this is ever handed to
        # apply_update.py as "safe to swap in".
        for entry in files:
            full = os.path.join(stage_dir, entry["path"])
            if "symlink" in entry:
                if not (os.path.islink(full)
                       and os.readlink(full) == entry["symlink"]):
                    raise UpdateError(f"{entry['path']}: staged symlink mismatch.")
                continue
            if (not os.path.isfile(full)
                   or os.path.getsize(full) != entry["size"]
                   or update_manifest.sha256_file(full) != entry["sha256"]):
                raise UpdateError(f"{entry['path']}: staged copy failed final verification.")
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise

    # apply_update.perform_apply_and_relaunch() reads the outgoing version
    # from a `<stage_dir>.VERSION` file beside the staged tree, since it runs
    # as a separate process with no manifest of its own to consult, and
    # the version marker must not itself become a file inside install_dir
    # once the swap moves stage_dir into place.
    with open(stage_dir + ".VERSION", "w", encoding="utf-8") as f:
        f.write(check.version)

    _record_seen_version(check.version)
    return StagedUpdate(version=check.version, stage_dir=stage_dir, manifest=manifest)


def install_dir() -> str:
    """Root of the installed onedir folder — the directory containing the
    running executable and everything apply_update.py's swap touches.
    `sys.executable` in a frozen PyInstaller build points at the bundled
    executable itself (e.g. `.../Prism/Prism`), so its parent is the
    top-level folder that contains both the exe and `_internal/` — the same
    "extracted folder" update-research-inapp-download.md's whole design is
    built around. Deliberately NOT paths.bundle_dir(): that resolves to
    sys._MEIPASS, which PyInstaller onedir builds may point at a subfolder
    (`_internal/`) rather than the install root, and getting this path wrong
    would make perform_swap() rename the wrong directory.

    Only meaningful for a frozen build — a source checkout has no single
    "installed folder" to swap, so Phase 1 self-update does not apply to it.
    """
    if not paths.is_frozen():
        raise UpdateError("Self-update only applies to a packaged build, "
                          "not a source checkout.")
    import sys
    return os.path.dirname(sys.executable)


def relaunch_argv() -> list[str]:
    """What apply_update should re-exec, before and after the swap. A frozen
    build re-runs its own executable; running from source re-runs
    `python3 main.py` the same way the customer originally launched it."""
    import sys
    if paths.is_frozen():
        return [sys.executable]
    return [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "main.py")]


def begin_apply(staged: StagedUpdate, install_dir: str) -> None:
    """Hand off to apply_update.py: spawn the detached helper that will wait
    for THIS process to exit, then perform the swap. The caller (Qt code in
    main_window.py) must call QApplication.quit() immediately after this
    returns — see apply_update.begin_apply()'s docstring for why the timing
    matters. Kept as a thin pass-through here (rather than importing
    apply_update directly from main_window.py) so every Phase 1 entry point
    a caller needs lives in this one Qt-free module.
    """
    import apply_update

    backup_dir = install_dir.rstrip(os.sep) + ".old"
    apply_update.begin_apply(os.getpid(), install_dir, staged.stage_dir,
                             backup_dir, relaunch_argv())
