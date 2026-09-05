import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler, schedule
from community_base.jobs.relay import configured_client
from community_base.jobs.runner import claim_job, complete_job
from tests.jobs.fake_relay import FakeRelayTransport


@register_handler("tests.studio.complete")
def complete_handler(context: JobContext, payload: JobPayload):
    del context, payload


schedule(
    "tests.studio.complete",
    "17 * * * *",
    {},
    name="tests.studio.hourly",
)


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(username="jobs-staff", is_staff=True)


def make_intent(status=JobIntent.Status.PENDING, *, handler="tests.studio.complete"):
    attempts = 3 if status == JobIntent.Status.DEAD else 0
    return JobIntent.objects.create(
        handler=handler,
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        payload={"record_id": 1},
        payload_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=status,
        attempts=attempts,
        max_attempts=3,
        available_at=timezone.now(),
        last_error=(
            "test_error" if status in {JobIntent.Status.FAILED, JobIntent.Status.DEAD} else ""
        ),
    )


@pytest.mark.django_db
def test_jobs_studio_requires_staff(client):
    user = get_user_model().objects.create_user(username="jobs-member")
    client.force_login(user)
    assert client.get(reverse("community_base_jobs")).status_code == 403


@pytest.mark.django_db
def test_jobs_studio_lists_work_without_rendering_payload(client, staff_user):
    intent = make_intent(JobIntent.Status.FAILED)
    client.force_login(staff_user)
    response = client.get(reverse("community_base_jobs"))
    assert response.status_code == 200
    assert str(intent.id).encode() in response.content
    assert b"tests.studio.hourly" in response.content
    assert b"record_id" not in response.content
    assert "no-cache" in response.headers["Cache-Control"]


@pytest.mark.django_db(transaction=True)
def test_retry_requires_confirmation_then_runs_with_sync_backend(client, staff_user):
    intent = make_intent(JobIntent.Status.DEAD)
    client.force_login(staff_user)
    url = reverse("community_base_job_retry", args=(intent.id,))
    assert client.post(url, {"confirmation": "no"}).status_code == 302
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.DEAD

    assert client.post(url, {"confirmation": "retry"}).status_code == 302
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert intent.attempts == 1
    assert intent.last_error == ""


@pytest.mark.django_db
def test_discard_fences_a_running_worker(client, staff_user):
    intent = make_intent()
    claim = claim_job(intent.id, worker_id="studio-test")
    assert claim is not None
    client.force_login(staff_user)
    response = client.post(
        reverse("community_base_job_discard", args=(intent.id,)),
        {"confirmation": "discard"},
    )
    assert response.status_code == 302
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.DEAD
    assert intent.last_error == "discarded_by_operator"
    assert not complete_job(intent.id, claim.lease_token)


@pytest.mark.django_db
def test_studio_actions_reject_get(client, staff_user):
    intent = make_intent(JobIntent.Status.FAILED)
    client.force_login(staff_user)
    assert client.get(reverse("community_base_job_retry", args=(intent.id,))).status_code == 405
    assert client.get(reverse("community_base_job_discard", args=(intent.id,))).status_code == 405


@pytest.mark.django_db
def test_jobs_studio_projects_relay_health_and_schedule_times(client, staff_user, settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "JOBS_BACKEND": "relay",
        "SITE_KEY": "test",
        "SITE_URL": "https://community.example.com",
        "RELAY_BASE_URL": "https://relay.example.com",
        "RELAY_API_KEY": "relay-test-key",
    }
    transport = FakeRelayTransport()
    relay_client = configured_client(transport=transport)
    relay_client.upsert_schedule(
        {
            "name": "community-base:test:tests.studio.hourly",
            "cron": "17 * * * *",
            "type": "webhook",
            "url": "https://community.example.com/internal/jobs/run",
            "params": {"schedule_name": "tests.studio.hourly"},
        }
    )
    transport._submit_task(
        {
            "type": "webhook",
            "idempotency_key": "health-task",
            "url": "https://community.example.com/internal/jobs/run",
            "params": {"intent_id": str(uuid.uuid4())},
        }
    )
    client.force_login(staff_user)
    with patch("community_base.jobs.studio.configured_client", return_value=relay_client):
        response = client.get(reverse("community_base_jobs"))
    assert response.status_code == 200
    assert b"Relay worker health" in response.content
    assert b"queued 1" in response.content
    assert b"2026-09-05T12:00:00+00:00" in response.content


@pytest.mark.django_db(transaction=True)
def test_relay_operator_retry_creates_new_intent_and_preserves_old_audit(
    client, staff_user, settings
):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "JOBS_BACKEND": "relay",
        "SITE_KEY": "test",
        "SITE_URL": "https://community.example.com",
        "RELAY_BASE_URL": "https://relay.example.com",
        "RELAY_API_KEY": "relay-test-key",
    }
    old = make_intent(JobIntent.Status.DEAD)
    old.external_id = str(uuid.uuid4())
    old.save(update_fields=("external_id",))
    transport = FakeRelayTransport()
    relay_client = configured_client(transport=transport)
    client.force_login(staff_user)

    with patch("community_base.jobs.backends.relay.configured_client", return_value=relay_client):
        response = client.post(
            reverse("community_base_job_retry", args=(old.id,)),
            {"confirmation": "retry"},
        )

    assert response.status_code == 302
    old.refresh_from_db()
    replacement = JobIntent.objects.exclude(id=old.id).get()
    assert old.status == JobIntent.Status.DEAD
    assert old.last_error == "retried_by_operator"
    assert replacement.status == JobIntent.Status.SUBMITTED
    assert replacement.external_id != old.external_id
    assert len(transport.tasks) == 1
