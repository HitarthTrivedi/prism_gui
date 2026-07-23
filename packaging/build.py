#!/usr/bin/env python3
"""Build the Prism desktop app for whichever OS you run this on.

    python packaging/build.py              # build + archive
    python packaging/build.py --no-archive # just dist/Prism*, for quick testing
    python packaging/build.py --clean      # wipe build/ and dist/ first

Produces, in dist/:
    Linux    Prism-<version>-linux-<arch>.tar.gz   (+ Prism-<version>.AppImage
                                                     when appimagetool is on PATH)
    Windows  Prism-<version>-windows-<arch>.zip
    macOS    Prism-<version>-macos-<arch>.dmg      (falls back to .zip without hdiutil)

PyInstaller cannot cross-compile: whatever OS you run this on is the OS you
get. All three are built together by .github/workflows/build.yml, which runs
this same script on three runners.
"""
from __future__ import annotations
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

# Windows consoles default to cp1252, which cannot encode the ✓/✗ these
# scripts print — the Windows CI build once FAILED after building successfully,
# purely on printing "✓ built". Force UTF-8, degrade characters rather than die.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
DIST = os.path.join(GUI, "dist")
BUILD = os.path.join(GUI, "build")
sys.path.insert(0, GUI)
import app_meta   # noqa: E402

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
OS_TAG = "windows" if IS_WIN else "macos" if IS_MAC else "linux"
ARCH = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64",
        "arm64": "arm64"}.get(platform.machine(), platform.machine())
STEM = f"{app_meta.NAME}-{app_meta.VERSION}-{OS_TAG}-{ARCH}"


