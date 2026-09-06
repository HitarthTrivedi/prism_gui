"""BOQ — Bill of Quantities, from a CAD drawing or a written spec."""
from __future__ import annotations

from addons import names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="boq",
    label="BOQ",
    feature="boq",
    tip="Bill of Quantities — from a CAD drawing, or from a written spec",
    blurb="Quantities off a drawing",
    icon="file",
    tone=ACCENT,
    order=20,
    shelves=(RAIL, HOME),
    screen="boq",
    dialog="dialogs.boq_dialog:BoqDialog",
    # The probe runs AFTER the licence check, never before: a customer who
    # has not bought BOQ should be told that, not sent off to install ezdxf
    # for a feature they still will not be able to open.
    probe="core_bridge:boq_available",
    kind="boq",
    # Matched against titles written as f-strings inside the dialog. Never
    # translate these: a translated prefix matches nothing and History
    # silently empties in Hindi.
    run_prefixes=("BOQ — ", "/boq "),
    engine=("boq",),
    # What Inquiry actually needs when an order arrives with a drawing
    # attached. Inquiry hands paths; BOQ decides what an attachment is --
    # the offering side does the shaping.
    offers=(Offer(names.MEASURE_DRAWING,
                  "addons.boq.contract:open_with_files",
                  "Measure this drawing"),),
)
