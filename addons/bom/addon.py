"""BOM — Bill of Materials, the parts list to fabricate a drawing or spec."""
from __future__ import annotations

from addons import names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="bom",
    # "BOM & Stock" is what the customer actually bought -- it is the name in
    # plans.FEATURES["bom"] and it was already the name on Home. The rail said
    # just "BOM", a fourth drift on the same add-on. The SKU name wins: it is
    # the one a customer can match against their licence.
    #
    # Safe on the shelf despite the ampersand, because AddonRow draws its name
    # through an _Elided QLabel rather than through the button's own setText,
    # and QLabel does not read "&" as an accelerator. sidebar._amp() is for the
    # rows that DO use setText.
    label="BOM & Stock",
    chip="BOM",                 # the history pill, where there is no room
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
    dialog="addons.boq.dialog:BoqDialog",
    panel="addons.bom.panel:BomPanel",
    # Declared, not smuggled. See manifest.Addon.provided_by.
    provided_by="boq",
    probe="core_bridge:boq_available",
    kind="bom",
    run_prefixes=("BOM — ", "/bom "),
    engine=("boq",),
    offers=(Offer(names.LIST_PARTS,
                  "addons.bom.contract:open_with_files",
                  "List the parts"),),
)
