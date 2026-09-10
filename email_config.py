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
    # Install-wide like `folder`: how fast and how many, not whose account.
    if existing.get("send") and "send" not in block:
        block["send"] = dict(existing["send"])
    if "save_to_sent" in existing and "save_to_sent" not in block:
        block["save_to_sent"] = bool(existing["save_to_sent"])
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
    send = settings_of(cfg).get("send")
    if send and "send" not in block:
        block["send"] = dict(send)
    if "save_to_sent" in settings_of(cfg) and "save_to_sent" not in block:
        block["save_to_sent"] = bool(settings_of(cfg)["save_to_sent"])
    out["email"] = block
    return out


# ────────────────────────────────────────────────────────────────────────────
# Pace and limits -- how a list goes out
# ────────────────────────────────────────────────────────────────────────────
# `cfg["email"]["send"]` holds four numbers. They are install-wide (a pace is
# a habit, not an account), carried across a save the way `folder` is, and
# read by the Email add-on's window and by the terminal's /email alike, so
# the two cannot pace a list two different ways.
#
#   gap_seconds      the fixed pause between two messages
#   jitter_seconds   a random 0..this added to every pause, so the pauses
#                    are not a metronome
#   max_per_run      send to at most this many per press of Send; 0 = all
#   max_per_day      send at most this many from one address per calendar
#                    day, counted off the sent log; 0 = no limit
#
# The defaults reproduce what the engine did before there were knobs (a
# flat two seconds, no cap), so a config without the block sends exactly
# as it always has.

DEFAULT_GAP_SECONDS = 2.0
SEND_KEYS = ("gap_seconds", "jitter_seconds", "max_per_run", "max_per_day")


def send_policy(cfg: dict) -> dict:
    """The four numbers, always all four, always sane: negatives and
    junk read as the default, and the gap is never below half a second --
    a zero gap is exactly the burst the pause exists to prevent."""
    raw = settings_of(cfg).get("send") or {}

    def _num(key, default, cast):
        try:
            v = cast(raw.get(key, default))
        except (TypeError, ValueError):
            v = default
        return v if v >= 0 else default

    return {
        "gap_seconds": max(0.5, _num("gap_seconds", DEFAULT_GAP_SECONDS, float)),
        "jitter_seconds": _num("jitter_seconds", 0.0, float),
        "max_per_run": _num("max_per_run", 0, int),
        "max_per_day": _num("max_per_day", 0, int),
    }


def with_send_policy(cfg: dict, policy: dict) -> dict:
    """A copy of cfg with the four numbers written into the email block.
    Only the four: a stray key from a screen never reaches the engine."""
    out = dict(cfg or {})
    block = settings_of(cfg)
    block["send"] = {k: policy[k] for k in SEND_KEYS if k in policy}
    out["email"] = block
    return out


def plan_send(policy: dict, wanted: int, sent_today: int = 0) -> tuple[int, list[str]]:
    """How many of `wanted` may go now, and why not all of them, in words.

    Pure arithmetic over the policy so the window, the terminal and the
    tests agree on the number. The daily cap is what is left of it after
    what the sent log already shows for today; the per-run cap is flat.
    """
    allowed = max(0, int(wanted))
    reasons = []
    per_day = int(policy.get("max_per_day") or 0)
    if per_day > 0:
        left = max(0, per_day - max(0, int(sent_today)))
        if left < allowed:
            allowed = left
            reasons.append(
                "daily limit %d, %d already sent today" % (per_day, sent_today))
    per_run = int(policy.get("max_per_run") or 0)
    if per_run > 0 and per_run < allowed:
        allowed = per_run
        reasons.append("at most %d per send" % per_run)
    return allowed, reasons


# ────────────────────────────────────────────────────────────────────────────
# A copy in Sent
# ────────────────────────────────────────────────────────────────────────────
# `cfg["email"]["save_to_sent"]` is the engine's own switch (core/mailer, 10
# Sep 2026): after each SMTP send it files a copy into the account's Sent
# folder over IMAP, so a Prism-sent mail shows in Outlook and webmail. The
# engine defaults it ON and treats a failed copy as a note, never an error.
# Install-wide like `folder` and `send`, and carried across a save the same
# way, so the window and the terminal's /email agree.

def save_to_sent(cfg: dict) -> bool:
    """Whether a copy of each send is filed in Sent. Missing = on."""
    return bool(settings_of(cfg).get("save_to_sent", True))


def with_save_to_sent(cfg: dict, on: bool) -> dict:
    """A copy of cfg with the switch written into the email block."""
    out = dict(cfg or {})
    block = settings_of(cfg)
    block["save_to_sent"] = bool(on)
    out["email"] = block
    return out
