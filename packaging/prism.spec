# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Prism desktop app — one spec, all three OSes.

Run it through packaging/build.py rather than directly; that script generates
the icons first and packs the result into the archive people download.

Deliberately a onedir build, not onefile. undetected-chromedriver downloads and
PATCHES a chromedriver binary at runtime, and a onefile bundle re-extracts to a
fresh temp directory on every launch — so every run would re-download the
driver, and the patched copy would be thrown away each time. onedir also starts
noticeably faster and lets antivirus scan the payload once instead of on every
launch.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
GUI_DIR = os.path.dirname(SPEC_DIR)
sys.path.insert(0, GUI_DIR)
import app_meta   # noqa: E402

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# ── the build will not ship without a production signing key ────────────────
# licensing/keys.py trusts its DEVELOPMENT keys only when running from source,
# so a frozen build with an empty PRODUCTION map trusts nothing and rejects
# every customer's licence with "issued for a different version of Prism".
#
# Nothing else catches this: the app starts, the window opens, and
# licensing.selftest() still passes, because it verifies the committed test
# vector against that vector's own key rather than against PRODUCTION. The
# first sign would be every client of the release failing to activate at once.
import licensing.keys as _keys   # noqa: E402

if not _keys.PRODUCTION and not os.environ.get("PRISM_UNLICENSED_TEST_BUILD"):
    raise SystemExit(
        "\n  Refusing to build: licensing/keys.py has no PRODUCTION key.\n"
        "  A packaged Prism would reject every licence you issue.\n\n"
        "  Generate the production keypair on the licence server, then paste\n"
        "  its PUBLIC half into PRODUCTION in licensing/keys.py:\n\n"
        '      PRODUCTION = {"k1": "<64 hex chars>"}\n\n'
        "  See license_server/.env.example for the generator command.\n"
        "  (Building packaging smoke tests only? "
        "PRISM_UNLICENSED_TEST_BUILD=1 — the result cannot activate.)\n")

ENGINE_DIR = os.path.join(GUI_DIR, "prism_terminal")

icon = os.path.join(SPEC_DIR, "icons",
                    "prism.ico" if IS_WIN else "prism.icns" if IS_MAC else "prism.png")

# ── which licence server this build talks to ─────────────────────────────────
# A frozen app ignores PRISM_LICENSE_SERVER at runtime (that override would be
# a bypass), so the URL has to be decided here. PRISM_SERVER_URL lets a test
# build point at a laptop or a LAN address without editing source; unset, the
# DEFAULT_SERVER already in licensing/client.py ships.
_server_url = os.environ.get("PRISM_SERVER_URL", "").strip()
if _server_url:
    _client_py = os.path.join(GUI_DIR, "licensing", "client.py")
    with open(_client_py, "r", encoding="utf-8") as _f:
        _src = _f.read()
    import re as _re
    _patched = _re.sub(r'^DEFAULT_SERVER = ".*"$',
                       f'DEFAULT_SERVER = "{_server_url}"', _src,
                       count=1, flags=_re.M)
    if _patched == _src:
        raise SystemExit("PRISM_SERVER_URL set but DEFAULT_SERVER not found "
                         "in licensing/client.py — has it been renamed?")
    # Written back so the analyser bundles the patched module. build.py restores
    # the original afterwards; if a build is interrupted, `git diff` shows it.
    with open(_client_py, "w", encoding="utf-8") as _f:
        _f.write(_patched)
    print(f"[prism] licence server baked in: {_server_url}")

# ── what ships alongside the code ────────────────────────────────────────────
# paths.resource() resolves these at runtime; the destination names must match
# the layout the sources expect ("assets/…", "prism_terminal/…").
datas = [
    (os.path.join(GUI_DIR, "assets"), "assets"),
    (os.path.join(GUI_DIR, "style.qss"), "."),
    # The committed licence-token test vector. main.py's --selftest verifies a
    # real signature against it, which is the only check that proves the
    # crypto survived freezing on this platform — an import succeeding says
    # nothing about whether the native backend actually works.
    (os.path.join(GUI_DIR, "licensing", "testdata", "vector.json"),
     os.path.join("licensing", "testdata")),
]

# devtools/ is deliberately absent: it holds the token-signing logic and a
# private key. Nothing in it may ever reach a build.

# The engine also ships as files, because core_bridge puts this directory on
# sys.path at runtime and router._tool_notes() reads pros_cons.txt/tool_notes.md
# off disk. (The code itself is additionally analysed — see pathex below — so
# that the stdlib modules core/*.py import actually get bundled. Shipping the
# sources without analysing them is how a build ends up missing smtplib.)
for root, dirs, files in os.walk(ENGINE_DIR):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".venv")]
    for name in files:
        if name.endswith((".pyc", ".pyo")):
            continue
        src = os.path.join(root, name)
        rel = os.path.relpath(root, GUI_DIR)
        datas.append((src, rel))

