from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from django.db import transaction

from community_base.jobs.models import JobIntent
from community_base.mail.models import EmailDelivery
from community_base.mail.relay import RelayMailClient, RelayMailError
from community_base.mail.service import send
from community_base.testing import FakeRelay, FakeResponse


@pytest.fixture
def relay_settings(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_BACKEND": "relay",
        "RELAY_BASE_URL": "https://relay.example.com",
        "RELAY_API_KEY": "relay-test-key",
    }


@pytest.mark.django_db(transaction=True)
def test_fake_relay_send_reaches_provider_accepted(relay_settings):
    transport = FakeRelay()
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    with patch("community_base.mail.backends.relay.configured_client", return_value=client):
        with transaction.atomic():
            delivery = send(
                "event_registration",
                "person@example.com",
                {"event_name": "Test event"},
                "event-registration:1",
                category="transactional",
                sender="courses",
            )

    delivery.refresh_from_db()
    delivery.job.refresh_from_db()
    assert delivery.state == EmailDelivery.State.PROVIDER_ACCEPTED
    assert delivery.external_message_id in transport.messages
    assert delivery.job.status == JobIntent.Status.SUCCEEDED
    payload = transport.calls[0][2]["json"]
    assert payload["email"] == "person@example.com"
    assert payload["context"] == {"event_name": "Test event"}
    assert payload["template_version"] == 1
    assert payload["from_email"] == "courses"


@pytest.mark.django_db(transaction=True)
def test_relay_suppression_is_terminal_without_retry(relay_settings):
    transport = FakeRelay()
    transport.suppress_next("hard_bounce")
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    with patch("community_base.mail.backends.relay.configured_client", return_value=client):
        with transaction.atomic():
            delivery = send("welcome", "person@example.com", {}, "welcome:suppressed")

    delivery.refresh_from_db()
    delivery.job.refresh_from_db()
    assert delivery.state == EmailDelivery.State.SUPPRESSED
    assert delivery.reason_code == "hard_bounce"
    assert delivery.job.status == JobIntent.Status.SUCCEEDED


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("failure", "state", "job_status"),
    [
        (requests.ConnectionError("unavailable"), "retryable", "failed"),
        (requests.Timeout("unknown acknowledgement"), "ambiguous", "dead"),
    ],
)
def test_transport_failure_classification(relay_settings, failure, state, job_status):
    transport = FakeRelay()
    transport.next_response = failure
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    with patch("community_base.mail.backends.relay.configured_client", return_value=client):
        with transaction.atomic():
            delivery = send("welcome", "person@example.com", {}, f"welcome:{state}")

    delivery.refresh_from_db()
    delivery.job.refresh_from_db()
    assert delivery.state == state
    assert delivery.job.status == job_status


def test_client_rejects_malformed_success_without_exposing_payload():
    transport = FakeRelay()
    transport.next_response = FakeResponse(202, {"message": {"id": "bad"}})
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    delivery = EmailDelivery(
        idempotency_key="welcome:bad",
        purpose="welcome",
        template_key="welcome",
        recipient_email="person@example.com",
        context_hash="0" * 64,
    )
    with pytest.raises(RelayMailError, match="malformed_send_response") as raised:
        client.send(delivery)
    assert "person@example.com" not in str(raised.value)
