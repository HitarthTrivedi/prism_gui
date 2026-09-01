"""The update manifest — format, hashing, signing input, and verification.

A manifest is a signed list of every file in a Prism release: `{path, size,
sha256, mode}` for each one, plus the version it describes and an
expiry. `updater.py` fetches one of these (Phase 1, see
update-research-inapp-download.md) to decide what changed since the copy on
disk, and to verify what it downloads before ever touching the installed
tree.

Wire format, deliberately parallel to `licensing/token.py`:

    PRSMUv1.<b64url(payload_json)>.<b64url(ed25519_sig)>

`PRSMUv1` rather than `PRSMv1` on purpose — a manifest signed with the
update key must never verify as a licence token or vice versa, even though
both are short Ed25519-signed JSON blobs. The version prefix is covered by
the signature (see signing_input()) for the same reason token.py's is: a
signature over one prefix must not verify under the other.

This module is Qt-free, like updater.py and licensing/, so devtools tooling,
the CLI and tests can all use it without pulling in a GUI.

Trust boundary (see update-research-inapp-download.md §4 — read that before
changing anything here):
  - Nothing here executes or overwrites anything. This module only answers
    "is this manifest genuine, and what does it claim" — the swap itself
    lives in apply_update.py, and is only ever reached after updater.py has
    walked every one of these checks.
  - Signature verification happens before any field of the payload is
    trusted for anything besides picking the right key (`kid`) — the same
    discipline token.py's verify() uses.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from licensing.token import b64u_decode, b64u_encode

PREFIX = "PRSMUv1"

# How long a signed manifest stays usable after it's signed. A shorter window
# than a licence token's, on purpose: a manifest is only ever fetched right
# before it's acted on, never cached for offline use the way a licence is, so
# there is no cost to keeping this short — and a short window is what limits
# how long a captured, still-validly-signed manifest for a vulnerable version
# could be replayed if one were ever stolen off a release host.
DEFAULT_VALIDITY_DAYS = 90


class ManifestError(Exception):
    """A manifest that is malformed, forged, expired, or for a version this
    client must not move to. Carries a stable `code`, the same discipline as
    licensing.token.TokenError, so callers can tell "not ours" apart from
    "ours, but not something to act on"."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ── per-file facts the manifest and the local tree are both judged by ──────
