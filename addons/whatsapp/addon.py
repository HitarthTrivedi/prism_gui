"""WhatsApp — your team's inbox, contacts and broadcasts, in Prism.

n8n (its own always-on host) is the WhatsApp engine — Meta credentials, the AI
conversation bot, the sends. Prism is the workspace on top of it: a rail
add-on like Leads, whose whole surface lives in the window
(addons/whatsapp/panel.py → workbench.py). Every read and send goes through
the licence server (addons/whatsapp/license_client.py), so no Supabase key or
n8n URL ever sits on a customer's computer. cloud_api.py + webhook.py are the
older direct-Meta path, kept for Settings' manual test send and for a gateway
process, should Prism ever run one itself.

STDLIB ONLY, like the rest of the manifest layer.
"""
from __future__ import annotations

from addons.manifest import HOME, OK, RAIL, Addon

MANIFEST = Addon(
    key="whatsapp",
    label="WhatsApp",
    # Rides the "marketing" licence feature: WhatsApp broadcast/outreach is the
    # marketing channel, and no other add-on claims that key. A one-word diff if
    # WhatsApp ever earns its own licence line. See plans.FEATURES.
    feature="marketing",
    tip="Your team's WhatsApp — inbox, contacts and broadcasts in one place",
    blurb="Reach customers on WhatsApp",
    icon="message",
    tone=OK,                       # WhatsApp green — the OK token's ramp
    order=48,                      # just after Leads (45), before Reel (50)
    # On the rail now, between Leads and BOM by order — a live inbox/CRM tool
    # a team opens daily earns a row the way Leads did, not a Home tile.
    # Pinned by tests/test_addon_contract.py's GOLDEN_RAIL and GOLDEN_HOME.
    shelves=(RAIL, HOME),
    screen="whatsapp",
    panel="addons.whatsapp.panel:WhatsAppPanel",
    dialog="addons.whatsapp.dialog:WhatsAppDialog",
    kind="whatsapp",
    run_prefixes=("WhatsApp — ", "/whatsapp "),
)
