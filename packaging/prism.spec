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
    # subn, not sub: what matters is whether the PATTERN MATCHED, not whether
    # the text changed. Those come apart in one ordinary case — the URL in
    # source already being the URL we are baking in — and the old `_patched ==
    # _src` test read that as "DEFAULT_SERVER not found" and killed the build
    # over a line sitting right there in the file.
    #
    # It cost two rounds of chasing, because it is invisible locally: with
    # PRISM_SERVER_URL unset this whole branch is skipped, so every local build
    # passed while CI failed on all three platforms.
    _patched, _hits = _re.subn(r'^DEFAULT_SERVER = ".*"$',
                               f'DEFAULT_SERVER = "{_server_url}"', _src,
                               count=1, flags=_re.M)
    if not _hits:
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
    # Read in-app via dialogs/legal_dialog.py (Settings → Help & more →
    # Legal) so a customer never needs a network connection just to read
    # what they agreed to.
    (os.path.join(GUI_DIR, "TERMS_OF_USE.md"), "."),
    (os.path.join(GUI_DIR, "PRIVACY_POLICY.md"), "."),
    # The translation catalogue and every language pack. i18n.load() reads
    # these through paths.resource(), and a build that ships without them
    # doesn't fail — it just quietly renders in English no matter what the
    # customer picked, which is a far harder bug to be told about.
    (os.path.join(GUI_DIR, "lang"), "lang"),
    # The Google OAuth client, if this build has one. Optional on purpose:
    # gdrive.configured() reports "not set up" rather than failing, so a build
    # made without it still ships — it just has no Drive picker.
    *([(os.path.join(GUI_DIR, "integrations", "google_client.json"),
        "integrations")]
      if os.path.exists(os.path.join(GUI_DIR, "integrations",
                                     "google_client.json")) else []),
    # The committed licence-token test vector. main.py's --selftest verifies a
    # real signature against it, which is the only check that proves the
    # crypto survived freezing on this platform — an import succeeding says
    # nothing about whether the native backend actually works.
    (os.path.join(GUI_DIR, "licensing", "testdata", "vector.json"),
     os.path.join("licensing", "testdata")),
]

# devtools/ is deliberately absent: it holds the token-signing logic and a
# private key. Nothing in it may ever reach a build.

# The engine's DATA ships as files. Its CODE comes from the archive — pathex
# below plus the enumerated core.* hiddenimports.
#
# This used to ship the sources too, and that was the whole product in editable
# form sitting next to the binary: 19 .py files at mode 0664, including
# automation.py, boq.py and a prism.py with a complete licence-free main().
# Two bypasses came free with it. core_bridge put this directory AHEAD of the
# archive on sys.path, so editing a file here changed what the "compiled" app
# did — verified, not theorised. And run_prism.command shipped at mode 0755:
# double-click it and a venv builds itself, pip installs requirements.txt and
# runs the engine with no licence check at all, needing no Python knowledge.
#
# The launchers and requirements.txt exist to start the CLI from a source
# checkout and have no purpose in a bundle. requirements.txt is worth removing
# on its own account: it is unpinned, so that launcher also pulled whatever
# PyPI served that day into the customer's install folder.
_ENGINE_SKIP = {"run_prism.bat", "run_prism.command", "requirements.txt",
                # A submodule's .git is a one-line gitlink file, so the dirs
                # filter below never catches it. Harmless, and it has no
                # business in a customer's install folder.
                ".git", ".gitignore", ".gitmodules"}
# demo/ is sample CSVs for a walkthrough that is not part of the product, and
# nothing in the app reads it.
_ENGINE_SKIP_DIRS = ("__pycache__", ".git", ".venv", "demo", "tests")
for root, dirs, files in os.walk(ENGINE_DIR):
    dirs[:] = [d for d in dirs if d not in _ENGINE_SKIP_DIRS]
    for name in files:
        if name.endswith((".py", ".pyc", ".pyo")) or name in _ENGINE_SKIP:
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