def sha256_file(path: str) -> str:
    """Streamed, so a 200MB executable doesn't need to fit in memory twice
    (once as the file, once as a copy read() would otherwise hand back)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_mode(path: str) -> int:
    """Just the executable bits, not the full stat mode. A manifest that
    stored full permissions (including group/other write, setuid, ...) would
    be replaying whatever the build machine's umask happened to be onto every
    customer's disk — the only bit a customer's Prism ever actually needs
    restored on a downloaded file is "can this be run"."""
    st = os.stat(path, follow_symlinks=False)
    return stat.S_IMODE(st.st_mode) & 0o111


# Ext4, APFS, NTFS and HFS+ all cap a single filename component at 255
# bytes — not the whole path, just the last segment. Flattening never hits
# that for an ordinary tree, but Chromium's macOS build does: a bundled
# "Google Chrome for Testing.app" nests deep (Contents/Frameworks/…
# .framework/Versions/<ver>/…), and Google's own naming is verbose enough
# that platform_tag + "__" + the whole flattened relative path blows past
# 255 on its own — the actual failure, once (see packaging/
# flatten_update_assets.py's CI run for v1.4.0, 2026-08-31).
_MAX_FLAT_NAME = 255

# GitHub silently REWRITES a release asset's filename on upload for any
# character outside this set — no error, no warning, `gh release upload`
# exits 0 either way. Confirmed against the real API while fixing v1.4.0:
# "[Content_Types].xml" landed as ".Content_Types.xml" (both `[` and `]`
# became `.`), "First Run" landed as "First.Run" (the space became `.`).
# Uploading under our intended name and then asking for that same name
# back at fetch time 404s forever — the file is THERE, just under a name
# neither side ever asked for. Matching this pattern before upload, not
# after discovering the mismatch, is what keeps upload and fetch agreeing.
_GITHUB_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def flat_name(platform_tag: str, rel: str) -> str:
    """The GitHub Release asset name for one file — shared by
    packaging/flatten_update_assets.py (writing it at build time) and
    updater.py's `_file_url()` (reading it back at runtime), so there is
    exactly one implementation to keep in sync, not two that must agree by
    convention. `rel` is a manifest entry's `path` field: relative, `/`-
    separated, exactly what `build()` below records.

    Ordinarily just `<platform_tag>__<rel with / as __>`, readable and
    reversible by eye. Falls back to a name built from a hash of the same
    (platform_tag, rel) pair — still deterministic, still exactly
    reproducible by both call sites, just no longer human-readable — for
    either of two reasons: past `_MAX_FLAT_NAME` bytes, or containing any
    character GitHub itself would silently rewrite on upload (see
    _GITHUB_SAFE_NAME above). The extension is kept where there is one,
    purely so a directory listing still hints at what a hashed file is.
    """
    name = f"{platform_tag}__{rel.replace('/', '__')}"
    if (len(name.encode("utf-8")) <= _MAX_FLAT_NAME
           and _GITHUB_SAFE_NAME.match(name)):
        return name
    digest = hashlib.sha256(f"{platform_tag}/{rel}".encode("utf-8")).hexdigest()
    ext = os.path.splitext(rel)[1]
    if len(ext) > 16 or not _GITHUB_SAFE_NAME.match(ext.lstrip(".")):
        ext = ""                     # not a real, upload-safe extension
    return f"{platform_tag}__long__{digest}{ext}"


# ── building the (unsigned) payload ─────────────────────────────────────────
def build(root_dir: str, version: str) -> dict[str, Any]:
    """Walk `root_dir` (a built app directory, e.g. dist/Prism) and list every
    file relative to it. Deterministic — same tree in, same manifest out,
    modulo `created`/`expires` which the caller stamps at signing time, not
    here — so this half is testable with an ordinary throwaway directory and
    needs no real PyInstaller build to exercise."""
    files: list[dict[str, Any]] = []
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root_dir).replace(os.sep, "/")
            if os.path.islink(full):
                files.append({
                    "path": rel,
                    "symlink": os.readlink(full),
                })
                continue
            files.append({
                "path": rel,
                "size": os.path.getsize(full),
                "sha256": sha256_file(full),
                "mode": file_mode(full),
            })
    files.sort(key=lambda f: f["path"])
    return {"version": version, "files": files}


def add_archive(manifest: dict[str, Any], archive_path: str) -> dict[str, Any]:
    """Record the full distributable archive (the tar.gz/zip/dmg a human
    downloads by hand today) alongside the per-file list, so a client that
    can't or won't do a file-level update — a first install, or a version gap
    too old for anything in `files` to line up against — has a verified
    fallback: download the whole archive, check it against one hash, done."""
    manifest = dict(manifest)
    manifest["archive"] = {
        "name": os.path.basename(archive_path),
        "size": os.path.getsize(archive_path),
        "sha256": sha256_file(archive_path),
    }
    return manifest


# ── signing (devtools/sign_manifest.py calls this; never at runtime) ───────
def sign(manifest: dict[str, Any], priv_key_hex: str, *,
         validity_days: int = DEFAULT_VALIDITY_DAYS,
         kid: str = "u1", now: int | None = None) -> str:
    """Stamp `created`/`expires` and produce the PRSMUv1 token.

    Called only from a human's machine (devtools/sign_manifest.py) — never
    from anything CI or the license server can trigger unattended, per
    update-research-inapp-download.md §5.2 requirement #2. This function does
    not enforce that; it can't, from inside a library call. The enforcement is
    organisational (where the private key lives) plus sign_manifest.py's own
    downgrade check.
    """
    now = int(time.time()) if now is None else now
    payload = {
        **manifest,
        "kid": kid,
        "created": now,
        "expires": now + validity_days * 86400,
    }
    payload_b64 = b64u_encode(json.dumps(payload, sort_keys=True).encode("utf-8"))
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_key_hex))
    sig = priv.sign(signing_input(payload_b64))
    return f"{PREFIX}.{payload_b64}.{b64u_encode(sig)}"


def signing_input(payload_b64: str) -> bytes:
    """See token.signing_input's docstring — same reasoning, same shape: the
    prefix is inside what's signed, so a PRSMUv1 signature can never be
    replayed as a PRSMv1 (licence) signature or any future manifest version,
    even if the payload segment were byte-identical."""
    return f"{PREFIX}.{payload_b64}".encode("utf-8")


# ── verification (updater.py calls this; this IS the trust boundary) ──────
def verify(token: str, *, public_keys: dict[str, str],
           now: int | None = None) -> dict[str, Any]:
    """Check a manifest's integrity and freshness; return its payload.

    Raises ManifestError on anything suspicious. Mirrors
    licensing.token.verify()'s step ordering deliberately — this codebase
    already reviewed that ordering once, and a manifest is the same shape of
    problem (signed claims from a party we don't fully trust, evaluated
    offline against a key baked into the build).

    Does NOT check monotonic-version-against-what-we've-seen — that needs
    updater.py's persisted state (~/.prism/update_state.json), which this
    Qt-free, state-free module deliberately has no access to. Callers MUST
    do that check too; see updater.py's fetch_and_verify_manifest().
    """
    now = int(time.time()) if now is None else now

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ManifestError("malformed", "Update manifest is not in the "
                                          "expected format.")
    version_tag, payload_b64, sig_b64 = parts
    if version_tag != PREFIX:
        raise ManifestError("version", f"Unsupported manifest version "
                                        f"{version_tag!r}.")

    try:
        payload = json.loads(b64u_decode(payload_b64))
    except (ValueError, Exception) as e:  # noqa: BLE001 - b64/json both raise here
        raise ManifestError("malformed", "Update manifest payload is "
                                          "unreadable.") from e
    if not isinstance(payload, dict):
        raise ManifestError("malformed", "Update manifest payload is not "
                                          "an object.")

    kid = payload.get("kid")
    pub_hex = public_keys.get(kid) if isinstance(kid, str) else None
    if not pub_hex:
        raise ManifestError("unknown_key", "This update was signed with a "
                                            "key this build does not "
                                            "recognise.")

    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(b64u_decode(sig_b64), signing_input(payload_b64))
    except (InvalidSignature, ValueError, Exception) as e:  # noqa: BLE001
        raise ManifestError("bad_signature", "This update's signature does "
                                              "not check out.") from e

    expires = payload.get("expires")
    if not isinstance(expires, (int, float)) or now > expires:
        raise ManifestError("expired", "This update's manifest has expired "
                                        "— ask Prism to check again.")

    if not isinstance(payload.get("version"), str) or not payload.get("version"):
        raise ManifestError("malformed", "Update manifest has no version.")
    files = payload.get("files")
    if not isinstance(files, list):
        raise ManifestError("malformed", "Update manifest has no file list.")
    for entry in files:
        _check_safe_path(entry.get("path") if isinstance(entry, dict) else None)

    return payload


def _check_safe_path(path: Any) -> None:
    """Defense-in-depth, not the primary control: a manifest that fails to
    verify above never reaches here, so this only matters if the *signing*
    tooling itself ever emitted a bad path. Still cheap to refuse outright — a
    `path` of `../../.bashrc` or `/etc/passwd` has no legitimate reason to
    exist in a release's file list, and stage_update() joins this value onto a
    directory it then writes into."""
    if (not isinstance(path, str) or not path
           or path.startswith("/") or path.startswith("\\")
           or ":" in path  # Windows drive letters (C:\...)
           or any(part in ("..", "") for part in path.replace("\\", "/").split("/"))):
        raise ManifestError("malformed", f"Update manifest contains an "
                                          f"unsafe file path: {path!r}.")
