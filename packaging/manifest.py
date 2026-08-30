"""Build an (unsigned) update manifest for a built Prism directory.

    python3 packaging/manifest.py dist/Prism 1.3.1 -o dist/manifest.json
    python3 packaging/manifest.py dist/Prism 1.3.1 -o dist/manifest.json \
        --archive dist/Prism-1.3.1-linux-x64.tar.gz

Run by file path, like packaging/build.py — packaging/ has no __init__.py
(see build.py's own invocation convention), and deliberately so: `packaging`
is also the name of a real PyPI library this project depends on
(requirements.txt), and `python3 -m packaging.manifest` resolves to THAT
package, not this file, the moment it's installed. `python3 packaging/
manifest.py` sidesteps the collision entirely by never asking Python to
resolve `packaging` as an import at all.

Run this AFTER packaging/build.py has produced dist/<platform build> and
AFTER packaging/smoke_test.py has passed against it — a manifest is a
description of a build the team is willing to ship, not a build step in its
own right. The output is unsigned; devtools/sign_manifest.py signs it in a
separate step, deliberately on a different machine/key (see
licensing/keys.py's UPDATE_PRODUCTION comment for why the two are split).

All the actual hashing/walking logic lives in update_manifest.py (imported by
updater.py at runtime too, to hash the LOCAL installed tree the same way this
script hashes the build) — this file is just the build-time CLI over it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root_dir", help="Built app directory, e.g. dist/Prism")
    p.add_argument("version", help="Release version, e.g. 1.3.1")
    p.add_argument("-o", "--output", required=True, help="Where to write the JSON manifest")
    p.add_argument("--archive", help="Optional distributable archive (tar.gz/zip/dmg) "
                                     "to record a whole-download fallback entry for")
    args = p.parse_args(argv)

    if not os.path.isdir(args.root_dir):
        p.error(f"{args.root_dir!r} is not a directory")

    manifest = update_manifest.build(args.root_dir, args.version)
    if args.archive:
        if not os.path.isfile(args.archive):
            p.error(f"{args.archive!r} is not a file")
        manifest = update_manifest.add_archive(manifest, args.archive)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    print(f"Wrote manifest for {args.version}: {len(manifest['files'])} files"
          f"{', plus archive entry' if args.archive else ''} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