# The FFmpeg executable, which lives inside the imageio_ffmpeg package as a
# data file rather than as Python. include_py_files is off, so this picks up
# the binary and nothing else.
#
# A build without it produces an app whose Reel button fails on a customer's
# machine with an install guide — which is exactly what happened to the first
# Windows user. There is a runtime download as a fallback (core/ffmpeg.py),
# but a customer should never meet it.
try:
    import imageio_ffmpeg  # noqa: F401
    datas += collect_data_files("imageio_ffmpeg")
    print("[prism] FFmpeg bundled")
except ImportError:
    print("[prism] WARNING: imageio-ffmpeg is not installed, so this build "
          "ships no FFmpeg. Reel will have to download it on first use.")

def _engine_modules() -> list[str]:
    """Every core.* module, read off disk rather than listed by hand.

    This used to be a hand-maintained list. It named 11 modules; the engine has
    25. The other 14 reached the archive only because PyInstaller also scans
    function-level imports and found core_bridge's lazy `def get_X(): from core
    import X` getters — an accident, not a plan, and one nobody could see.

    That was survivable only while the loose .py files also shipped and
    core_bridge put them ahead of the archive: a module missing from here was
    silently imported from disk instead. Now that the sources do not ship,
    anything missing from this list is an ImportError in front of a customer,
    in a windowed build with no console to print it. So enumerate, never list.
    """
    core = os.path.join(ENGINE_DIR, "core")
    found = ["core"] + [
        "core." + name[:-3] for name in sorted(os.listdir(core))
        if name.endswith(".py") and name != "__init__.py"]
    print(f"[prism] engine modules bundled: {len(found) - 1}")
    return found


hiddenimports = _engine_modules() + [
    # Optional-at-runtime, imported inside functions.
    "pypdf", "docx", "pyaudio",
    # Mail-server discovery: core/inbox.py does a lazy `import dns.resolver`
    # inside mx_host(), which degrades SILENTLY to guessing when absent. That
    # is right on a customer machine and wrong in a build — and it was already
    # happening: dnspython was installed on the build box and PyInstaller still
    # did not bundle it, because a function-level import of a package it has no
    # hook for is invisible. Every shipped copy had MX detection dead, which is
    # precisely the bug the lazy import was added to fix.
    "dns", "dns.resolver", "dns.rdatatype",
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

# The Google Drive libraries are imported lazily inside integrations/gdrive.py,
# so the analyser never sees them. Added only when they are actually installed
# on the build machine: a build without them still ships, with the Drive picker
# reporting itself unavailable rather than crashing.
try:
    import google_auth_oauthlib  # noqa: F401
    import googleapiclient       # noqa: F401
    hiddenimports += collect_submodules("googleapiclient")
    hiddenimports += collect_submodules("google_auth_oauthlib")
    hiddenimports += collect_submodules("google.oauth2")
    datas += collect_data_files("googleapiclient")
    print("[prism] Google Drive support bundled")
except ImportError:
    print("[prism] Google Drive libraries not installed - picker will be "
          "unavailable in this build")
hiddenimports += collect_submodules("undetected_chromedriver")
hiddenimports += collect_submodules("selenium")

# The OS credential store, for the licence key (licensing/secretstore.py).
# Optional in exactly the same way as the Drive libraries above: a build made
# without it falls back to the plaintext file the previous version used, and
# says so in diagnostics rather than failing.
#
# collect_submodules matters here — keyring picks its backend by ENTRY POINT
# at runtime, so nothing static imports keyring.backends.Windows, and a build
# that bundled only `keyring` itself would find no usable backend and silently
# degrade to the file on every machine.
try:
    import keyring  # noqa: F401
    hiddenimports += collect_submodules("keyring")
    print("[prism] OS credential store bundled - licence key will be "
          "kept in the keychain")
except ImportError:
    print("[prism] keyring not installed - the licence key will be stored in "
          "~/.prism/license.json instead")

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
