"""Reading the Email add-on's sending accounts out of the config dict.

Pure functions over a plain dict. No Qt, no engine, no widgets -- the same
shape, and for the same reason, as `inquiry_config.py` next door.

Why this is a root module rather than something inside `addons/email/`:
Email automation sends from these accounts too -- the quotation, the
reminder, the win-back -- and no add-on may import another. Putting the
readers in the Email add-on's package would make the Inquiry add-on depend
on the Email add-on, which is the exact coupling the add-on split removes.
Both import this instead, the way both already read `cfg["email"]` today.

────────────────────────────────────────────────────────────────────────────
Several sending addresses, one default
────────────────────────────────────────────────────────────────────────────
`cfg["email"]["accounts"]` is a list. The old single-account keys --
`address`, `password`, `host`, `port` -- are still written at the top of the
block, mirroring whichever account is the default, so:

  · a config saved by this version opens cleanly in the previous one, and
  · `core/mailer.py:is_configured()` and `verify()`, which read those top
    level keys and are called from five places, keep working untouched and
    keep answering about the account that will ACTUALLY be used.

That second point is what makes this change small. The gates did not have to
be rewritten to understand a list; they read the mirror, and the mirror is
the default sender.

The default is simply the first active account, so "make this the default"
is "move it to the top" -- one concept, not two, and nothing to get out of
step with the list order the user can see.

`sending_accounts_of()` is the one reader that understands both shapes.
"""
from __future__ import annotations

# Keys that describe an account TO PRISM rather than to the mail server.
# They must never reach the engine: `core/mailer.py:_connect()` reads this
# dict straight, and a stray key there is at best ignored and at worst a
# TypeError on a day nobody wants to be debugging SMTP.
_LOCAL_KEYS = ("label", "active")


def settings_of(cfg: dict) -> dict:
    return dict((cfg or {}).get("email") or {})


def sending_accounts_of(cfg: dict) -> list[dict]:
    """Every configured sending address, in the order they were added.

    Reads the list form first; a config from before sending was a list is
    wrapped on the way out, so an existing customer with one account set up
    reads as exactly one account and nothing about their sending changes.

    Copies, not references: callers edit these freely and save what they
    mean to save.
    """
    s = settings_of(cfg)
    accounts = [dict(a) for a in (s.get("accounts") or []) if a]
    if not accounts and s.get("address"):
        accounts = [{k: v for k, v in s.items() if k != "accounts"}]
    return accounts


def is_complete(account: dict) -> bool:
    """Enough of an account to attempt a sign-in.

    The same three fields `core/mailer.py:is_configured()` insists on, and
    deliberately the same three -- two different answers to "is this usable"
    is how a screen offers a Send button that the engine then refuses.
    """
    account = account or {}
    return bool(account.get("address") and account.get("password")
                and account.get("host"))


def is_active(account: dict) -> bool:
    """Whether this account is in play.

    Absent means active. A config written before there was a switch has no
    `active` key, and reading that as "off" would silently stop an existing
    customer's mail going out -- the worst possible reading of a missing
    field.
    """
    return bool((account or {}).get("active", True))


def active_senders(cfg: dict) -> list[dict]:
    """The accounts a message could go out from, in list order."""
    return [a for a in sending_accounts_of(cfg)
            if is_active(a) and is_complete(a)]


def default_sender(cfg: dict) -> dict:
    """The account that sends unless somebody picks another. {} if none."""
    active = active_senders(cfg)
    return active[0] if active else {}


def can_send(cfg: dict) -> bool:
    """True when there is at least one account able to send."""
    return bool(default_sender(cfg))


def account_block(cfg: dict, accounts: list[dict]) -> dict:
    """The `cfg["email"]` block for this list: the list, plus the mirror.

    The one place the mirror rule lives. Written here rather than in the
    setup dialog because the reminder screen and the quotation screen must
    be able to trust it without knowing how the dialog spells it, and
    because a mirror maintained in two places is a mirror that will
    disagree with itself.

    `folder` is carried across from whatever was already saved: it is where
    the sent log is kept, an install-wide setting rather than an account's,
    and it has never been on this dialog to re-enter.
    """
    existing = settings_of(cfg)
    accounts = [dict(a) for a in (accounts or []) if a.get("address")]
    default = next((a for a in accounts if is_active(a) and is_complete(a)),
                   accounts[0] if accounts else {})
    block = {k: v for k, v in default.items() if k not in _LOCAL_KEYS}
    if existing.get("folder") and "folder" not in block:
        block["folder"] = existing["folder"]
    block["accounts"] = accounts
    return block


def cfg_for_sender(cfg: dict, account: dict) -> dict:
    """A copy of `cfg` that sends as `account`.

    The same overlay Email automation already uses to read several mailboxes
    with a single-mailbox engine (`addons/inquiry/dialog.py:_check_account`,
    which sets `engine_cfg["inbox"]`). The engine keeps its one account per
    call and knows nothing about lists; the app fans out.

    Given no account this returns the config unchanged, so a caller that
    cannot resolve a sender sends exactly what it would have sent before
    rather than sending from nowhere.
    """
    if not account:
        return dict(cfg or {})
    out = dict(cfg or {})
    block = {k: v for k, v in account.items() if k not in _LOCAL_KEYS}
    folder = settings_of(cfg).get("folder")
    if folder and "folder" not in block:
        block["folder"] = folder
    out["email"] = block
    return out
