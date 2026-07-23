"""Runtime hook: give the stdlib `ssl` module a trusted CA bundle to find.

The bug this fixes: "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate>" — seen on
a client's Mac the first time Prism tried to run automation.

Why this happens on macOS specifically: CPython's `ssl` module is OpenSSL-
based and does NOT talk to the macOS Keychain the way it talks to Windows'
CryptoAPI (`ssl.enum_certificates`) or Linux's `/etc/ssl/certs` (compiled into
OpenSSL's default search path). `ssl.create_default_context()` with no
explicit `cafile` therefore finds nothing to verify against. The python.org
macOS *installer* papers over this with a separate "Install
Certificates.command" script that points the interpreter at `certifi`'s
bundle — but that script is an installer-only convenience. A frozen app never
runs it, and never had a python.org installer in the first place.

Two real call sites in this app hit exactly this, both via a bare
`ssl.create_default_context()`/`urlopen()` with no cafile:
  - undetected_chromedriver's patcher, downloading/verifying the chromedriver
    binary (`urllib.request.urlopen` — the automation feature is the whole
    product, so this is not a cosmetic bug)
  - core/mailer.py's SMTP connection (`ssl.create_default_context()` in
    `_connect()`)

The fix is one process-wide patch, applied here because PyInstaller runtime
hooks execute before ANY other import — including third-party packages — so
every later `import ssl; ssl.create_default_context()` anywhere in the app or
its dependencies picks up the patched version automatically. Nothing at any
call site has to change.

Harmless everywhere else: it only supplies a cafile when the caller didn't
already provide one, so it never overrides an explicit cert and it's a no-op
wherever the OS default already works (Windows, Linux) — it exists for the
platform where it doesn't.
"""
import ssl

try:
    import certifi
except ImportError:
    # requests depends on certifi, so this should never be missing from a
    # build that includes requests — but a hook that can itself crash the
    # app's startup is worse than the bug it's fixing.
    certifi = None

if certifi is not None:
    _CAFILE = certifi.where()
    _original_create_default_context = ssl.create_default_context

    def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH,
                                        *, cafile=None, capath=None,
                                        cadata=None, **kwargs):
        if cafile is None and capath is None and cadata is None:
            cafile = _CAFILE
        return _original_create_default_context(
            purpose, cafile=cafile, capath=capath, cadata=cadata, **kwargs)

    ssl.create_default_context = _patched_create_default_context

    # urllib.request.urlopen() reaches https:// through this factory
    # (http.client calls it when the caller passes no context of its own),
    # not through create_default_context() directly — cover it too, or the
    # chromedriver download keeps failing even after the patch above.
    ssl._create_default_https_context = ssl.create_default_context
