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

ENGINE_DIR = os.path.join(GUI_DIR, "prism_terminal")

icon = os.path.join(SPEC_DIR, "icons",
                    "prism.ico" if IS_WIN else "prism.icns" if IS_MAC else "prism.png")

# ── what ships alongside the code ────────────────────────────────────────────
# paths.resource() resolves these at runtime; the destination names must match
# the layout the sources expect ("assets/…", "prism_terminal/…").
datas = [
    (os.path.join(GUI_DIR, "assets"), "assets"),
    (os.path.join(GUI_DIR, "style.qss"), "."),
]

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
    "tkinter", "matplotlib", "numpy", "scipy", "pandas", "PIL", "IPython",
    "pytest", "notebook",
]

block_cipher = None

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
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
