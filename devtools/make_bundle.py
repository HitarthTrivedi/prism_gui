#!/usr/bin/env python3
"""Zip Prism up for a Mac that has nothing on it — source plus one launcher.

    python3 devtools/make_bundle.py                 # dist/Prism-<version>-mac-source.zip
    python3 devtools/make_bundle.py --with-python   # + the standalone Pythons, so
                                                    #   the first run needs no download
                                                    #   for the interpreter (~90 MB more)
    python3 devtools/make_bundle.py -o ~/Desktop    # put the zip somewhere else

What goes in: every file git tracks in prism_gui and in the prism_terminal
submodule (so nothing from build/, dist/, .venv/, videos/ or somebody's
uncommitted desk clutter travels), minus the folders a customer never runs
(tests/, devtools/, docs/, examples/, videos/, .github/), plus
`packaging/Install and Run Prism.command` and `packaging/README-INSTALL.txt`
at the top of the folder. The .command keeps its executable bit; a zip made
by Finder would too, but this one is made the same way every time.

Interim hand-off until the Developer ID certificate lets the DMG be signed
and notarised (docs/handover/Shipping_the_app_as_a_macOS_DMG.docx). The
launcher does the install on the other Mac: see its own header.
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
import urllib.request
import zipfile

# A Windows console is cp1252 and cannot encode the ✓ below -- see
# packaging/build.py for the CI failure that found this. Degrade, don't die.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Pinned to the same release the .command downloads, so a bundled tarball
# and a fetched one are the same bytes.
PY_VERSION = "3.12.14"
PY_RELEASE = "20260901"
_PY_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
           "{rel}/cpython-{ver}+{rel}-{arch}-apple-darwin-install_only.tar.gz")

SKIP_TOP = ("tests", "devtools", "docs", "examples", "videos", ".github",
            "build", "dist", "license_server")
SKIP_NAMES = (".gitignore", ".gitmodules", ".gitattributes")


def tracked(repo: str) -> list[str]:
    out = subprocess.run(["git", "-C", repo, "ls-files", "-z"], check=True,
                         capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def wanted(rel: str) -> bool:
    top = rel.split("/", 1)[0]
    if top in SKIP_TOP or os.path.basename(rel) in SKIP_NAMES:
        return False
    return True


def version() -> str:
    import app_meta
    return app_meta.VERSION


def add(zf: zipfile.ZipFile, src: str, arc: str) -> None:
    info = zipfile.ZipInfo.from_file(src, arc)
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = os.stat(src).st_mode
    if arc.endswith(".command") or arc.endswith(".sh"):
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    info.external_attr = (mode & 0xFFFF) << 16
    with open(src, "rb") as f:
        zf.writestr(info, f.read())


def fetch_pythons(into: str) -> list[str]:
    os.makedirs(into, exist_ok=True)
    paths = []
    for arch in ("aarch64", "x86_64"):
        url = _PY_URL.format(rel=PY_RELEASE, ver=PY_VERSION, arch=arch)
        dest = os.path.join(into, os.path.basename(url))
        if not os.path.exists(dest):
            print(f"  downloading {os.path.basename(url)} …")
            urllib.request.urlretrieve(url, dest)
        paths.append(dest)
    return paths


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--out-dir", default=os.path.join(ROOT, "dist"))
    p.add_argument("--with-python", action="store_true",
                   help="bundle the standalone CPython tarballs for both Mac types")
    p.add_argument("--name", default="Prism", help="top folder name inside the zip")
    args = p.parse_args(argv)

    ver = version()
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"Prism-{ver}-mac-source.zip")
    top = args.name

    files: list[tuple[str, str]] = []
    for rel in tracked(ROOT):
        if rel == "prism_terminal" or not wanted(rel):
            continue
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            files.append((src, f"{top}/{rel}"))
    engine = os.path.join(ROOT, "prism_terminal")
    for rel in tracked(engine):
        if rel.split("/", 1)[0] in ("demo",) or os.path.basename(rel) in SKIP_NAMES:
            continue
        src = os.path.join(engine, rel)
        if os.path.isfile(src):
            files.append((src, f"{top}/prism_terminal/{rel}"))
    files.append((os.path.join(ROOT, "packaging", "Install and Run Prism.command"),
                  f"{top}/Install and Run Prism.command"))
    files.append((os.path.join(ROOT, "packaging", "README-INSTALL.txt"),
                  f"{top}/READ ME FIRST.txt"))
    if args.with_python:
        for path in fetch_pythons(os.path.join(args.out_dir, "python-standalone")):
            files.append((path, f"{top}/runtime/downloads/{os.path.basename(path)}"))

    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in files:
            add(zf, src, arc)
    size = os.path.getsize(out) / 1e6
    print(f"✓ {out}  ({len(files)} files, {size:.1f} MB)")
    print(f"  hand over the zip; the other Mac unzips it and double-clicks "
          f"'Install and Run Prism.command'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
