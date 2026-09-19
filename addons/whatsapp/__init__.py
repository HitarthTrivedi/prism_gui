"""WhatsApp Business Platform — the engine core for Prism's WhatsApp add-on.

Plan B (see docs/WHATSAPP_B0_CHECKLIST.md and the project memory): Prism becomes
a Meta Tech Provider and replaces AiSensy's software layer. This package holds
the protocol-level pieces the desktop add-on and, later, the always-on gateway
both build on:

  · cloud_api.py — send messages/templates through Meta's Graph API (stdlib
    urllib, so nothing here pulls a dependency and every call is unit-testable
    with an injected transport).
  · webhook.py   — verify Meta's subscription handshake and parse inbound
    messages and delivery statuses out of a webhook payload. Pure functions.

These two modules are STDLIB ONLY on purpose: they are imported by the add-on's
workers AND, later, by a headless gateway process, and neither should drag Qt or
the engine onto its thread. The Qt dialog/panel/manifest live beside them but
import from here, never the reverse.
"""
