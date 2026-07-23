#!/usr/bin/env python3
"""
Prism GUI — desktop entry point
────────────────────────────────
    python3 main.py

A native desktop app (PySide6/Qt) — no browser, no server, nothing "online"
about it. It is a pure UI layer: every routing decision and every browser
automation call is delegated straight into prism_terminal/core/*.py via
core_bridge.py, so the CLI and GUI share one engine and one ~/.prism config.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

import app_meta
import paths
import theme
from main_window import MainWindow
from widgets import icons


def _selftest(app) -> int:
    """Prove a packaged build is whole: every bundled resource present, the
    engine importable, the window constructible. Run by packaging/smoke_test.py
    against the real executable, because a build that merely finishes can still
    die on launch — and a windowed app has no console to say why.

    Deliberately checks the things freezing breaks, not the things Python
    already guarantees."""
    import core_bridge as CB
    import wakeword

    # The checks below print ✓/✗ to whatever stdout the harness attached. On
    # Windows that pipe defaults to cp1252, which can't encode them — and a
    # windowed (console=False) build may have no stdout at all, hence the guard.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Selenium + undetected_chromedriver are the product's whole point, and
    # they are also the most fragile thing to freeze (dynamic imports, a
    # patcher that still wants the removed distutils). A build where this
    # doesn't import is broken even though every window renders, so it fails
    # the check rather than printing a warning nobody reads.
    automation_ok, automation_err = CB.automation_available()

    # A real HTTPS handshake, not just an import — the SSL cert bug that
    # reached a client's Mac (urlopen: CERTIFICATE_VERIFY_FAILED) had every
    # module import cleanly; ssl.create_default_context() only fails once it
    # actually tries to verify a live server, and that only happens on macOS,
    # where the frozen ssl module has no route to the system trust store
    # unless rthook_ssl_certs.py has patched it in. Catches a regression here
    # instead of on a user's machine a second time.
    try:
        import urllib.request
        with urllib.request.urlopen("https://www.google.com", timeout=10) as r:
            tls_ok, tls_err = r.status == 200, ""
    except Exception as e:
        tls_ok, tls_err = False, str(e)

    checks = [
        (f"HTTPS trust store{'' if tls_ok else f' — {tls_err}'}", tls_ok),
        ("stylesheet", os.path.exists(paths.resource("style.qss"))),
        ("fonts", os.path.isdir(paths.resource("assets", "fonts"))
                  and theme.FONT_BODY in QFontDatabase.families()),
        ("logo", not icons.logo_pixmap(64).isNull()),
        # A multi-part icon that only paints SOME of its strokes still passes
        # isNull(), and even a bare painted-pixel-count check isn't enough —
        # a second macOS bug (QSvgRenderer.render(painter) with no target
        # rect mis-mapping under devicePixelRatio != 1) painted only the
        # icon's FIRST subpath, scaled and cropped, which alone already
        # cleared a ">= 40 total pixels" bar. "sliders" has one row at y=8
        # and another at y=16 in its 24x24 viewBox, so require paint in BOTH
        # halves — a partial render that drops either row now fails loudly.
        ("line icons (sliders, top+bottom rows)", (lambda img: (
            any(img.pixelColor(x, y).alpha() > 10
                for y in range(img.height() // 2) for x in range(img.width()))
            and any(img.pixelColor(x, y).alpha() > 10
                    for y in range(img.height() // 2, img.height()) for x in range(img.width()))
         ))(icons.pixmap("sliders", 24, "#5980a6").toImage())),
        ("engine", hasattr(CB.agents, "AGENT_REGISTRY")
                   and len(CB.agents.AGENT_REGISTRY) > 0),
        ("engine notes", bool(CB.router._tool_notes())),
        ("config path", CB.config.CONFIG_PATH.endswith("config.json")),
        ("mailer", callable(CB.mailer.send_bulk)),
        (f"browser automation{'' if automation_ok else f' — {automation_err}'}",
         automation_ok),
    ]
    win = MainWindow()
    win.show()
    checks.append(("main window", win.isVisible()))
    checks.append(("sidebar", win.sidebar.width() > 0))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
    ok, why = wakeword.available()
    print(f"  {'✓' if ok else '!'} voice input{'' if ok else f' — {why}'}"
          "  (optional — needs PortAudio on the machine)")
    print(f"{app.applicationName()} {app.applicationVersion()} · "
          f"frozen={paths.is_frozen()} · {sys.platform} · py"
          f"{sys.version_info.major}.{sys.version_info.minor}")
    return 1 if failed else 0


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(app_meta.NAME)
    app.setApplicationDisplayName(app_meta.NAME)
    app.setApplicationVersion(app_meta.VERSION)
    app.setOrganizationName(app_meta.PUBLISHER)
    # Wayland/X11 read this to match the window to its .desktop entry — without
    # it the taskbar shows a generic icon no matter what setWindowIcon says.
    app.setDesktopFileName(app_meta.BUNDLE_ID)
    # Register Barlow before any widget is constructed — a QFont resolved
    # against a missing family stays resolved, so loading late leaves the
    # first-built widgets on the fallback sans.
    theme.load_fonts()
    # Titlebar, taskbar, alt-tab and every dialog inherit this.
    app.setWindowIcon(icons.logo_icon())

    style_path = paths.resource("style.qss")
    if os.path.exists(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            qss = f.read()
        # QSS url(…) paths must be absolute and posix-separated: a Windows
        # backslash inside url() is read as an escape and the icon vanishes.
        assets = paths.resource("assets").replace(os.sep, "/")
        app.setStyleSheet(qss.replace("%ASSETS%", assets))

    if os.environ.get("PRISM_SELFTEST"):
        sys.exit(_selftest(app))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
