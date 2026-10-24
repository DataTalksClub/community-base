"""Capture the native Relay request for persisted mail recipient options."""

import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest

from community_base.mail.relay import RelayMailClient, RelayMailError
from community_base.testing import FakeRelay


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Transport option tests must not use network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def delivery(options):
    return SimpleNamespace(
        recipient_email="member@example.invalid",
        template_key="welcome",
        template_version=1,
        idempotency_key="welcome:transport-options",
        context_data={"greeting": "Hello"},
        category="transactional",
        sender_id="welcome",
        transport_options=options,
    )


def relay_client():
    transport = FakeRelay()
    return RelayMailClient(
        "https://relay.example.invalid", "relay-test-key", transport=transport
    ), transport


def test_recipient_options_reach_the_native_relay_wire_without_mutating_delivery():
    options = {
        "reply_to": ["reply@example.invalid"],
        "cc": ["copy@example.invalid"],
        "bcc": ["hidden@example.invalid"],
    }
    original = delivery(options)
    expected_options = deepcopy(options)
    client, transport = relay_client()
    client.send(original)

    assert len(transport.calls) == 1
    assert transport.calls[0][2]["json"] == {
        "email": original.recipient_email,
        "template_key": "welcome",
        "template_version": 1,
        "idempotency_key": "welcome:transport-options",
        "context": {"greeting": "Hello"},
        "category": "transactional",
        "from_email": "welcome",
        "reply_to": "reply@example.invalid",
        "cc": ["copy@example.invalid"],
        "bcc": ["hidden@example.invalid"],
    }
    assert original.transport_options == expected_options


@pytest.mark.parametrize("options", [None, {}, {"reply_to": [], "cc": [], "bcc": []}])
def test_absent_options_keep_the_existing_request_shape(options):
    client, transport = relay_client()
    client.send(delivery(options))
    assert len(transport.calls) == 1
    assert set(transport.calls[0][2]["json"]) == {
        "email",
        "template_key",
        "template_version",
        "idempotency_key",
        "context",
        "category",
        "from_email",
    }


def test_ses_configuration_and_unknown_options_are_never_merged_into_relay_payload():
    client, transport = relay_client()
    client.send(
        delivery(
            {
                "configuration_set": "local-only",
                "headers": {"X-Unapproved": "value"},
                "email": "override@example.invalid",
                "from_email": "override",
                "context": {"unexpected": True},
            }
        )
    )
    assert len(transport.calls) == 1
    payload = transport.calls[0][2]["json"]
    assert "configuration_set" not in payload
    assert "headers" not in payload
    assert payload["email"] == "member@example.invalid"
    assert payload["from_email"] == "welcome"
    assert payload["context"] == {"greeting": "Hello"}


def test_multiple_reply_to_addresses_fail_safely_before_any_http_request():
    client, transport = relay_client()
    with pytest.raises(RelayMailError, match="^unsupported_relay_reply_to_count$") as caught:
        client.send(delivery({"reply_to": ["first@example.invalid", "second@example.invalid"]}))
    assert transport.calls == []
    assert not caught.value.retryable
    assert not caught.value.ambiguous
