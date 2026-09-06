"""What Email will do for another add-on.

Inquiry sends quotes, chasers and PO confirmations, and today does it by
reaching for the mailer itself. Routing that through SEND_MAIL is what lets
Email move into addons/email/ without Inquiry following it.

Note what did NOT change when Email's dialog moved from dialogs/ into this
package: the intent name, and therefore every caller. A contract names where
the work happens today and is the only thing that has to be edited when the
work moves. That is the property being bought.
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

    from addons.email.dialog import EmailComposeDialog
    EmailComposeDialog(cfg, attachments, parent, mode=mode).exec()
