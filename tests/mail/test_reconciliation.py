from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from community_base.mail.models import EmailDelivery
from community_base.mail.reconciliation import reconcile_deliveries
from community_base.mail.relay import RelayMailClient, RelayMailError
from tests.mail.fake_relay import FakeMailRelayTransport


def local_delivery(key="reconcile:one"):
    return EmailDelivery.objects.create(
        idempotency_key=key,
        purpose="welcome",
        template_key="welcome",
        recipient_email="person@example.com",
        context_hash="0" * 64,
    )


def client_and_transport():
    transport = FakeMailRelayTransport()
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    return client, transport


@pytest.mark.django_db
def test_reconciliation_applies_remote_delivery_and_is_idempotent():
    delivery = local_delivery()
    client, transport = client_and_transport()
    response = transport._send(
        {
            "email": delivery.recipient_email,
            "template_key": delivery.template_key,
            "template_version": 3,
            "idempotency_key": delivery.idempotency_key,
            "context": {},
        }
    )
    message = response.document["message"]
    transport.messages[message["id"]]["status"] = "delivered"

    first = reconcile_deliveries(timezone.now() - timedelta(hours=1), client=client)
    second = reconcile_deliveries(timezone.now() - timedelta(hours=1), client=client)

    delivery.refresh_from_db()
    assert first == (first.__class__)(received=1, matched=1, changed=1, missing=0)
    assert second.changed == 0
    assert delivery.state == EmailDelivery.State.DELIVERED
    assert delivery.external_message_id == message["id"]
    assert delivery.template_version == 3


@pytest.mark.django_db
def test_reconciliation_counts_remote_message_missing_locally():
    client, transport = client_and_transport()
    transport._send(
        {
            "email": "person@example.com",
            "template_key": "welcome",
            "template_version": 1,
            "idempotency_key": "missing:local",
            "context": {},
        }
    )
    result = reconcile_deliveries(timezone.now() - timedelta(hours=1), client=client)
    assert result.missing == 1
    assert result.matched == 0


@pytest.mark.django_db
def test_reconciliation_rejects_message_identity_conflict():
    delivery = local_delivery()
    delivery.external_message_id = "different-message"
    delivery.save(update_fields=("external_message_id",))
    client, transport = client_and_transport()
    transport._send(
        {
            "email": delivery.recipient_email,
            "template_key": delivery.template_key,
            "template_version": 1,
            "idempotency_key": delivery.idempotency_key,
            "context": {},
        }
    )
    with pytest.raises(RelayMailError, match="message_delivery_conflict"):
        reconcile_deliveries(timezone.now() - timedelta(hours=1), client=client)
