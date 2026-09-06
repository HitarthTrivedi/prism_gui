"""What Email will do for another add-on.

Inquiry sends quotes, chasers and PO confirmations, and today does it by
reaching for the mailer itself. Routing that through SEND_MAIL is what lets
Email move into addons/email/ without Inquiry following it.

The dialog still lives in dialogs/email_dialog.py -- Email has not moved
yet -- and that is fine: a contract names where the work happens TODAY and
changes when the work moves. Nothing outside this file has to know.
"""
from __future__ import annotations

import core_bridge as CB


def compose_with_files(parent, cfg: dict, paths, mode: str = "one") -> None:
    """Open the composer with these files attached.

    Plain paths in. `mode` is Email's own vocabulary ("one" for a single
    message, the batch modes for a mail-out) and defaults to the safe one,
    so a caller that does not know about modes cannot accidentally start a
    bulk send.
    """
    files = CB.get_files()
    attachments = []
    for path in paths or ():
        try:
            attachments.append(files.attach(path))
        except Exception:                               # noqa: BLE001
            continue

    from dialogs.email_dialog import EmailComposeDialog
    EmailComposeDialog(cfg, attachments, parent, mode=mode).exec()
