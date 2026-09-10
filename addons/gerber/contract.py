"""What Gerber will do for another add-on.

Nothing wants MEASURE_PCB yet. Inquiry is the obvious consumer -- an order
arrives with board files attached and somebody has to measure them -- and
the day it does, that is one `wants=` entry and one button on Inquiry's
side, not an import.

Written now rather than when a caller appears, because an offer that does
not resolve is indistinguishable from a feature the customer has not bought:
both draw no button and neither raises. tests/test_addon_contract.py
resolves every declared handler for exactly that reason.
"""
from __future__ import annotations

import core_bridge as CB


def open_with_files(parent, cfg: dict, paths) -> None:
    """Measure these Gerber files.

    Plain paths in; the shaping into attachments happens here, on the
    offering side, because what counts as an attachment is Gerber's business
    and not the caller's.
    """
    files = CB.get_files()
    attachments = []
    for path in paths or ():
        try:
            attachments.append(files.attach(path))
        except Exception:                               # noqa: BLE001
            continue

    from addons.gerber.dialog import GerberDialog
    GerberDialog(cfg, attachments, parent).exec()
