from __future__ import annotations

import itertools
import uuid

import pytest

from community_base.mail.callbacks import CallbackConflict, CallbackError, apply_callback
from community_base.mail.models import CallbackEvent, EmailDelivery


@pytest.fixture
def delivery(db):
    return EmailDelivery.objects.create(
        idempotency_key=f"callback:{uuid.uuid4()}",
        purpose="welcome",
        template_key="welcome",
        recipient_email="person@example.com",
        context_hash="0" * 64,
    )


@pytest.mark.django_db
def test_reordered_callbacks_converge_on_delivered():
    for index, states in enumerate(
        itertools.permutations(("queued", "provider_accepted", "delivered"))
    ):
        current = EmailDelivery.objects.create(
            idempotency_key=f"ordered:{index}",
            purpose="welcome",
            template_key="welcome",
            recipient_email="person@example.com",
            context_hash="0" * 64,
        )
        for event_index, state in enumerate(states):
            apply_callback(
                event_id=f"event:{index}:{event_index}",
                delivery_id=current.id,
                state=state,
            )
        current.refresh_from_db()
        assert current.state == EmailDelivery.State.DELIVERED


@pytest.mark.django_db
def test_adverse_provider_outcomes_override_success(delivery):
    apply_callback(event_id="event:delivered", delivery_id=delivery.id, state="delivered")
    apply_callback(
        event_id="event:bounce",
        delivery_id=delivery.id,
        state="hard_bounced",
        reason_code="mailbox_unavailable",
    )

    delivery.refresh_from_db()
    assert delivery.state == EmailDelivery.State.HARD_BOUNCED
    assert delivery.reason_code == "mailbox_unavailable"


@pytest.mark.django_db
def test_exact_event_replay_is_deduplicated(delivery):
    first = apply_callback(event_id="event:one", delivery_id=delivery.id, state="delivered")
    replay = apply_callback(event_id="event:one", delivery_id=delivery.id, state="delivered")

    assert first.created is True
    assert replay.created is False
    assert replay.event.pk == first.event.pk
    assert CallbackEvent.objects.count() == 1


@pytest.mark.django_db
def test_changed_event_replay_conflicts(delivery):
    apply_callback(event_id="event:one", delivery_id=delivery.id, state="delivered")
    with pytest.raises(CallbackConflict):
        apply_callback(event_id="event:one", delivery_id=delivery.id, state="complained")


@pytest.mark.django_db
def test_ignored_older_callback_remains_in_history(delivery):
    apply_callback(event_id="event:new", delivery_id=delivery.id, state="delivered")
    result = apply_callback(
        event_id="event:old", delivery_id=delivery.id, state="provider_accepted"
    )

    assert result.created is True
    assert result.applied is False
    assert list(delivery.callback_events.values_list("event_id", flat=True)) == [
        "event:new",
        "event:old",
    ]


@pytest.mark.django_db
def test_callback_rejects_unknown_delivery_without_recording_event():
    with pytest.raises(CallbackError, match="does not exist"):
        apply_callback(event_id="event:missing", delivery_id=uuid.uuid4(), state="delivered")
    assert not CallbackEvent.objects.exists()
