"""Where the reusable licence key lives, when we have to keep one.

The problem
───────────
`~/.prism/license.json` used to hold the customer's licence key in plaintext,
in a world-readable-by-default home directory, forever. It is kept because
`_refresh_once()` uses it to silently re-activate a seat that was released by
mistake — a genuinely good behaviour that saves a support call.

But the key is the ONE reusable credential in the whole system. The token is
device-bound and expires; the lease is device-bound and expires in half an
hour; the key is neither. Anyone who reads that file — a backup, a synced
home directory, a support screen-share, a second user on a shared workstation,
malware with no privileges at all — can type it into their own copy of Prism
and take a seat.

The fix
───────
Put it in the operating system's own credential store, which is encrypted at
rest and gated on the user's login:

    macOS    Keychain
    Windows  Credential Manager (DPAPI)
    Linux    Secret Service (GNOME Keyring / KWallet)

`keyring` is an OPTIONAL import. It is not in requirements.txt as a hard
dependency and this module must work without it, because a headless Linux box
has no Secret Service and a frozen build must not fail to start over a missing
backend. When it is unavailable the key falls back to license.json exactly as
before — no behaviour changes, nothing breaks, and where() reports the
downgrade so diagnostics and Setup can say so honestly.

What this is NOT
────────────────
Not a security boundary. A determined attacker running as the user can read
the keychain too — that is true of every password manager on the machine. It
raises the cost of casual theft from "open a text file" to "run code as that
user and defeat the OS prompt", which is the honest description of what an OS
credential store buys. The real boundary is still that the backend counts
seats and can revoke.
"""
from __future__ import annotations

SERVICE = "Prism (Alphakore)"
ACCOUNT = "licence-key"

# Where the key ended up. Reported by diagnostics and by Setup so a support
# call can tell "we never stored it" from "we stored it in the clear".
KEYRING = "keyring"
FILE = "file"
ABSENT = "absent"

_backend: object | None = None
_probed = False


def _keyring():
    """The keyring module, or None. Probed once — an import that fails, or a
    backend that raises on first use, must cost one attempt, not one per call
    on a path that runs at every launch."""
    global _backend, _probed
    if _probed:
        return _backend
    _probed = True
    try:
        import keyring                                  # noqa: PLC0415
        from keyring.backends import fail                # noqa: PLC0415

        backend = keyring.get_keyring()
        # keyring installs a null backend when nothing usable is present, and
        # it raises only when you try to USE it. Detect that here rather than
        # discovering it inside activate().
        if isinstance(backend, fail.Keyring):
            _backend = None
        else:
            _backend = keyring
    except Exception:                                   # noqa: BLE001
        # Not installed, no backend, no D-Bus session, a locked keyring — all
        # the same to us, and none of them may stop Prism opening.
        _backend = None
    return _backend


def available() -> bool:
    return _keyring() is not None


def store_key(key: str) -> bool:
    """Put the key in the OS credential store. True if it went in.

    A False return is not an error the caller should surface — it means "use
    the file", which is what the previous version of Prism did unconditionally.
    """
    kr = _keyring()
    if kr is None or not key:
        return False
    try:
        kr.set_password(SERVICE, ACCOUNT, key)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def fetch_key() -> str:
    kr = _keyring()
    if kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, ACCOUNT) or ""
    except Exception:                                   # noqa: BLE001
        # A keyring that is present but locked. Nothing to do but carry on
        # without automatic re-activation; the customer can retype the key.
        return ""


def forget_key() -> None:
    """Remove it. Deactivation goes through here — 'release this device' has
    to mean the credential is gone too, or the next launch re-activates."""
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, ACCOUNT)
    except Exception:                                   # noqa: BLE001
        pass    # already absent, or locked. Either way there is no recovery.


def where(file_has_key: bool) -> str:
    """Which of the two places currently holds a key, for diagnostics."""
    if fetch_key():
        return KEYRING
    return FILE if file_has_key else ABSENT
