import uuid
from unittest.mock import patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from community_base.jobs.backends import get_backend
from community_base.jobs.models import JobIntent
from community_base.jobs.relay import RelayError, configured_client
from tests.jobs.fake_relay import FakeRelayTransport, FakeResponse


@pytest.fixture
def relay_settings(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "JOBS_BACKEND": "relay",
        "SITE_KEY": "test-site",
        "SITE_URL": "https://community.example.com/",
        "RELAY_BASE_URL": "https://relay.example.com/",
        "RELAY_API_KEY": "relay-test-key",
    }
    return settings


def make_intent(**overrides):
    values = {
        "handler": "system.noop",
        "key_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "payload": {},
        "payload_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "available_at": timezone.now(),
    }
    values.update(overrides)
    return JobIntent.objects.create(**values)


def test_backend_loader_selects_relay(relay_settings):
    assert get_backend().__name__.endswith(".relay")


@pytest.mark.django_db
def test_relay_backend_submits_webhook_and_persists_task_id(relay_settings):
    intent = make_intent(correlation_id=str(uuid.uuid4()))
    transport = FakeRelayTransport()
    client = configured_client(transport=transport)

    with patch("community_base.jobs.backends.relay.configured_client", return_value=client):
        task_id = get_backend().submit(intent.id)

    intent.refresh_from_db()
    assert intent.external_id == task_id
    assert intent.status == JobIntent.Status.SUBMITTED
    request = transport.tasks[task_id]["request"]
    assert request == {
        "type": "webhook",
        "url": "https://community.example.com/internal/jobs/run",
        "idempotency_key": f"test-site:{intent.key_hash}",
        "params": {"intent_id": str(intent.id)},
        "correlation_id": intent.correlation_id,
    }


@pytest.mark.django_db
def test_relay_backend_does_not_resubmit_bound_intent(relay_settings):
    intent = make_intent(external_id=str(uuid.uuid4()), status=JobIntent.Status.SUBMITTED)
    transport = FakeRelayTransport()
    client = configured_client(transport=transport)
    with patch("community_base.jobs.backends.relay.configured_client", return_value=client):
        assert get_backend().submit(intent.id) == intent.external_id
    assert transport.calls == []


@pytest.mark.django_db
def test_non_uuid_correlation_is_not_sent_to_relay(relay_settings):
    intent = make_intent(correlation_id="request-correlation")
    transport = FakeRelayTransport()
    configured_client(transport=transport).submit_webhook(intent)
    request = next(iter(transport.tasks.values()))["request"]
    assert "correlation_id" not in request


def test_relay_timeout_is_safe_and_retryable(relay_settings):
    transport = FakeRelayTransport()
    transport.next_response = requests.Timeout("credential-canary")
    client = configured_client(transport=transport)
    with pytest.raises(RelayError) as captured:
        client.health()
    assert captured.value.code == "relay_unavailable"
    assert captured.value.retryable
    assert "credential-canary" not in str(captured.value)


@pytest.mark.parametrize("status, retryable", [(400, False), (429, True), (503, True)])
def test_relay_http_errors_are_classified_without_response_body(relay_settings, status, retryable):
    transport = FakeRelayTransport()
    transport.next_response = FakeResponse(status, {"secret": "response-canary"})
    client = configured_client(transport=transport)
    with pytest.raises(RelayError) as captured:
        client.health()
    assert captured.value.status == status
    assert captured.value.retryable is retryable
    assert "response-canary" not in str(captured.value)


def test_malformed_success_response_is_rejected(relay_settings):
    transport = FakeRelayTransport()
    transport.next_response = FakeResponse(200, ValueError("bad json"))
    with pytest.raises(RelayError, match="malformed_relay_response"):
        configured_client(transport=transport).health()


def test_relay_client_requires_explicit_configuration(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "RELAY_BASE_URL": "",
        "RELAY_API_KEY": "",
    }
    with pytest.raises(ImproperlyConfigured):
        configured_client()
