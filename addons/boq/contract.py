"""What BOQ will do for another add-on, and the only way in from outside.

Before this, addons/inquiry/dialog.py did:

    files = CB.get_files()
    attachments = []
    for path in drawings:
        try:
            attachments.append(files.attach(path))
        except Exception:
            continue
    from shell.dialogs.boq_dialog import BoqDialog
    BoqDialog(self.cfg, attachments, self).exec()

Five things Inquiry knew about BOQ: its module path, its class name, its
constructor signature, that an "attachment" is whatever CB.get_files().attach
returns, and implicitly that the customer is entitled to open it. Every one
of those is a reason the two files could not move independently, and the
fourth is the subtle one -- Inquiry was doing BOQ's own data shaping.

Now Inquiry hands over PATHS and an intent name. The shaping happens here,
on the offering side, which is the rule: the add-on that does the work
decides what the work needs.
"""
from __future__ import annotations

import core_bridge as CB


def open_with_files(parent, cfg: dict, paths, mode: str = "boq") -> None:
    """Measure these drawings and put the result in front of the user.

    `paths` is plain data -- a list of strings. Never a Qt object and never
    an engine object, so that the caller does not have to import either to
    talk to us, and so the payload survives being logged or replayed.

    A path that will not attach is skipped rather than fatal: one unreadable
    drawing on an inquiry with four should not stop the other three being
    measured, and the dialog says what it got.
    """
    files = CB.get_files()
    attachments = []
    for path in paths or ():
        try:
            attachments.append(files.attach(path))
        except Exception:                               # noqa: BLE001
            continue

    from addons.boq.dialog import BoqDialog
    BoqDialog(cfg, attachments, parent, mode=mode).exec()
