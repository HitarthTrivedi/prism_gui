#!/usr/bin/env python3
"""Digitally sign a built Prism, on whichever OS built it.

    python packaging/codesign.py dist/Prism            # Linux/Windows folder
    python packaging/codesign.py dist/Prism.app        # macOS bundle

Called automatically by packaging/build.py after a successful build. Run it by
hand only when re-signing something that is already built.

────────────────────────────────────────────────────────────────────────────
WHY THIS EXISTS, AND WHAT IT IS NOT
────────────────────────────────────────────────────────────────────────────
Code signing is not a licensing control and does not protect the licensing
system. A signature says "this binary came from Alphakore and has not been
altered since"; it does not stop anyone modifying the binary, it stops them
doing so *and still passing as us*.

What it actually buys, all of which are real:

  · Windows SmartScreen stops telling a new customer that Prism is an
    unrecognised app from an unknown publisher — which, for a paid B2B tool
    bought by someone's IT manager, is the difference between an install and
    a phone call.
  · macOS Gatekeeper stops refusing to open it at all. An unsigned,
    un-notarised .app on a current macOS cannot be opened by double-clicking
    it, at all, and the workaround involves right-click-Open and a
    reassurance dialog.
  · A modified copy is DETECTABLE. That is the honest security value.

The real boundary remains backend authorisation: a resigned or unsigned build
still cannot obtain an authorisation lease, because it has no private key.

────────────────────────────────────────────────────────────────────────────
WHERE THE CREDENTIALS LIVE
────────────────────────────────────────────────────────────────────────────
Nowhere in this repository, ever. Everything comes from the environment, which
in practice means the CI secret store (GitHub Actions → Settings → Secrets)
and, locally, a shell that sourced them from somewhere outside the tree.

Windows
    WINDOWS_CERT_PFX_BASE64   base64 of the .pfx  (an EV token cannot be
                              exported; see the note in sign_windows)
    WINDOWS_CERT_PASSWORD     its password
    WINDOWS_TIMESTAMP_URL     optional, defaults to DigiCert's

macOS
    MACOS_SIGN_IDENTITY       "Developer ID Application: Alphakore (TEAMID)"
    MACOS_NOTARY_PROFILE      a `xcrun notarytool store-credentials` profile
                              name — preferred, keeps the app password out of
                              the environment entirely
      …or…
    MACOS_NOTARY_APPLE_ID     Apple ID
    MACOS_NOTARY_PASSWORD     an app-specific password
    MACOS_NOTARY_TEAM_ID      the team id

Linux
    Nothing. Linux desktop software is not code-signed in any way a user's
    machine checks; the distribution channel (a checksum next to the tarball)
    is the equivalent, and build.py writes that.

TIMESTAMPING IS NOT OPTIONAL on Windows. Without a timestamp every signature
becomes invalid the day the certificate expires — including on copies
customers installed years earlier.

Unconfigured is a WARNING, not a failure. A developer building locally must
not need the company's signing certificate, and a build that dies for want of
one is a build nobody runs.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile

# Windows consoles are cp1252 and cannot encode the characters below — see
# packaging/build.py for the CI failure that found this. Degrade, don't die.
#
# Under __main__ only: at import time sys.stdout belongs to the importer,
# not to us. devtools/mint.py is imported by five test files, so at module
# level this block would re-encode pytest's own capture stream as a side
# effect of collecting a test — a script reaching into its caller's I/O.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
sys.path.insert(0, GUI)
import app_meta   # noqa: E402

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    # Never echo the command when it might carry a password — signtool takes
    # /p <password> on the command line, and a CI log is forever.
    printable = [("***" if i and cmd[i - 1] in ("/p", "--password") else part)
                 for i, part in enumerate(cmd)]
    print("»", " ".join(printable))
    return subprocess.run(cmd, check=True, **kw)


def _skip(reason: str) -> bool:
    print(f"!  not signing — {reason}")
    return False


# ── Windows ────────────────────────────────────────────────────────────────
def _signtool() -> str:
    """signtool.exe, from PATH or the Windows SDK."""
    found = shutil.which("signtool")
    if found:
        return found
    roots = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("ProgramFiles", r"C:\Program Files")]
    for root in roots:
        base = os.path.join(root, "Windows Kits", "10", "bin")
        if not os.path.isdir(base):
            continue
        # Newest SDK first — older signtool builds lack /fd and /td.
        for version in sorted(os.listdir(base), reverse=True):
            candidate = os.path.join(base, version, "x64", "signtool.exe")
            if os.path.exists(candidate):
                return candidate
    return ""


def sign_windows(target: str) -> bool:
    """Sign every executable and DLL in the build folder.

    Signing only Prism.exe is the mistake worth naming: PyInstaller's
    one-folder layout puts the Python runtime and every extension module
    beside it as DLLs, and an installer or an enterprise allow-list that
    checks those will find them unsigned.

    An EV certificate on a hardware token cannot be exported to a .pfx and
    therefore cannot go in an environment variable. For EV, use the token's
    own CSP through signtool's /f + /csp + /kc arguments on a self-hosted
    runner, or a cloud signing service — the loop below is otherwise the same.
    """
    pfx_b64 = os.environ.get("WINDOWS_CERT_PFX_BASE64", "")
    password = os.environ.get("WINDOWS_CERT_PASSWORD", "")
    if not pfx_b64:
        return _skip("WINDOWS_CERT_PFX_BASE64 is not set")
    tool = _signtool()
    if not tool:
        return _skip("signtool.exe not found (install the Windows 10 SDK)")

    binaries = [os.path.join(root, name)
                for root, _dirs, names in os.walk(target)
                for name in names
                if name.lower().endswith((".exe", ".dll", ".pyd"))]
    if not binaries:
        return _skip(f"no signable binaries under {target}")

    pfx_fd, pfx_path = tempfile.mkstemp(suffix=".pfx")
    try:
        with os.fdopen(pfx_fd, "wb") as f:
            f.write(base64.b64decode(pfx_b64))
        os.chmod(pfx_path, 0o600)
        cmd = [tool, "sign", "/f", pfx_path]
        if password:
            cmd += ["/p", password]
        cmd += [
            "/fd", "sha256",                      # file digest
            "/tr", os.environ.get("WINDOWS_TIMESTAMP_URL",
                                  DEFAULT_TIMESTAMP_URL),
            "/td", "sha256",                      # timestamp digest
            "/d", app_meta.NAME,
            "/du", app_meta.WEBSITE,
        ]
        # In batches: the command line has a length limit and a one-folder
        # build is hundreds of files.
        for i in range(0, len(binaries), 50):
            _run(cmd + binaries[i:i + 50])
        _run([tool, "verify", "/pa", "/all",
              os.path.join(target, f"{app_meta.NAME}.exe")])
    finally:
        try:
            os.unlink(pfx_path)
        except OSError:
            pass
    print(f"✓ signed {len(binaries)} binaries")
    return True


# ── macOS ──────────────────────────────────────────────────────────────────
def sign_macos(target: str) -> bool:
    """Sign, then notarise, then staple.

    All three are needed. Signing alone still gets "cannot be opened because
    Apple cannot check it for malicious software" — notarisation is what
    clears that, and stapling is what makes it work on a machine that is
    offline when the customer first opens Prism.

    --options runtime (the hardened runtime) is mandatory for notarisation.
    That is also what makes the entitlements file necessary: the hardened
    runtime blocks the unsigned-memory execution CPython needs.
    """
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "")
    if not identity:
        return _skip("MACOS_SIGN_IDENTITY is not set")
    if not shutil.which("codesign"):
        return _skip("codesign not found (install the Xcode command line tools)")

    entitlements = os.path.join(HERE, "entitlements.plist")
    _run(["codesign", "--force", "--deep", "--timestamp",
          "--options", "runtime",
          "--entitlements", entitlements,
          "--sign", identity, target])
    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", target])

    if not _notarise(target):
        print("!  signed but NOT notarised — Gatekeeper will still refuse "
              "this on a customer's Mac. Set MACOS_NOTARY_PROFILE (or the "
              "MACOS_NOTARY_APPLE_ID trio) before shipping.")
        return True

    # Staple the ticket INTO the bundle, so a Mac with no network still
    # recognises it. Without this, first launch on a locked-down site fails.
    _run(["xcrun", "stapler", "staple", target])
    print("✓ signed, notarised and stapled")
    return True


def _notarise(target: str) -> bool:
    if not shutil.which("xcrun"):
        return False
    profile = os.environ.get("MACOS_NOTARY_PROFILE", "")
    apple_id = os.environ.get("MACOS_NOTARY_APPLE_ID", "")
    if not profile and not apple_id:
        return False

    # notarytool only accepts a zip, a dmg or a pkg — never a bare .app.
    archive = os.path.join(tempfile.mkdtemp(), f"{app_meta.NAME}.zip")
    _run(["ditto", "-c", "-k", "--keepParent", target, archive])

    cmd = ["xcrun", "notarytool", "submit", archive, "--wait"]
    if profile:
        cmd += ["--keychain-profile", profile]
    else:
        cmd += ["--apple-id", apple_id,
                "--password", os.environ.get("MACOS_NOTARY_PASSWORD", ""),
                "--team-id", os.environ.get("MACOS_NOTARY_TEAM_ID", "")]
    _run(cmd)
    return True


def sign(target: str) -> bool:
    """Sign `target` if this platform and this environment can. Never raises
    for want of a certificate — see the module docstring."""
    if not os.path.exists(target):
        return _skip(f"{target} does not exist")
    if IS_WIN:
        return sign_windows(target)
    if IS_MAC:
        return sign_macos(target)
    print("·  Linux builds are not code-signed; build.py writes a SHA-256 "
          "checksum beside each artifact instead.")
    return False


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sign(sys.argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
