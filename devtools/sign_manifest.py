#!/usr/bin/env python3
"""Sign an update manifest — release-machine tool, not CI, not a build step.

    python3 devtools/sign_manifest.py dist/manifest.json -o dist/manifest.signed \
        --key-hex "$UPDATE_SIGNING_KEY_HEX"

Deliberately a human running this by hand from a private key that lives
nowhere near CI or the licence server — see licensing/keys.py's
UPDATE_PRODUCTION comment for the whole reasoning
(update-research-inapp-download.md §5.2 requirement #2). The key never
appears as a literal in this file or anywhere else in the repo; it must be
supplied at run time via --key-hex or the UPDATE_SIGNING_KEY_HEX environment
variable, on whatever offline machine holds it.

Refuses to sign a version that is not strictly newer than the last version
this tool has signed on this machine (tracked in
devtools/.last_signed_update_version, gitignored) — the same "no accidental
downgrade" property update_manifest.verify()'s expiry/monotonic checks give
the CLIENT side, mirrored here so a release engineer can't accidentally
re-sign an old manifest and publish it over a newer one.

NOT SHIPPED. devtools/ is absent from packaging/prism.spec (see build.py's
own comment: "devtools/ is NOT here, and must never be").
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manifest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LAST_SIGNED_PATH = os.path.join(HERE, ".last_signed_update_version")


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _last_signed_version() -> str:
    try:
        with open(LAST_SIGNED_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _record_signed_version(version: str) -> None:
    with open(LAST_SIGNED_PATH, "w", encoding="utf-8") as f:
        f.write(version)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("manifest_path", help="Unsigned manifest JSON from packaging/manifest.py")
    p.add_argument("-o", "--output", required=True, help="Where to write the signed PRSMUv1 token")
    p.add_argument("--key-hex", default=os.environ.get("UPDATE_SIGNING_KEY_HEX", ""),
                   help="Ed25519 private key, hex. Prefer the env var over the flag "
                        "so it never lands in shell history.")
    p.add_argument("--kid", default="u1", help="Key id this signature claims (default: u1, "
                                               "the production update key's id)")
    p.add_argument("--validity-days", type=int, default=update_manifest.DEFAULT_VALIDITY_DAYS)
    p.add_argument("--allow-downgrade", action="store_true",
                   help="Bypass the monotonic-version check. For test fixtures only — "
                        "never pass this when signing a real release.")
    args = p.parse_args(argv)

    if not args.key_hex:
        p.error("no signing key: pass --key-hex or set UPDATE_SIGNING_KEY_HEX")

    with open(args.manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    version = manifest.get("version", "")
    if not version:
        p.error("manifest has no 'version' field")

    last = _last_signed_version()
    if last and not args.allow_downgrade and _version_tuple(version) <= _version_tuple(last):
        p.error(f"refusing to sign {version!r}: not newer than the last version this "
                f"machine signed ({last!r}). Pass --allow-downgrade only for test "
                f"fixtures, never for a real release.")

    token = update_manifest.sign(manifest, args.key_hex, kid=args.kid,
                                 validity_days=args.validity_days)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(token)

    if not args.allow_downgrade:
        _record_signed_version(version)

    print(f"Signed manifest for {version} (kid={args.kid}) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
