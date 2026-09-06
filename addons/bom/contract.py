"""What BOM will do for another add-on.

BOM's dialog is BOQ's dialog in mode="bom" -- see addons/bom/addon.py's
provided_by. This resolves it THROUGH THE REGISTRY rather than importing
addons.boq directly, which is the difference between a declared dependency
and a smuggled one: the registry is shared infrastructure every add-on may
use, and the manifest is where the borrowing is written down and tested.

If BOM ever gets a dialog of its own, this file does not change -- only the
manifest does.
"""
from __future__ import annotations

from addons import registry


def open_with_files(parent, cfg: dict, paths) -> None:
    """List the parts on these drawings.

    Same contract as BOQ's: plain paths in, the offering side does its own
    shaping.
    """
    entry = registry.by_key("bom")
    if entry is None or not entry.dialog:
        return
    handler = registry.resolve("addons.boq.contract:open_with_files")
    handler(parent, cfg, paths, mode="bom")
