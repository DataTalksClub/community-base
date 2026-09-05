import uuid

import pytest
import requests
from django.utils import timezone

from community_base.jobs.chunked import complete_chunked_job, fail_chunked_job
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler
from community_base.jobs.relay import RelayError, configured_client
from community_base.jobs.runner import run_intent
from community_base.testing import FakeRelay, FakeResponse


@register_handler("tests.chunked.start", chunked=True)
def starts_chunked_work(context: JobContext, payload: JobPayload):
    del context, payload


@register_handler("tests.chunked.regular")
def regular_work(context: JobContext, payload: JobPayload):
    del context, payload


def make_intent(handler="tests.chunked.start"):
    task_id = str(uuid.uuid4())
    return JobIntent.objects.create(
        handler=handler,
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        payload={},
        payload_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=JobIntent.Status.SUBMITTED,
        available_at=timezone.now(),
        external_id=task_id,
    )


def relay_client_for(intent):
    transport = FakeRelay()
    transport.tasks[intent.external_id] = {
        "id": intent.external_id,
        "type": "webhook",
        "status": "running",
        "request": {},
    }
    return configured_client(transport=transport), transport


@pytest.fixture(autouse=True)
def relay_settings(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "RELAY_BASE_URL": "https://relay.example.com",
        "RELAY_API_KEY": "relay-test-key",
    }


@pytest.mark.django_db
def test_chunked_completion_updates_remote_then_completes_local_with_fence():
    intent = make_intent()
    assert run_intent(intent.id, worker_id="relay") == "accepted"
    intent.refresh_from_db()
    client, transport = relay_client_for(intent)

    assert complete_chunked_job(intent.id, intent.lease_token, client=client)

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert transport.tasks[intent.external_id]["status"] == "succeeded"


@pytest.mark.django_db
def test_stale_chunked_completion_is_fenced_before_remote_call():
    intent = make_intent()
    assert run_intent(intent.id, worker_id="relay") == "accepted"
    client, transport = relay_client_for(intent)
    before = len(transport.calls)
    assert not complete_chunked_job(intent.id, uuid.uuid4(), client=client)
    assert len(transport.calls) == before


@pytest.mark.django_db
def test_chunked_retryable_failure_updates_both_states():
    intent = make_intent()
    assert run_intent(intent.id, worker_id="relay") == "accepted"
    intent.refresh_from_db()
    client, transport = relay_client_for(intent)

    assert fail_chunked_job(
        intent.id,
        intent.lease_token,
        error_code="upstream_unavailable",
        retryable=True,
        client=client,
    )

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.FAILED
    assert transport.tasks[intent.external_id]["status"] == "retrying"


@pytest.mark.django_db
def test_remote_timeout_leaves_local_lease_for_safe_retry():
    intent = make_intent()
    assert run_intent(intent.id, worker_id="relay") == "accepted"
    intent.refresh_from_db()
    client, transport = relay_client_for(intent)
    transport.next_response = requests.Timeout("response-canary")

    with pytest.raises(RelayError, match="relay_unavailable"):
        complete_chunked_job(intent.id, intent.lease_token, client=client)

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.RUNNING
    assert intent.lease_token is not None


@pytest.mark.django_db
def test_malformed_remote_completion_leaves_local_lease():
    intent = make_intent()
    assert run_intent(intent.id, worker_id="relay") == "accepted"
    intent.refresh_from_db()
    client, transport = relay_client_for(intent)
    transport.next_response = FakeResponse(200, {"id": intent.external_id, "status": "running"})

    with pytest.raises(RelayError, match="malformed_task_response"):
        complete_chunked_job(intent.id, intent.lease_token, client=client)

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.RUNNING


@pytest.mark.django_db
def test_regular_intent_cannot_use_chunked_completion():
    intent = make_intent("tests.chunked.regular")
    assert run_intent(intent.id, worker_id="relay") == "succeeded"
    client, transport = relay_client_for(intent)
    assert not complete_chunked_job(intent.id, uuid.uuid4(), client=client)
    assert transport.calls == []
