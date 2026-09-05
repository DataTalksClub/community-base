import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from community_base.jobs.ingress import sign_body
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler

OBSERVED = []
SECRET = "test-relay-webhook-secret"


@register_handler("tests.ingress.complete")
def complete_handler(context: JobContext, payload: JobPayload):
    OBSERVED.append((context.correlation_id, payload))


@register_handler("tests.ingress.chunked", chunked=True)
def chunked_handler(context: JobContext, payload: JobPayload):
    OBSERVED.append((context.correlation_id, payload))


@pytest.fixture(autouse=True)
def clear_observed():
    OBSERVED.clear()


def make_intent(handler="tests.ingress.complete", **overrides):
    values = {
        "handler": handler,
        "key_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "payload": {"record_id": 7},
        "payload_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "available_at": timezone.now(),
    }
    values.update(overrides)
    return JobIntent.objects.create(**values)


def signed_request(client, intent_id, *, task_id=None, timestamp=None, body=None, signature=None):
    task_id = task_id or str(uuid.uuid4())
    timestamp = timestamp or str(int(timezone.now().timestamp()))
    body = body or json.dumps(
        {"intent_id": str(intent_id)}, sort_keys=True, separators=(",", ":")
    ).encode()
    signature = signature or sign_body(body, timestamp, SECRET)
    return client.post(
        "/internal/jobs/run",
        data=body,
        content_type="application/json",
        headers={
            "X-Relay-Task-Id": task_id,
            "X-Relay-Correlation-Id": "relay-correlation-1",
            "X-Relay-Timestamp": timestamp,
            "X-Relay-Signature": signature,
        },
    )


@pytest.mark.django_db
def test_signed_ingress_runs_intent_and_records_relay_task(client):
    intent = make_intent()

    response = signed_request(client, intent.id)

    intent.refresh_from_db()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "result": "succeeded"}
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert intent.external_id
    assert intent.correlation_id == "relay-correlation-1"
    assert OBSERVED == [("relay-correlation-1", {"record_id": 7})]


@pytest.mark.django_db
def test_signature_is_checked_before_payload(client):
    intent = make_intent()
    response = signed_request(client, intent.id, body=b"not-json", signature="sha256=invalid")
    assert response.status_code == 401
    assert response.json() == {"error": "invalid_signature"}


@pytest.mark.django_db
def test_tampered_body_is_rejected(client):
    intent = make_intent()
    original = json.dumps({"intent_id": str(intent.id)}).encode()
    signature = sign_body(original, str(int(timezone.now().timestamp())), SECRET)
    response = signed_request(
        client,
        intent.id,
        body=b'{"intent_id":"tampered"}',
        signature=signature,
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_stale_timestamp_is_rejected(client):
    intent = make_intent()
    stale = str(int((timezone.now() - timedelta(minutes=6)).timestamp()))
    response = signed_request(client, intent.id, timestamp=stale)
    assert response.status_code == 401
    assert response.json() == {"error": "stale_signature"}


@pytest.mark.django_db
def test_unknown_intent_is_rejected(client):
    response = signed_request(client, uuid.uuid4())
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_intent"}


@pytest.mark.django_db
def test_relay_task_replay_is_rejected(client):
    task_id = str(uuid.uuid4())
    first = make_intent()
    second = make_intent()
    assert signed_request(client, first.id, task_id=task_id).status_code == 200

    response = signed_request(client, second.id, task_id=task_id)

    assert response.status_code == 409
    assert response.json() == {"error": "replayed_task"}
    assert OBSERVED == [("relay-correlation-1", {"record_id": 7})]


@pytest.mark.django_db
def test_intent_cannot_be_bound_to_two_relay_tasks(client):
    intent = make_intent()
    assert signed_request(client, intent.id).status_code == 200
    response = signed_request(client, intent.id)
    assert response.status_code == 409


@pytest.mark.django_db
def test_chunked_handler_returns_lease_duration(client):
    intent = make_intent("tests.ingress.chunked")
    response = signed_request(client, intent.id)
    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "result": "succeeded",
        "lease_seconds": 300,
    }


@pytest.mark.django_db
def test_missing_webhook_secret_disables_ingress(client, settings):
    settings.COMMUNITY_BASE["RELAY_WEBHOOK_SECRET"] = ""
    intent = make_intent()
    response = signed_request(client, intent.id)
    assert response.status_code == 503
    assert response.json() == {"error": "ingress_not_configured"}
