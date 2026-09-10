"""Gerber — PCB measurements taken from the Gerber files themselves."""
from __future__ import annotations

from addons import names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="gerber",
    label="Gerber",
    # Its own key since 2026-09-10: Gerber is sold as its own add-on
    # (plans.FEATURES["gerber"]). It rode "boq" before that, so every licence
    # that held "boq" on that date was granted "gerber" server-side and nobody
    # lost access when this line changed.
    feature="gerber",
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
    # The first add-on whose dotted strings point INSIDE its own package.
    # Everything else still names its current home; this one has moved.
    dialog="addons.gerber.dialog:GerberDialog",
    panel="addons.gerber.panel:GerberPanel",
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
