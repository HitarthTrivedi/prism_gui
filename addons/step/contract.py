"""What STEP will do for another add-on.

Nothing wants MEASURE_MODEL yet. Inquiry is the obvious consumer -- an
order arrives with a .step attached and somebody has to measure it -- and
the day it does, that is one `wants=` entry and one button on Inquiry's
side, not an import.

Written now rather than when a caller appears, because an offer that does
not resolve is indistinguishable from a feature the customer has not
bought: both draw no button and neither raises.
tests/test_addon_contract.py resolves every declared handler for exactly
that reason.
"""
from __future__ import annotations


def open_with_files(parent, cfg: dict, paths) -> None:
    """Measure these STEP models.

    Plain paths in. The dialog does its own shaping -- it takes only
    .step/.stp files and says which it left out -- so the caller needs to
    know nothing about what a model is. The attachments list the dialog's
    constructor takes is the workbench's, which a caller by intent does not
    have; the models go in through the same door a drop uses.
    """
    from addons.step.dialog import StepDialog
    dlg = StepDialog(cfg, [], parent)
    dlg._on_files_added(list(paths or ()))
    dlg.exec()
