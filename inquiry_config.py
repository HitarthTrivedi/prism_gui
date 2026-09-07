"""Reading Email automation's settings out of the config dict.

Pure functions over a plain dict. No Qt, no engine, no widgets -- which is
the point: they were trapped inside a 1,100-line Qt setup dialog, and
everything that needed to ask "is the mailbox set up?" had to import that
dialog to find out.

That inverted the layering in two places that matter:

  dashboard_data.py           a root DATA module, feeding Home, importing
                              a dialog
  the inquiry panel           a widget importing a dialog, six times over

Both worked only because every one of those eight imports is inside a
function rather than at module scope -- a deferred import is a circular
dependency you have agreed not to look at. It also meant Email automation
could not be extracted into an add-on without dragging Home along with it,
since Home reads the register through dashboard_data.

The dialog now imports these from here and re-exports them, so nothing that
already said `from addons.inquiry.setup import is_ready` breaks.

────────────────────────────────────────────────────────────────────────────
Several mailboxes, one register
────────────────────────────────────────────────────────────────────────────
`cfg["inquiry"]["accounts"]` is a list, and each entry carries its own
`state` (the read bookmark), because two mailboxes sharing one bookmark
would skip or re-import each other's mail. The old single-mailbox keys --
`account` and `state` -- are still written, mirroring the first entry, so a
config saved by this version opens cleanly in the previous one.
`accounts_of()` is the one reader that understands both.
"""
from __future__ import annotations

import os

DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Prism Inquiries")

# ── the working screen's tabs ────────────────────────────────────────────
# Here rather than in addons/inquiry/dialog.py because addons/inquiry/panel.py
# needs them and was importing a 4,313-line dialog AT MODULE SCOPE to get
# them -- the one widget->dialog import in the tree that is not a deferred
# "open this modal", and therefore a real load-order dependency rather than a
# navigational one.
#
# Still translated at render time, never here. `TABS` is in
# devtools/extract_strings.py's COPY_TABLES and this file is scanned, so the
# labels remain translatable exactly as they were.
TABS = [
    ("to_quote", "1 · To quote"),
    ("waiting", "2 · No answer yet"),
    ("replies", "3 · They answered"),
    ("orders", "4 · Order came"),
    ("register", "5 · All inquiries"),
    ("arrived", "6 · All mail"),
]
TAB_INDEX = {key: index for index, (key, _label) in enumerate(TABS)}
# Tabs whose title carries a live count. The reference tabs do not: "All
# inquiries (312)" is not a number anybody acts on.
COUNTED_TABS = ("to_quote", "waiting", "replies", "orders")


def settings_of(cfg: dict) -> dict:
    return dict(cfg.get("inquiry") or {})


def accounts_of(cfg: dict) -> list[dict]:
    """Every configured mailbox, in the order they were added.

    Reads the list form first; a config from before mailboxes were a list is
    wrapped on the way out — the legacy `account` becomes entry one and
    brings the legacy `state` bookmark with it, so an existing customer's
    first multi-mailbox check carries on from where their last single-mailbox
    check stopped instead of re-importing a month of mail.

    Copies, not references: callers edit these freely and save what they
    mean to save.
    """
    s = settings_of(cfg)
    accounts = [dict(a) for a in (s.get("accounts") or []) if a]
    if not accounts and s.get("account"):
        legacy = dict(s["account"])
        legacy["state"] = dict(s.get("state") or {})
        accounts = [legacy]
    return accounts


def is_complete(account: dict) -> bool:
    """Enough of a mailbox to attempt a connection.

    Named `_complete` while it lived in the dialog, and imported under that
    name from addons/inquiry/panel.py anyway -- a private name with an
    outside caller is just a public name nobody renamed. `_complete` stays
    available as an alias so no existing import breaks.
    """
    return bool(account.get("address") and account.get("password")
                and account.get("host"))


def is_ready(cfg: dict) -> bool:
    """Enough set up to run a check. Deliberately only a mailbox and the
    folder — a rate list matters at quoting time, not at reading time, and
    demanding one up front would stop somebody trying the read-only half."""
    s = settings_of(cfg)
    return bool(any(is_complete(a) for a in accounts_of(cfg))
                and s.get("folder"))


# Back-compat alias. See is_complete's docstring.
_complete = is_complete
