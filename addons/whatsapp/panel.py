"""The WhatsApp front door."""
from __future__ import annotations

import theme
from widgets.panel_base import AddonFrontDoor


class WhatsAppPanel(AddonFrontDoor):
    TITLE = "WhatsApp"
    BLURB = "Your team's WhatsApp, run by n8n — read here, act on it here."
    ICON = "message"
    HEADLINE = "Open WhatsApp"
    DETAIL = ("Every conversation and contact n8n has logged, plus a manual "
              "send for testing outside the CRM.")
    ACTION = "Open WhatsApp"
    ACTION_ICON = "message"
    KIND = "whatsapp"

    STEPS = [
        ("inbox", "Inbox",
         "Every conversation, read straight from Supabase. Reply, and n8n "
         "sends it and logs it — nothing here talks to WhatsApp on its own."),
        ("user", "Contacts",
         "Searchable, with the one write Prism makes to Supabase itself: a "
         "contact's opt-out flag, because that never sends anything."),
        ("message", "Send",
         "A one-off Cloud API message, straight to Meta, for a manual test "
         "outside the CRM — not part of the logged conversation history."),
        ("sliders", "Settings",
         "The three connections this add-on needs: the WhatsApp number's own "
         "Cloud API credentials, Supabase (an anon key, read-only), and the "
         "n8n webhook that sends a reply."),
    ]

    def build(self):
        self.HUE = theme.OK
        super().build()
