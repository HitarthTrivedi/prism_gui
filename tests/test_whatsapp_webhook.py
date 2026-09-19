"""webhook parses Meta's real payload shapes and guards the setup handshake."""
from __future__ import annotations

from addons.whatsapp.webhook import (
    DeliveryStatus, InboundMessage, parse_events, verify_subscription,
)


def test_verify_subscription_echoes_challenge_on_match():
    params = {"hub.mode": "subscribe", "hub.verify_token": "s3cret",
              "hub.challenge": "1158201444"}
    assert verify_subscription(params, "s3cret") == "1158201444"


def test_verify_subscription_rejects_wrong_token():
    params = {"hub.mode": "subscribe", "hub.verify_token": "nope",
              "hub.challenge": "123"}
    assert verify_subscription(params, "s3cret") is None


def test_verify_subscription_accepts_list_valued_params():
    # urllib.parse.parse_qs yields {key: [value]}.
    params = {"hub.mode": ["subscribe"], "hub.verify_token": ["s3cret"],
              "hub.challenge": ["999"]}
    assert verify_subscription(params, "s3cret") == "999"


_INBOUND = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "WABA_ID",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15550000",
                             "phone_number_id": "PNID"},
                "contacts": [{"profile": {"name": "Asha"},
                              "wa_id": "919812345678"}],
                "messages": [{
                    "from": "919812345678", "id": "wamid.IN1",
                    "timestamp": "1690000000", "type": "text",
                    "text": {"body": "yes, interested"},
                }],
            },
        }],
    }],
}


def test_parse_inbound_message():
    messages, statuses = parse_events(_INBOUND)
    assert statuses == []
    assert len(messages) == 1
    m = messages[0]
    assert isinstance(m, InboundMessage)
    assert (m.wa_id, m.msg_id, m.type, m.text) == (
        "919812345678", "wamid.IN1", "text", "yes, interested")
    assert m.name == "Asha"
    assert m.phone_number_id == "PNID"


_STATUS = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "PNID"},
        "statuses": [{"id": "wamid.OUT1", "status": "delivered",
                      "timestamp": "1690000100",
                      "recipient_id": "919812345678"}],
    }}]}],
}


def test_parse_delivery_status():
    messages, statuses = parse_events(_STATUS)
    assert messages == []
    assert len(statuses) == 1
    s = statuses[0]
    assert isinstance(s, DeliveryStatus)
    assert (s.msg_id, s.status, s.recipient_id) == (
        "wamid.OUT1", "delivered", "919812345678")


def test_button_reply_text_is_extracted():
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "P"},
        "messages": [{"from": "9198", "id": "w1", "type": "button",
                      "button": {"text": "Stop"}, "timestamp": "1"}],
    }}]}]}
    messages, _ = parse_events(payload)
    assert messages[0].text == "Stop"
    assert messages[0].type == "button"


def test_malformed_payload_is_safe():
    for junk in (None, {}, {"entry": None}, {"entry": [{}]},
                 {"entry": [{"changes": [{"value": {}}]}]}, "nope", 42):
        assert parse_events(junk) == ([], [])
