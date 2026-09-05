from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from community_base.mail.models import CallbackEvent, EmailDelivery
from community_base.testing import FakeRelay

SECRET = "callback-test-secret"


@pytest.fixture(autouse=True)
def callback_settings(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "RELAY_WEBHOOK_SECRET": SECRET,
    }


@pytest.fixture
def delivery(db):
    return EmailDelivery.objects.create(
        idempotency_key="callback-ingress:one",
        purpose="welcome",
        template_key="welcome",
        recipient_email="person@example.com",
        context_hash="0" * 64,
    )


def signed_post(client, payload, *, timestamp=None, secret=SECRET):
    return FakeRelay().post_callback(client, payload, secret, timestamp=timestamp)


def payload(delivery, event_id, event_type, **extra):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "message_id": "relay-message-1",
        "client_reference": delivery.idempotency_key,
        "timestamp": timezone.now().isoformat(),
    } | extra


@pytest.mark.django_db
def test_signed_reordered_callbacks_converge_on_delivered(client, delivery):
    delivered = signed_post(client, payload(delivery, "callback:delivered", "delivery.delivered"))
    accepted = signed_post(client, payload(delivery, "callback:accepted", "delivery.accepted"))
    assert delivered.status_code == accepted.status_code == 200
    assert accepted.json()["applied"] is False
    delivery.refresh_from_db()
    assert delivery.state == EmailDelivery.State.DELIVERED
    assert delivery.external_message_id == "relay-message-1"


@pytest.mark.django_db
def test_callback_event_is_deduplicated_and_changed_replay_conflicts(client, delivery):
    document = payload(delivery, "callback:one", "delivery.delivered")
    first = signed_post(client, document)
    replay = signed_post(client, document)
    conflict = signed_post(client, document | {"event_type": "delivery.complained"})
    assert first.json()["created"] is True
    assert replay.json() == {"status": "ok", "created": False, "applied": False}
    assert conflict.status_code == 409
    assert CallbackEvent.objects.count() == 1


@pytest.mark.django_db
def test_hard_bounce_and_complaint_are_authoritative(client, delivery):
    signed_post(
        client,
        payload(
            delivery,
            "callback:bounce",
            "delivery.bounced",
            bounce_type="hard",
            reason_code="mailbox_unavailable",
        ),
    )
    signed_post(
        client,
        payload(delivery, "callback:complaint", "delivery.complained"),
    )
    delivery.refresh_from_db()
    assert delivery.state == EmailDelivery.State.COMPLAINED


@pytest.mark.django_db
def test_engagement_is_deduplicated_without_changing_delivery_state(client, delivery):
    response = signed_post(client, payload(delivery, "callback:opened", "engagement.opened"))
    delivery.refresh_from_db()
    event = CallbackEvent.objects.get()
    assert response.status_code == 200
    assert event.event_type == "engagement.opened"
    assert event.state == ""
    assert delivery.state == EmailDelivery.State.PENDING


@pytest.mark.django_db
def test_subscription_callback_can_be_deduplicated_without_delivery(client):
    document = {
        "event_id": "callback:subscription",
        "event_type": "subscription.changed",
        "message_id": None,
        "client_reference": None,
        "timestamp": timezone.now().isoformat(),
    }
    assert signed_post(client, document).status_code == 200
    assert CallbackEvent.objects.get().delivery is None


@pytest.mark.django_db
def test_callback_rejects_stale_or_altered_signatures(client, delivery):
    document = payload(delivery, "callback:stale", "delivery.delivered")
    stale = str(int((timezone.now() - timedelta(minutes=10)).timestamp()))
    assert signed_post(client, document, timestamp=stale).status_code == 401
    assert signed_post(client, document, secret="wrong-secret").status_code == 401
    assert not CallbackEvent.objects.exists()


@pytest.mark.django_db
def test_unknown_delivery_and_message_mismatch_fail_closed(client, delivery):
    unknown = signed_post(
        client,
        payload(delivery, "callback:unknown", "delivery.delivered")
        | {"client_reference": "missing"},
    )
    delivery.external_message_id = "original-message"
    delivery.save(update_fields=("external_message_id",))
    mismatch = signed_post(client, payload(delivery, "callback:mismatch", "delivery.delivered"))
    assert unknown.status_code == 404
    assert mismatch.status_code == 409
