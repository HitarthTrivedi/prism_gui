"""Read Meta's WhatsApp webhooks: verify the subscription handshake, and turn a
delivered payload into plain records the rest of Prism can use.

Meta talks to a webhook two ways. Once, at setup, with a GET carrying
`hub.mode`, `hub.verify_token` and `hub.challenge` — answer with the challenge
when the token matches. Then, forever, with POSTs whose JSON carries either
inbound MESSAGES (a customer wrote back) or STATUSES (sent / delivered / read /
failed for something we sent). This module is the pure parsing of both; the
always-on gateway that receives the HTTP is a thin shell around
`verify_subscription` and `parse_events`.

Pure and stdlib-only: no Qt, no network. A headless gateway process imports
this, and so do the tests, which feed it Meta's real sample payload shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InboundMessage:
    """One message a customer sent us. `text` is filled for text / button /
    interactive-reply messages and empty for the rest (image, audio, …); `raw`
    keeps Meta's original object so nothing is lost."""

    wa_id: str                  # the customer's WhatsApp number (E.164, no '+')
    msg_id: str                 # wamid — what a reply / read receipt is keyed on
    type: str                   # "text", "image", "button", "interactive", …
    text: str = ""
    name: str = ""              # the profile name, when Meta includes it
    timestamp: str = ""
    phone_number_id: str = ""   # which of OUR numbers received it
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryStatus:
    """A receipt for something WE sent, keyed on the same wamid `send_*`
    returned — so the add-on can move a message from 'sent' to 'delivered' to
    'read', or surface a 'failed' with Meta's reason."""

    msg_id: str
    status: str                 # "sent", "delivered", "read", "failed"
    recipient_id: str = ""
    timestamp: str = ""
    errors: tuple = ()
    raw: dict = field(default_factory=dict)


def _one(params, key):
    """A single query value whether `params` maps key->value (dict, QueryDict)
    or key->[value] (urllib.parse.parse_qs)."""
    val = params.get(key)
    if isinstance(val, (list, tuple)):
        return val[0] if val else None
    return val


def verify_subscription(params, expected_token: str) -> str | None:
    """The GET handshake. Return the challenge (as a string) to echo back when
    the mode is 'subscribe' and the token matches what we configured; otherwise
    None, which the gateway turns into a 403. `params` is any mapping of the
    query string."""
    if (_one(params, "hub.mode") == "subscribe" and expected_token
            and _one(params, "hub.verify_token") == expected_token):
        challenge = _one(params, "hub.challenge")
        return str(challenge) if challenge is not None else ""
    return None


def parse_events(payload) -> tuple:
    """Split a webhook POST body into (inbound messages, delivery statuses).

    Defensive by design: Meta batches several `entry` objects and several
    `changes` per entry, wraps everything a few layers deep, and a malformed or
    unrelated payload must yield empty lists rather than raise inside a gateway
    that has to keep answering 200. Anything unexpected is skipped, not fatal.
    Returns (list[InboundMessage], list[DeliveryStatus])."""
    messages: list = []
    statuses: list = []
    if not isinstance(payload, dict):
        return messages, statuses
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            meta = value.get("metadata")
            phone_number_id = (meta.get("phone_number_id", "")
                               if isinstance(meta, dict) else "")
            names = {}
            for contact in value.get("contacts") or []:
                if isinstance(contact, dict) and contact.get("wa_id"):
                    profile = contact.get("profile")
                    names[contact["wa_id"]] = (
                        profile.get("name", "")
                        if isinstance(profile, dict) else "")
            for m in value.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                mtype = m.get("type", "")
                text = ""
                if mtype == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif mtype == "button":
                    text = (m.get("button") or {}).get("text", "")
                elif mtype == "interactive":
                    inter = m.get("interactive") or {}
                    part = (inter.get("button_reply")
                            or inter.get("list_reply") or {})
                    text = part.get("title", "") if isinstance(part, dict) else ""
                sender = m.get("from", "")
                messages.append(InboundMessage(
                    wa_id=sender, msg_id=m.get("id", ""), type=mtype,
                    text=text, name=names.get(sender, ""),
                    timestamp=m.get("timestamp", ""),
                    phone_number_id=phone_number_id, raw=m))
            for s in value.get("statuses") or []:
                if not isinstance(s, dict):
                    continue
                statuses.append(DeliveryStatus(
                    msg_id=s.get("id", ""), status=s.get("status", ""),
                    recipient_id=s.get("recipient_id", ""),
                    timestamp=s.get("timestamp", ""),
                    errors=tuple(s.get("errors") or ()), raw=s))
    return messages, statuses
