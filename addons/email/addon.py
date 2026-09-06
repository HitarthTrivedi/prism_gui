"""Email — draft and send an email from the attached files, your account."""
from __future__ import annotations

from addons import names
from addons.manifest import WARN, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="email",
    label="Email",
    feature="email",
    tip="Draft & send an email from attached files",
    blurb="Draft & send, your account",
    icon="mail",
    tone=WARN,
    order=40,
    shelves=(RAIL, HOME),
    # A screen with a dialog behind it, like BOQ and Inquiry -- not a modal
    # thrown straight from the rail.
    screen="email",
    # EmailComposeDialog, not EmailSetupDialog. The setup dialog is a
    # PRECONDITION the route puts in front of the compose window when no
    # sending account is configured, and it is also reachable on its own from
    # the panel header; it is not the thing the add-on is for.
    dialog="dialogs.email_dialog:EmailComposeDialog",
    kind="email",
    # No display prefix, only the slash command: Email's runs are titled by
    # their subject line, which is the customer's text and therefore cannot
    # be matched on. Worth stating rather than leaving as an apparent
    # omission next to BOQ's two entries.
    run_prefixes=("/email ",),
    engine=("mailer",),
    offers=(Offer(names.SEND_MAIL,
                  "addons.email.contract:compose_with_files",
                  "Send this"),),
)
