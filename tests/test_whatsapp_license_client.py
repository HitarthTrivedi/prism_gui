"""license_client talks to Prism's own licence server, never to Supabase or
n8n directly — every call carries license_id/device_fp and lands on
licensing.client._post, the same call every other licence-server request in
this app goes through (see tests/test_license_seats.py::ClientCall for the
convention this follows). No socket is opened; nothing here needs a real
licence, a real Supabase project or a real n8n webhook to run."""
from __future__ import annotations

from unittest import mock

import pytest

import licensing
from addons.whatsapp import license_client as lc
from licensing.client import ServerError, Unreachable

LICENSE_ID = "lic_test123"
DEVICE_FP = "aaaaaaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _identity():
    with mock.patch.object(licensing, "state") as st, \
            mock.patch.object(licensing, "device_fingerprint",
                              return_value=DEVICE_FP):
        st.return_value.license_id = LICENSE_ID
        yield


def _fake_post(responses):
    seen = []

    def fake(endpoint, body, **kw):
        seen.append((endpoint, body, kw))
        return responses
    return fake, seen


def test_every_call_carries_the_same_auth_pair():
    fake, seen = _fake_post({"conversations": []})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        lc.list_conversations()
    endpoint, body, kw = seen[0]
    assert endpoint == "/v1/whatsapp/conversations"
    assert body["license_id"] == LICENSE_ID
    assert body["device_fp"] == DEVICE_FP
    assert kw["retries"] == lc.RETRIES


def test_list_conversations_unwraps_the_envelope():
    fake, _ = _fake_post({"conversations": [{"id": "c1"}]})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        rows = lc.list_conversations()
    assert rows == [{"id": "c1"}]


def test_get_thread_sends_the_conversation_id():
    fake, seen = _fake_post({"messages": [{"text": "hi"}]})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        rows = lc.get_thread("c1")
    assert seen[0][0] == "/v1/whatsapp/thread"
    assert seen[0][1]["conversation_id"] == "c1"
    assert rows == [{"text": "hi"}]


def test_send_reply_posts_phone_and_text():
    fake, seen = _fake_post({"ok": True})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        lc.send_reply(phone="9198", text="hello", conversation_id="c1",
                      contact_id="k1")
    _, body, _ = seen[0]
    assert body["phone"] == "9198"
    assert body["text"] == "hello"
    assert body["conversation_id"] == "c1"
    assert body["contact_id"] == "k1"


def test_list_contacts_passes_search():
    fake, seen = _fake_post({"contacts": []})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        lc.list_contacts(search="asha")
    assert seen[0][1]["search"] == "asha"


def test_set_contact_opt_out_returns_the_row():
    fake, seen = _fake_post({"contact": {"id": "k1", "opt_out": True}})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        row = lc.set_contact_opt_out("k1", True)
    assert row == {"id": "k1", "opt_out": True}
    assert seen[0][1]["opt_out"] is True


def test_resolve_audience_defaults_tags_to_empty_list():
    fake, seen = _fake_post({"audience": []})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        lc.resolve_audience()
    assert seen[0][1]["tags"] == []


def test_send_broadcast_returns_the_server_response_whole():
    fake, seen = _fake_post({"campaign": {"id": "camp1"}, "audience_size": 3})
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        result = lc.send_broadcast(template_name="hello_world", tags=["vip"])
    assert result == {"campaign": {"id": "camp1"}, "audience_size": 3}
    assert seen[0][1]["template_name"] == "hello_world"
    assert seen[0][1]["tags"] == ["vip"]


def test_a_server_refusal_becomes_a_whatsapp_error_with_its_message():
    def fake(endpoint, body, **kw):
        raise ServerError("FEATURE_NOT_LICENSED", "That add-on isn't part "
                          "of your licence.")
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        with pytest.raises(lc.WhatsAppError, match="isn't part"):
            lc.list_conversations()


def test_an_unreachable_server_becomes_a_whatsapp_error_too():
    def fake(endpoint, body, **kw):
        raise Unreachable("timed out")
    with mock.patch.object(licensing.client, "_post", side_effect=fake):
        with pytest.raises(lc.WhatsAppError, match="Couldn't reach"):
            lc.list_conversations()