# When frozen, core.router is imported from the archive, so its __file__ points
# at <bundle>/core/router.py and its notes lookup walks up to the bundle root —
# not to prism_terminal/. Put a copy there too, or the tool notes silently stop
# reaching the router prompt.
for note in ("pros_cons.txt", "tool_notes.md", "tool_notes.txt"):
    src = os.path.join(ENGINE_DIR, note)
    if os.path.exists(src):
        datas.append((src, "."))

# undetected_chromedriver ships non-Python files and imports its patcher
# dynamically; without this the frozen app raises at driver setup, which is the
# one moment the user is furthest from a terminal that would show the error.
datas += collect_data_files("undetected_chromedriver")

hiddenimports = [
    # Reached only through core_bridge's runtime sys.path insert, so static
    # analysis never sees them.
    "core", "core.config", "core.agents", "core.router", "core.pathfinder",
    "core.files", "core.voice", "core.mailer", "core.automation",
    "core.onboarding", "core.remote", "core.ui",
    # Optional-at-runtime, imported inside functions.
    "pypdf", "docx", "pyaudio",
    # undetected_chromedriver's patcher imports distutils, gone from the 3.12
    # stdlib — rthook_distutils.py aliases setuptools' copy, which has to be
    # bundled for that to be possible.
    "setuptools", "setuptools._distutils", "setuptools._distutils.version",
    # Qt bits pulled in by name (QtSvg backs every icon we draw).
    "PySide6.QtSvg", "PySide6.QtNetwork",
    # Licence verification. cryptography loads its Rust/OpenSSL backend
    # dynamically, so the leaf modules have to be named — a build where these
    # are missing starts fine and then rejects every customer's licence.
    "cryptography", "cryptography.hazmat.backends.openssl",
    "cryptography.hazmat.bindings._rust",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
]
hiddenimports += collect_submodules("undetected_chromedriver")
hiddenimports += collect_submodules("selenium")

# Qt is modular and PyInstaller takes the lot by default; these are the big
# ones Prism never touches. Dropping them roughly halves the download.
excludes = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "shiboken6.support",
    # Scientific/GUI stacks that sneak in via transitive imports.
    #
    # numpy and PIL are NOT in this list, and must not be added back:
    #   · ezdxf declares numpy as a hard dependency — excluding it made the
    #     BOQ add-on fail in every packaged build with "No module named
    #     'numpy'", while working perfectly from source.
    #   · Prism Reel draws its frames with Pillow (PIL).
    # Both add-ons are things we sell. They cost ~50MB in the bundle; a
    # flagship feature that only works on a developer's machine costs more.
    "tkinter", "matplotlib", "scipy", "pandas", "IPython",
    "pytest", "notebook",
]

# NOTE: there is no bytecode encryption here, and there cannot be — PyInstaller
# removed the `cipher`/`--key` option in 6.0, and this project requires >=6.3.
# The `block_cipher = None` / `cipher=block_cipher` arguments that used to sit
# here were inert and have been deleted rather than left implying protection
# that does not exist. What actually keeps the product closed is that the
# engine payload is not in this bundle at all — see docs/licensing/.

a = Analysis(
    [os.path.join(GUI_DIR, "main.py")],
    # ENGINE_DIR on the search path is what lets the `core.*` hiddenimports
    # below resolve — and analysing them is what drags in the stdlib they use
    # (smtplib, ssl, csv, email, …), none of which the GUI itself imports.
    pathex=[GUI_DIR, ENGINE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        os.path.join(SPEC_DIR, "rthook_distutils.py"),
        os.path.join(SPEC_DIR, "rthook_ssl_certs.py"),
    ],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_meta.NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed Qt DLLs are a reliable false-positive magnet
    console=False,      # a GUI app must not flash a terminal on Windows
    disable_windowed_traceback=False,
    argv_emulation=IS_MAC,   # lets Finder "Open with" pass file arguments
    target_arch=None,        # CI builds one arch per runner
    codesign_identity=None,  # unsigned: see BUILD.md for what users must do
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_meta.NAME,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{app_meta.NAME}.app",
        icon=icon,
        bundle_identifier=app_meta.BUNDLE_ID,
        version=app_meta.VERSION,
        info_plist={
            "CFBundleShortVersionString": app_meta.VERSION,
            "CFBundleVersion": app_meta.VERSION,
            "NSHighResolutionCapable": True,
            # Prism records the user through PyAudio for voice input; without a
            # usage string macOS kills the app the instant it opens the mic.
            "NSMicrophoneUsageDescription":
                "Prism listens for the wake word and transcribes what you say "
                "into a task.",
            "NSAppleEventsUsageDescription":
                "Prism opens Chrome to drive the AI tools you are signed in to.",
            "LSMinimumSystemVersion": "11.0",
        },
    )
