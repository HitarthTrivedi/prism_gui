"""Leads & Outreach — qualify a sheet of leads and draft outreach, from your
own account. The engine is the top-level `prospector/` package; this manifest
is the one line the registry needs to draw the screen and open the workbench."""
from __future__ import annotations

from addons.manifest import ACCENT, HOME, RAIL, Addon

MANIFEST = Addon(
    key="leads",
    label="Leads & Outreach",
    feature="leads",
    tip="Qualify a sheet of leads and draft outreach — from your own account",
    blurb="Qualify leads, draft outreach",
    icon="user",
    tone=ACCENT,
    order=45,
    shelves=(RAIL, HOME),
    screen="leads",
    dialog="addons.leads.dialog:LeadsDialog",
    panel="addons.leads.panel:LeadsPanel",
    kind="leads",
)
