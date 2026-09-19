"""cloud_api sends the right HTTP and reads Meta's reply — with a fake transport,
so no socket is opened and the suite stays network-free."""
from __future__ import annotations

import json

import pytest

from addons.whatsapp.cloud_api import (
    WhatsAppError, register_number, send_template, send_text,
)


class _Fake:
    """Captures the one call and returns a canned (status, body)."""

    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body or {"messages": [{"id": "wamid.TEST"}]}
        self.url = self.payload = self.headers = None

    def __call__(self, url, payload, headers):
        self.url, self.headers = url, headers
        self.payload = json.loads(payload.decode("utf-8"))
        return self.status, json.dumps(self.body).encode("utf-8")


def test_send_text_builds_the_right_url_and_headers():
    fake = _Fake()
    wamid = send_text("1234567890", "TOKEN", "919999999999", "hello",
                      transport=fake)
    assert wamid == "wamid.TEST"
    assert fake.url == "https://graph.facebook.com/v21.0/1234567890/messages"
    assert fake.headers["Authorization"] == "Bearer TOKEN"
    assert fake.headers["Content-Type"] == "application/json"


def test_send_text_payload_shape():
    fake = _Fake()
    send_text("PNID", "T", "919999999999", "hi there", transport=fake)
    assert fake.payload == {
        "messaging_product": "whatsapp",
        "to": "919999999999",
        "type": "text",
        "text": {"preview_url": False, "body": "hi there"},
    }


def test_send_template_payload_shape():
    fake = _Fake()
    send_template("PNID", "T", "919999999999", "hello_world",
                  language="en_US", transport=fake)
    assert fake.payload["type"] == "template"
    assert fake.payload["template"] == {
        "name": "hello_world", "language": {"code": "en_US"}}


def test_meta_error_becomes_whatsapp_error_with_code():
    fake = _Fake(status=400, body={"error": {
        "message": "Recipient phone number not in allowed list", "code": 131030}})
    with pytest.raises(WhatsAppError) as ei:
        send_text("PNID", "T", "919999999999", "hi", transport=fake)
    assert ei.value.code == 131030
    assert "allowed list" in str(ei.value)


def test_missing_credentials_refuses_before_touching_the_wire():
    calls = []

    def transport(*a):
        calls.append(a)
        return 200, b"{}"

    with pytest.raises(WhatsAppError):
        send_text("", "", "919999999999", "hi", transport=transport)
    assert calls == []


def test_api_version_is_overridable():
    fake = _Fake()
    send_text("PNID", "T", "9199", "hi", api_version="v20.0", transport=fake)
    assert "/v20.0/" in fake.url


def test_register_number_posts_the_pin():
    fake = _Fake(body={"success": True})
    assert register_number("PNID", "T", "123456", transport=fake) is True
    assert fake.url == "https://graph.facebook.com/v21.0/PNID/register"
    assert fake.payload == {"messaging_product": "whatsapp", "pin": "123456"}


def test_register_number_rejects_a_bad_pin_before_the_wire():
    calls = []

    def transport(*a):
        calls.append(a)
        return 200, b'{"success": true}'

    with pytest.raises(WhatsAppError):
        register_number("PNID", "T", "12", transport=transport)
    assert calls == []


def test_register_number_surfaces_meta_error_code():
    fake = _Fake(status=400, body={"error": {"message": "already registered",
                                             "code": 133005}})
    with pytest.raises(WhatsAppError) as ei:
        register_number("PNID", "T", "123456", transport=fake)
    assert ei.value.code == 133005