def run(cmd: list[str], **kw):
    print("»", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def preflight():
    """Fail with something actionable instead of a PyInstaller stack trace."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is missing — pip install -r packaging/requirements-build.txt")
    try:
        import PySide6  # noqa: F401
    except ImportError:
        sys.exit("PySide6 is missing — pip install -r requirements.txt")
    if sys.version_info >= (3, 13):
        print("!  Python 3.13+ dropped the stdlib audioop module: voice input "
              "will be disabled in this build unless audioop-lts is installed.")
    engine = os.path.join(GUI, "prism_terminal", "core")
    if not os.path.isdir(engine):
        sys.exit("prism_terminal/core is missing — run:\n"
                 "    git submodule update --init --recursive")


def build():
    run([sys.executable, os.path.join(HERE, "make_icons.py")])
    run([sys.executable, "-m", "PyInstaller", "--noconfirm",
         "--distpath", DIST, "--workpath", BUILD,
         os.path.join(HERE, "prism.spec")])


# ── per-OS packaging ─────────────────────────────────────────────────────────

def _desktop_entry() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={app_meta.NAME}\n"
        f"Comment={app_meta.DESCRIPTION}\n"
        f"Exec={app_meta.NAME}\n"
        f"Icon={app_meta.BUNDLE_ID}\n"
        "Terminal=false\n"
        # One main category only — two makes the app appear twice in the menu
        # (desktop-file-validate warns about exactly this).
        "Categories=Office;\n"
        f"X-AppImage-Version={app_meta.VERSION}\n"
    )


def archive_linux(app_dir: str) -> list[str]:
    made = []
    # A .desktop file and icon travel with the folder so `install.sh` can wire
    # it into the launcher menu.
    shutil.copy2(os.path.join(HERE, "icons", "prism.png"),
                 os.path.join(app_dir, f"{app_meta.BUNDLE_ID}.png"))
    with open(os.path.join(app_dir, f"{app_meta.BUNDLE_ID}.desktop"), "w") as f:
        f.write(_desktop_entry())
    shutil.copy2(os.path.join(HERE, "install.sh"), os.path.join(app_dir, "install.sh"))
    os.chmod(os.path.join(app_dir, "install.sh"), 0o755)

    tar_path = os.path.join(DIST, f"{STEM}.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(app_dir, arcname=app_meta.NAME)
    made.append(tar_path)

    appimagetool = shutil.which("appimagetool") or shutil.which("appimagetool-x86_64.AppImage")
    if appimagetool:
        made.append(build_appimage(app_dir, appimagetool))
    else:
        print("!  appimagetool not on PATH — skipping the AppImage "
              "(the .tar.gz is complete on its own).")
    return made


def build_appimage(app_dir: str, appimagetool: str) -> str:
    """AppDir layout: AppRun + .desktop + icon at the root, payload in usr/."""
    appdir = os.path.join(BUILD, f"{app_meta.NAME}.AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    os.makedirs(os.path.join(appdir, "usr"), exist_ok=True)
    shutil.copytree(app_dir, os.path.join(appdir, "usr", "bin"))

    with open(os.path.join(appdir, f"{app_meta.BUNDLE_ID}.desktop"), "w") as f:
        f.write(_desktop_entry())
    shutil.copy2(os.path.join(HERE, "icons", "prism.png"),
                 os.path.join(appdir, f"{app_meta.BUNDLE_ID}.png"))
    apprun = os.path.join(appdir, "AppRun")
    with open(apprun, "w") as f:
        f.write('#!/bin/sh\n'
                'HERE="$(dirname "$(readlink -f "$0")")"\n'
                f'exec "$HERE/usr/bin/{app_meta.NAME}" "$@"\n')
    os.chmod(apprun, 0o755)

    out = os.path.join(DIST, f"{app_meta.NAME}-{app_meta.VERSION}-{ARCH}.AppImage")
    env = dict(os.environ, ARCH=platform.machine())
    # --appimage-extract-and-run: CI containers have no FUSE.
    run([appimagetool, "--appimage-extract-and-run", appdir, out], env=env)
    return out


def archive_windows(app_dir: str) -> list[str]:
    zip_path = os.path.join(DIST, f"{STEM}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(app_dir):
            for name in files:
                src = os.path.join(root, name)
                z.write(src, os.path.join(
                    app_meta.NAME, os.path.relpath(src, app_dir)))
    return [zip_path]


def archive_macos(app_bundle: str) -> list[str]:
    if not shutil.which("hdiutil"):
        zip_path = os.path.join(DIST, f"{STEM}.zip")
        run(["ditto", "-c", "-k", "--keepParent", app_bundle, zip_path])
        return [zip_path]
    staging = os.path.join(BUILD, "dmg")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    run(["cp", "-R", app_bundle, staging])
    # The Applications symlink is what makes "drag the icon onto the folder"
    # work — without it people run the app from inside the mounted image.
    os.symlink("/Applications", os.path.join(staging, "Applications"))
    dmg = os.path.join(DIST, f"{STEM}.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    run(["hdiutil", "create", "-volname", app_meta.NAME, "-srcfolder", staging,
         "-ov", "-format", "UDZO", dmg])
    return [dmg]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="wipe build/ and dist/ first")
    ap.add_argument("--no-archive", action="store_true", help="skip the archive step")
    args = ap.parse_args()

    preflight()
    if args.clean:
        for d in (BUILD, DIST):
            shutil.rmtree(d, ignore_errors=True)
    build()

    app_dir = os.path.join(DIST, app_meta.NAME)
    bundle = os.path.join(DIST, f"{app_meta.NAME}.app")
    target = bundle if (IS_MAC and os.path.isdir(bundle)) else app_dir
    if not os.path.exists(target):
        sys.exit(f"build produced nothing at {target}")
    print(f"\n✓ built {target}")

    if args.no_archive:
        return
    if IS_WIN:
        made = archive_windows(app_dir)
    elif IS_MAC:
        made = archive_macos(target)
    else:
        made = archive_linux(app_dir)
    print("\n✓ artifacts:")
    for path in made:
        print(f"    {path}  ({os.path.getsize(path) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
