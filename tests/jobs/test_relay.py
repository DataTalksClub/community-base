import uuid
from unittest.mock import patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.utils import timezone

from community_base.jobs.backends import get_backend
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler, schedule
from community_base.jobs.relay import RelayError, configured_client
from community_base.jobs.relay_scheduling import sync_relay_schedules
from tests.jobs.fake_relay import FakeRelayTransport, FakeResponse


@register_handler("tests.relay.scheduled")
def scheduled_handler(context: JobContext, payload: JobPayload):
    del context, payload


schedule(
    "tests.relay.scheduled",
    "23 * * * *",
    {"record_id": 23},
    name="tests.relay.hourly",
)


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


def test_relay_schedule_sync_creates_updates_deletes_and_is_idempotent(relay_settings):
    transport = FakeRelayTransport()
    client = configured_client(transport=transport)
    unmanaged = client.upsert_schedule(
        {
            "name": "owned-by-another-integration",
            "cron": "0 0 * * *",
            "type": "webhook",
            "url": "https://community.example.com/other",
            "params": {},
        }
    )
    stale = client.upsert_schedule(
        {
            "name": "community-base:test-site:removed",
            "cron": "0 0 * * *",
            "type": "webhook",
            "url": "https://community.example.com/internal/jobs/run",
            "params": {"schedule_name": "removed"},
        }
    )

    first = sync_relay_schedules(client)

    assert ("create", "community-base:test-site:tests.relay.hourly", None) in first
    assert ("delete", stale.name, stale.id) in first
    assert transport.schedules[stale.id]["enabled"] is False
    assert transport.schedules[unmanaged.id]["enabled"] is True

    managed = next(
        row
        for row in transport.schedules.values()
        if row["name"] == "community-base:test-site:tests.relay.hourly"
    )
    managed["cron"] = "0 0 * * *"
    second = sync_relay_schedules(client)
    assert (
        "update",
        "community-base:test-site:tests.relay.hourly",
        managed["id"],
    ) in second
    assert all(action in {"unchanged", "update"} for action, _name, _id in second)

    mutation_count = len([call for call in transport.calls if call[0] in {"POST", "DELETE"}])
    third = sync_relay_schedules(client)
    assert (
        "unchanged",
        "community-base:test-site:tests.relay.hourly",
        managed["id"],
    ) in third
    assert all(action == "unchanged" for action, _name, _id in third)
    final_mutation_count = len([call for call in transport.calls if call[0] in {"POST", "DELETE"}])
    assert final_mutation_count == mutation_count


def test_relay_schedule_dry_run_makes_no_changes(relay_settings):
    transport = FakeRelayTransport()
    client = configured_client(transport=transport)
    changes = sync_relay_schedules(client, dry_run=True)
    assert ("create", "community-base:test-site:tests.relay.hourly", None) in changes
    assert all(action == "create" for action, _name, _id in changes)
    assert transport.schedules == {}


def test_sync_relay_schedules_command_reports_dry_run(relay_settings, capsys):
    transport = FakeRelayTransport()
    client = configured_client(transport=transport)
    with patch(
        "community_base.jobs.management.commands.sync_relay_schedules.configured_client",
        return_value=client,
    ):
        call_command("sync_relay_schedules", "--dry-run")
    assert "create: community-base:test-site:tests.relay.hourly" in capsys.readouterr().out
    assert transport.schedules == {}


@pytest.mark.django_db
def test_fake_relay_webhook_lifecycle_reaches_succeeded(relay_settings, client, settings):
    intent = make_intent()
    transport = FakeRelayTransport()
    relay_client = configured_client(transport=transport)
    with patch("community_base.jobs.backends.relay.configured_client", return_value=relay_client):
        task_id = get_backend().submit(intent.id)

    assert transport.tasks[task_id]["status"] == "queued"
    response = transport.deliver(
        task_id,
        client,
        settings.COMMUNITY_BASE["RELAY_WEBHOOK_SECRET"],
    )
    intent.refresh_from_db()
    assert response.status_code == 200
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert transport.tasks[task_id]["status"] == "succeeded"
