"""BOM — Bill of Materials, the parts list to fabricate a drawing or spec."""
from __future__ import annotations

from addons import names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="bom",
    label="BOM",
    # Rides "boq" for a different reason than Gerber does. A "bom" key DOES
    # exist in plans.FEATURES and is sellable -- but the licence server has
    # never been told about it, and the add-on ships as a mode inside the BOQ
    # dialog, so BOQ's route is the one that has to be guarded. Consequence
    # worth knowing before anyone prices it: today, buying "bom" without
    # "boq" gets you nothing, and buying "boq" gets you BOM for free.
    feature="boq",
    tip="Bill of Materials — the parts list to fabricate it, measured from "
        "a CAD drawing or a written spec",
    # DRIFT RESOLVED HERE, and this one was user-facing. BOM shipped: it is
    # routed, gated, has its own screen index and opens a real dialog. The
    # rail shows it in the accent colour. Home still described it as "Coming
    # soon" in grey, because that string was written when BOM was a SOON
    # placeholder and nothing made the two tables change together. Anyone
    # working from Home has been told a shipped add-on does not exist yet.
    blurb="The parts list, off a drawing",
    icon="list",
    tone=ACCENT,
    # Last on both shelves. One `order` reproduces the rail AND Home exactly,
    # because the rail is simply Home with reel and motion filtered out --
    # which is a fact neither table could express while there were two.
    order=70,
    shelves=(RAIL, HOME),
    screen="bom",
    # Not its own dialog: BOQ's, in a different mode. Exactly the kind of
    # implementation detail an intent name is supposed to hide -- and the
    # clearest illustration of why the add-on split is worth doing, since
    # today "a whole new add-on" means "a mode flag in someone else's file".
    dialog="dialogs.boq_dialog:BoqDialog",
    probe="core_bridge:boq_available",
    kind="bom",
    run_prefixes=("BOM — ", "/bom "),
    engine=("boq",),
    offers=(Offer(names.LIST_PARTS,
                  "addons.bom.contract:open_with_files",
                  "List the parts"),),
)
