"""Gerber — PCB measurements taken from the Gerber files themselves."""
from __future__ import annotations

from addons import names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="gerber",
    label="Gerber",
    # Rides "boq", not a dedicated "gerber" key. There is no gerber feature
    # on the licence server and this add-on has one prospective customer, so
    # gating on a key nobody can be granted would deny everyone -- including
    # the one account actually testing it. The day a real gerber feature
    # exists there, this is a one-word diff and nothing else moves. That is
    # precisely what plans.py's job-not-screen naming was built for.
    feature="boq",
    tip="PCB size, track width & spacing, drill size and count — measured "
        "from the Gerber files, never seen by an AI",
    blurb="Measured off the Gerber files",
    # DRIFT RESOLVED HERE: the rail said "file", Home said "grid". Two
    # tables, one add-on, two icons, and a comment in home_panel.py claiming
    # it "must never drift from" the rail. "file" is the rail's value and the
    # rail is the primary navigation, so it wins; a registry cannot hold a
    # contradiction, and holding one was the bug.
    icon="file",
    tone=ACCENT,
    order=30,
    shelves=(RAIL, HOME),
    screen="gerber",
    dialog="dialogs.gerber_dialog:GerberDialog",
    probe="core_bridge:gerber_available",
    kind="gerber",
    run_prefixes=("Gerber — ", "/gerber "),
    engine=("gerber",),
    # Nobody wants this yet. Inquiry is the obvious consumer, and the day it
    # does, that is one `wants=` entry and one button -- not an import.
    offers=(Offer(names.MEASURE_PCB,
                  "addons.gerber.contract:open_with_files",
                  "Measure this board"),),
)
