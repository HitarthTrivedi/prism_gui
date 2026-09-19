"""Send WhatsApp messages through Meta's Cloud API (the Graph API).

One thin function per message kind, each returning the message id (the *wamid*)
Meta assigns — the handle every later delivery/read receipt is keyed on, so the
worker stores it the moment a send succeeds. HTTP is done with urllib so this
module stays dependency-free and stdlib-only, and the transport is injectable so
the whole thing tests without opening a socket.

Nothing here knows about Qt, the engine or Prism's config: it takes a phone
number id and an access token — the caller's own Cloud API credentials, BYO-key
like every other key in Prism — and talks to Meta. The add-on's worker is what
reads those out of config and calls in here off the UI thread.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v21.0"

# A transport is (url, payload_bytes, headers) -> (status_code, body_bytes).
# The real one is below; tests pass a fake so no socket is opened.
Transport = Callable[[str, bytes, dict], tuple]


class WhatsAppError(Exception):
    """A Cloud API call Meta rejected, or a transport failure.

    `code` is Meta's numeric error code when there is one (131030 'recipient not
    in allowed list' on an unverified number, 190 'expired token', 132000
    'template does not exist' …) — the field worth branching on, so the worker
    can tell a fix-your-setup error from a per-recipient one and message the
    user accordingly."""

    def __init__(self, message: str, *, code: int | None = None,
                 status: int | None = None, raw: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.raw = raw or {}


def _urllib_transport(url: str, payload: bytes, headers: dict) -> tuple:
    req = urllib.request.Request(url, data=payload, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        # Meta returns a JSON error body with the 4xx/5xx — read it, don't lose
        # it, so _send can surface Meta's own message and code.
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise WhatsAppError("Could not reach Meta: %s" % (e.reason,)) from e


def _decode(status: int, raw: bytes) -> dict:
    """Parse a Cloud API response body, raising WhatsAppError on any Meta error
    (HTTP 4xx/5xx, or a JSON `error` object) so every caller reports Meta's own
    message and code the same way."""
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if status >= 400 or "error" in data:
        err = data.get("error") or {}
        raise WhatsAppError(
            err.get("message") or ("Meta returned HTTP %s" % (status,)),
            code=err.get("code"), status=status, raw=data)
    return data


def _send(phone_number_id: str, token: str, message: dict, *,
          api_version: str = DEFAULT_API_VERSION,
          transport: Optional[Transport] = None) -> str:
    if not phone_number_id or not token:
        raise WhatsAppError("A phone number id and access token are required — "
                            "connect a WhatsApp number first.")
    url = "%s/%s/%s/messages" % (GRAPH_HOST, api_version, phone_number_id)
    body = dict(message)
    body["messaging_product"] = "whatsapp"
    payload = json.dumps(body).encode("utf-8")
    headers = {"Authorization": "Bearer %s" % (token,),
               "Content-Type": "application/json"}
    send = transport or _urllib_transport
    status, raw = send(url, payload, headers)
    data = _decode(status, raw)
    messages = data.get("messages") or []
    if not messages or not messages[0].get("id"):
        raise WhatsAppError("Meta accepted the call but returned no message id",
                            status=status, raw=data)
    return messages[0]["id"]


def send_text(phone_number_id: str, token: str, to: str, body: str, *,
              preview_url: bool = False,
              api_version: str = DEFAULT_API_VERSION,
              transport: Optional[Transport] = None) -> str:
    """Send a free-form text message and return its wamid.

    Only valid inside an open 24-hour service window (a reply to something the
    customer sent us). To OPEN a conversation Meta requires a pre-approved
    template — that is `send_template`."""
    return _send(phone_number_id, token,
                 {"to": to, "type": "text",
                  "text": {"preview_url": preview_url, "body": body}},
                 api_version=api_version, transport=transport)


def send_template(phone_number_id: str, token: str, to: str, name: str, *,
                  language: str = "en_US", components: list | None = None,
                  api_version: str = DEFAULT_API_VERSION,
                  transport: Optional[Transport] = None) -> str:
    """Send a pre-approved template and return its wamid.

    A template is the only thing Meta allows to OPEN a conversation (marketing,
    utility or authentication). `name` and `language` must match a template
    already approved on the WABA; `components` carries the body/header variables
    when the template has any."""
    template: dict = {"name": name, "language": {"code": language}}
    if components:
        template["components"] = components
    return _send(phone_number_id, token,
                 {"to": to, "type": "template", "template": template},
                 api_version=api_version, transport=transport)


def register_number(phone_number_id: str, token: str, pin: str, *,
                    api_version: str = DEFAULT_API_VERSION,
                    transport: Optional[Transport] = None) -> bool:
    """Register a number for Cloud API sending — the one-time step behind a fresh
    number and behind error #133010 ('account not registered'). `pin` is a
    6-digit two-step-verification PIN you choose for the number (set here if the
    number has none). Returns True on success. Meta's own test number is
    pre-registered and does not need this."""
    if not phone_number_id or not token:
        raise WhatsAppError("A phone number id and access token are required.")
    if not (pin and pin.isdigit() and len(pin) == 6):
        raise WhatsAppError("The registration PIN must be exactly 6 digits.")
    url = "%s/%s/%s/register" % (GRAPH_HOST, api_version, phone_number_id)
    payload = json.dumps({"messaging_product": "whatsapp",
                          "pin": pin}).encode("utf-8")
    headers = {"Authorization": "Bearer %s" % (token,),
               "Content-Type": "application/json"}
    send = transport or _urllib_transport
    status, raw = send(url, payload, headers)
    data = _decode(status, raw)
    return bool(data.get("success", True))
