"""The WhatsApp add-on's connection to Prism's own licence server — never to
Supabase or n8n directly, and this file holds no credential for either.

Reads land on Supabase and a send lands on n8n, exactly as before, but now on
the SERVER's own service_role key and webhook URLs
(prism-license-server/app/routes/whatsapp.py, app/whatsapp_crm.py). Every
call here carries the same license_id + device_fp pair every other Prism
call sends, and the server checks it the same way: a seated device, on a
licence that actually includes "marketing" (see licensing/__init__.py). A
client that holds neither key can do nothing here its own licence would not
already have let it do directly, and every action is attributable to the
seat that made it — which a Supabase anon key shared by every install never
was.

Goes through licensing.client.call() rather than opening a second HTTP path:
same address, same headers, same retry-once-on-cold-start behaviour every
other licence-server call already has tuned.
"""
from __future__ import annotations

from typing import Optional

import app_meta
import licensing
from licensing.client import ServerError, Unreachable

TIMEOUT = 20
RETRIES = 1


class WhatsAppError(Exception):
    """A call the licence server refused, or couldn't be reached at all —
    one exception type so a worker's `except Exception` needs to know only
    this module, not licensing.client's."""


def _auth_body(**extra) -> dict:
    body = {
        "license_id": licensing.state().license_id,
        "device_fp": licensing.device_fingerprint(),
        "app_version": app_meta.VERSION,
    }
    body.update(extra)
    return body


def _call(endpoint: str, **extra) -> dict:
    try:
        return licensing.client.call(
            "/v1/whatsapp" + endpoint, _auth_body(**extra),
            app_version=app_meta.VERSION, timeout=TIMEOUT, retries=RETRIES)
    except ServerError as e:
        raise WhatsAppError(e.message) from e
    except Unreachable:
        raise WhatsAppError(
            "Couldn't reach Prism's licence server for WhatsApp — check "
            "this computer's internet connection and try again.") from None


# ── inbox ────────────────────────────────────────────────────────────────────

def list_conversations() -> list:
    return _call("/conversations").get("conversations") or []


def get_thread(conversation_id) -> list:
    return _call("/thread", conversation_id=str(conversation_id)).get("messages") or []


def send_reply(*, phone: str, text: str, conversation_id="", contact_id="") -> dict:
    return _call("/reply", phone=phone, text=text,
                conversation_id=str(conversation_id) if conversation_id else "",
                contact_id=str(contact_id) if contact_id else "")


# ── contacts, tags, segments ──────────────────────────────────────────────────

def list_contacts(*, search: str = "") -> list:
    return _call("/contacts", search=search).get("contacts") or []


def set_contact_opt_out(contact_id, opt_out: bool) -> Optional[dict]:
    return _call("/contacts/opt-out", contact_id=str(contact_id),
                opt_out=bool(opt_out)).get("contact") or None


def set_contact_tags(contact_id, tags: list) -> Optional[dict]:
    return _call("/contacts/tags", contact_id=str(contact_id),
                tags=list(tags or [])).get("contact") or None


def list_tags() -> list:
    return _call("/tags").get("tags") or []


def list_segments() -> list:
    return _call("/segments").get("segments") or []


def save_segment(name: str, tags: list) -> dict:
    return _call("/segments/save", name=name, tags=list(tags or [])).get("segment") or {}


def delete_segment(segment_id) -> None:
    _call("/segments/delete", segment_id=str(segment_id))


def resolve_audience(*, tags: list = None) -> list:
    return _call("/audience", tags=list(tags or [])).get("audience") or []


# ── broadcasts ─────────────────────────────────────────────────────────────

def list_campaigns() -> list:
    return _call("/campaigns").get("campaigns") or []


def send_broadcast(*, template_name: str, language: str = "en_US",
                   tags: list = None, segment_name: str = "") -> dict:
    return _call("/broadcast", template_name=template_name, language=language,
                tags=list(tags or []), segment_name=segment_name)
