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
import diagnostics
import i18n
import paths
import theme
import updater
from widgets import icons

# MainWindow is imported inside main(), after i18n.start() has patched Qt.
# Importing it here would be harmless today, but the moment a widget module
# builds a QLabel at import time that label is created untranslated — and the
# failure looks like one stubbornly English string with no obvious cause.


def _force_utf8_streams() -> None:
    """Make stdout/stderr encode UTF-8, whatever console Windows attached.

    The engine narrates its whole run through print() — and one of those lines
    carries an emoji (the 🍪 profile message). On Windows a redirected or
    console-launched process gets a cp1252 stream, and print()ing a character
    cp1252 can't encode raises UnicodeEncodeError — which, uncaught in the
    engine's loop, takes the entire run down. errors="replace" is the belt to
    reconfigure's braces: even a glyph outside the target codec degrades to a
    '?' instead of crashing. A windowed (console=False) build may have no
    stdout at all, so each stream is guarded independently.

    Must run before anything prints — the engine imports happen in main()
    right after this returns.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            pass    # None (windowed build) or a stream that can't reconfigure


def _selftest(app) -> int:
    """Prove a packaged build is whole: every bundled resource present, the
    engine importable, the window constructible. Run by packaging/smoke_test.py
    against the real executable, because a build that merely finishes can still
    die on launch — and a windowed app has no console to say why.

    Deliberately checks the things freezing breaks, not the things Python
    already guarantees."""
    import core_bridge as CB
    import licensing
    import wakeword

    # The checks below print ✓/✗ to whatever stdout the harness attached. On
    # Windows that pipe defaults to cp1252, which can't encode them — main()
    # already forced UTF-8 before us, but PRISM_SELFTEST can be entered on a
    # path that hasn't, so this stays as a cheap idempotent guard.
    _force_utf8_streams()

    # Selenium + undetected_chromedriver are the product's whole point, and
    # they are also the most fragile thing to freeze (dynamic imports, a
    # patcher that still wants the removed distutils). A build where this
    # doesn't import is broken even though every window renders, so it fails
    # the check rather than printing a warning nobody reads.
    automation_ok, automation_err = CB.automation_available()

    # Licence verification is now the first thing that runs on a customer's
    # machine, so a crypto backend that did not survive freezing locks every
    # customer out at once — and looks exactly like a revoked licence. Verify a
    # real signature here, for the same reason the TLS check below does a real
    # handshake rather than importing ssl.
    license_ok, license_err = licensing.selftest()

    # The add-ons we sell. Both once shipped broken: packaging/prism.spec
    # excluded numpy and PIL, so BOQ and Reel failed only in the frozen build
    # and only when a customer clicked them. A dependency that is fine from
    # source and missing once packaged is exactly what this self-test is for.
    boq_ok, boq_err = CB.boq_available()

    # Reel is probed in two halves rather than through CB.reel_available(),
    # because it needs two different kinds of thing and only one of them is a
    # property of the build. Pillow is FROZEN INTO the bundle — that half is
    # the regression above and stays a hard failure.
    #
    # FFmpeg used to be described here as "a system tool the customer
    # installs, never bundled and never bundle-able". That was wrong, and a
    # Windows customer paid for it: Windows ships no FFmpeg and nobody
    # installs one by accident, so the first thing they met on pressing Reel
    # was a codec install guide. It IS bundle-able — imageio-ffmpeg puts it in
    # the wheel — and it is bundled now. Still reported rather than fatal,
    # because a source checkout without the package is a normal thing to be
    # and Prism can fetch it at runtime (core/ffmpeg.py).
    try:
        from PIL import Image, ImageDraw   # noqa: F401
        from core import reel              # noqa: F401
        reel_ok, reel_err = True, ""
    except Exception as e:
        reel_ok, reel_err = False, str(e)
    ffmpeg_ok, ffmpeg_err = CB.reel_available()

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
         ))(icons.pixmap("sliders", 24, theme.ACCENT).toImage())),
        ("engine", hasattr(CB.agents, "AGENT_REGISTRY")
                   and len(CB.agents.AGENT_REGISTRY) > 0),
        ("engine notes", bool(CB.router._tool_notes())),
        ("config path", CB.config.CONFIG_PATH.endswith("config.json")),
        ("mailer", callable(CB.mailer.send_bulk)),
        (f"browser automation{'' if automation_ok else f' — {automation_err}'}",
         automation_ok),
        (f"licence verification{'' if license_ok else f' — {license_err}'}",
         license_ok),
        (f"BOQ add-on (ezdxf){'' if boq_ok else f' — {boq_err}'}", boq_ok),
        (f"Reel add-on (Pillow + renderer)"
         f"{'' if reel_ok else f' — {reel_err}'}", reel_ok),
    ]
    from main_window import MainWindow
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
    # ffmpeg_path()'s message is a multi-line install guide; one line is enough
    # here. split() rather than splitlines()[0] so an exception that stringifies
    # to "" can't turn a diagnostic into an IndexError.
    ffmpeg_why = ffmpeg_err.split("\n")[0]
    # Say WHICH FFmpeg. "✓ Reel encoding" told us nothing about whether the
    # build actually shipped one — which is the single fact this line exists
    # to establish, and the one that was wrong on Windows.
    try:
        from core import ffmpeg as _ffmpeg
        ffmpeg_which = _ffmpeg.describe()
    except Exception:
        ffmpeg_which = "unknown"
    print(f"  {'✓' if ffmpeg_ok else '!'} Reel encoding"
          f"{'' if ffmpeg_ok else f' — {ffmpeg_why}'}"
          f"  ({ffmpeg_which if ffmpeg_ok else 'Prism can download it'})")
    print(f"{app.applicationName()} {app.applicationVersion()} · "
          f"frozen={paths.is_frozen()} · {sys.platform} · py"
          f"{sys.version_info.major}.{sys.version_info.minor}")
    return 1 if failed else 0


def main():
    # First line of the program: guarantee our text streams speak UTF-8 before
    # any engine code can print() the emoji that used to crash a whole run on a
    # cp1252 Windows console. Cheap, side-effect-free, must come before the
    # core_bridge import below.
    _force_utf8_streams()

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

    # Before the first widget exists, and before the licence gate — that
    # dialog is the very first thing a new customer sees, and it is the one
    # screen they cannot skip. Also before the stylesheet, which both of
    # these rewrite.
    # Before diagnostics, because diagnostics.log_dir() is the first thing to
    # create anything under ~/.prism — and whoever creates the root decides its
    # mode. Owner-only, so nothing written underneath (runs, logs, workspace)
    # is readable on a shared workstation regardless of the umask in force.
    paths.ensure_user_dir()

    # Before anything that can fail: from here on, a crash lands in
    # ~/.prism/logs instead of on a stdout a windowed build does not have.
    diagnostics.install()

    # Rollback check for the in-app updater (Phase 1) — as early as possible,
    # before anything else assumes the files on disk are the ones the last
    # launch actually finished starting. Only meaningful for a packaged
    # build (see updater.install_dir()); a source checkout was never swapped
    # by apply_update.py in the first place, so there is nothing to check.
    if paths.is_frozen():
        try:
            import apply_update
            _dir = updater.install_dir()
            if apply_update.check_and_rollback_if_pending(_dir, _dir + ".old"):
                # The version that was just swapped in never confirmed it
                # started — the backup has already been restored to disk by
                # the call above, but THIS process already has the broken
                # new version's modules loaded in memory. Record which
                # version failed, then relaunch fresh (now-restored old
                # code) rather than limp on with what's already loaded —
                # continuing this process would mean "rolled back" but still
                # running the thing that just failed to start.
                updater.note_rollback(app_meta.VERSION)
                apply_update.spawn_detached(updater.relaunch_argv())
                sys.exit(0)
        except SystemExit:
            raise
        except Exception:                            # noqa: BLE001
            # A rollback CHECK failing must never stop Prism starting — the
            # one thing worse than "an update silently didn't roll back"
            # is "Prism won't open at all because its own safety net threw."
            pass

    import core_bridge as CB
    import identity
    cfg = CB.config.load()
    i18n.start(cfg, app)

    # The signed-in member's role decides the accent colour, so a glance at
    # the window says whose copy this is — and, for a manager running several,
    # which one they are looking at. theme's constants have to move with the
    # stylesheet or the custom-painted widgets keep the old blue.
    role_hue = identity.hue()
    theme.apply_role(role_hue)

    style_path = paths.resource("style.qss")
    if os.path.exists(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            qss = f.read()
        # QSS url(…) paths must be absolute and posix-separated: a Windows
        # backslash inside url() is read as an escape and the icon vanishes.
        assets = paths.resource("assets").replace(os.sep, "/")
        # Barlow has no Devanagari or Gujarati; this appends families that do
        # to every font stack. A no-op for Latin-script languages.
        qss = i18n.style_for_script(qss)
        qss = theme.role_stylesheet(qss, role_hue)
        app.setStyleSheet(qss.replace("%ASSETS%", assets))

    # Make sure this member's folders exist before anything tries to write a
    # run into them.
    try:
        import workspace
        workspace.ensure_member(identity.current()["mid"], cfg)
    except OSError:
        pass    # an unreachable share must not stop the app opening

    if os.environ.get("PRISM_SELFTEST"):
        sys.exit(_selftest(app))

    if not _licence_gate():
        sys.exit(0)

    from main_window import MainWindow
    win = MainWindow()
    win.show()

    # The window is up — this version is good enough to trust. Clear the
    # pending-update marker and drop the one-launch-kept backup, so the NEXT
    # launch's check_and_rollback_if_pending() (above) has nothing to roll
    # back and simply starts normally. Never allowed to stop the app: a
    # customer's session must not fail because tidying up an old update's
    # backup did.
    if paths.is_frozen():
        try:
            import apply_update
            _dir = updater.install_dir()
            apply_update.confirm_startup_success(_dir, _dir + ".old")
        except Exception:                            # noqa: BLE001
            pass

    sys.exit(app.exec())


def _paywall(feature: str, parent, state) -> None:
    """Shown when a locked add-on is opened. Registered once, here, so the
    licensing package never has to import Qt."""
    from PySide6.QtWidgets import QDialog
    from dialogs.paywall import PaywallDialog

    sheet = PaywallDialog(feature, parent, state)
    sheet.exec()
    if sheet.relaunch_license:
        # Parented to the window rather than to the sheet, which is closing.
        from dialogs.license_dialog import LicenseDialog
        LicenseDialog(parent, mode="change").exec()


def _licence_gate() -> bool:
    """Decide whether the app may open, before the window is built.

    ────────────────────────────────────────────────────────────────────────
    STARTUP IS LOCAL-FIRST, AND MUST STAY THAT WAY
    ────────────────────────────────────────────────────────────────────────
    Nothing on this path touches the network. The whole decision comes from
    the signed licence token already on disk:

        read ~/.prism/license.json
          → verify the Ed25519 signature
          → verify the device binding and not-before
          → resolve expiry and grace  (licensing/status.py)
          → open the window

    licensing.refresh() below returns immediately and does its work on a
    daemon thread. It is deliberately fired BEFORE state() is read, so the
    renewal is already in flight while the window builds — and deliberately
    not waited on, so it cannot add a millisecond to launch.

    If you are tempted to make anything here synchronous, don't: a customer on
    a corporate network with slow DNS, or on a site with no signal, would wait
    on a request whose answer they already hold a valid signed copy of. The
    same rule applies to moving a network call into MainWindow.__init__ —
    that is still the startup path, just further down it.

    Returns False only when there is no licence at all and the customer closed
    the activation screen — an expired one still opens, read-only, because
    History and everything already produced must stay reachable. Locking
    someone out of their own past output is how a lapsed trial becomes a
    complaint instead of a sale.
    """
    from PySide6.QtWidgets import QDialog

    import licensing
    from dialogs.license_dialog import LicenseDialog

    licensing.set_paywall_handler(_paywall)
    # Server-published selector fixes from the last run, re-verified and applied
    # before anything can use them. Offline and synchronous on purpose: it reads
    # one small local file, and a customer who starts with no connection must
    # still get the fix that was delivered yesterday. The fetch, when the etag
    # is stale, happens on refresh()'s background thread below.
    overridden = licensing.apply_cached_payload()
    if overridden:
        print(f"[prism] applied server config for {overridden} tool(s)")

    # Fire-and-forget: renews the token AND the authorisation lease in the
    # background. The window builds against the cached pair, so a slow
    # corporate DNS costs nothing at startup.
    licensing.refresh()

    state = licensing.state()
    if state.status == licensing.NONE:
        return LicenseDialog(mode="activate").exec() == QDialog.Accepted
    if state.status == licensing.TAMPERED:
        LicenseDialog(mode="problem").exec()
    elif state.status == licensing.EXPIRED:
        LicenseDialog(mode="expired").exec()
    return True


if __name__ == "__main__":
    # The detached update-apply helper (see apply_update.py's module
    # docstring and updater.begin_apply()) — a fresh, separate process the
    # OLD Prism spawned right before quitting. Never the normal launch path:
    # this waits for the old PID to exit, performs the file swap, and
    # relaunches the real app. Checked before QApplication or any other Qt
    # object is touched, since this invocation may have nothing to show.
    if len(sys.argv) >= 6 and sys.argv[1] == "--prism-apply-update":
        import apply_update
        _pid, _install, _staged, _backup = (
            int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])
        sys.exit(apply_update.perform_apply_and_relaunch(
            _pid, _install, _staged, _backup, updater.relaunch_argv()))
    main()
