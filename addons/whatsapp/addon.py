"""WhatsApp — a CRM run by n8n, read and acted on from Prism.

Plan B, as it actually landed: n8n (its own always-on host) is the WhatsApp
engine — Meta credentials, the AI conversation bot, the broadcast/follow-up
sends. Prism is the front door onto it: a rail add-on like BOQ or Leads, with
its own screen (addons/whatsapp/panel.py) and working window
(addons/whatsapp/dialog.py) reading Supabase and triggering n8n's webhooks.
cloud_api.py + webhook.py are the older direct-Meta path, kept for the
dialog's manual "Send" tab and for a gateway process, should Prism ever run
one itself.

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
    tip="Your team's WhatsApp, run by n8n — inbox, contacts and sends, read "
        "and acted on from here",
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
