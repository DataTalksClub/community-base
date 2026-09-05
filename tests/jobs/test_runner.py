import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler
from community_base.jobs.runner import (
    PermanentJobError,
    RetryableJobError,
    claim_job,
    complete_job,
    renew_lease,
    run_intent,
    sweep_expired_jobs,
)
from community_base.kernel.context import current_context

OBSERVED = []


@register_handler("tests.runner.complete")
def completes(context: JobContext, payload: JobPayload):
    OBSERVED.append((context, current_context(), payload))


@register_handler("tests.runner.retry")
def retries(context: JobContext, payload: JobPayload):
    del context, payload
    raise RetryableJobError("temporary_failure")


@register_handler("tests.runner.permanent")
def dies(context: JobContext, payload: JobPayload):
    del context, payload
    raise PermanentJobError("invalid_target")


@register_handler("tests.runner.unexpected")
def crashes(context: JobContext, payload: JobPayload):
    del context, payload
    raise RuntimeError("credential-canary")


@pytest.fixture(autouse=True)
def clear_observed():
    OBSERVED.clear()


def make_intent(handler="tests.runner.complete", *, max_attempts=3):
    return JobIntent.objects.create(
        handler=handler,
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        payload={"record_id": 1},
        payload_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        max_attempts=max_attempts,
        available_at=timezone.now(),
        correlation_id="correlation-456",
    )


@pytest.mark.django_db
def test_active_lease_is_exclusive_and_token_fences_completion():
    intent = make_intent()
    first = claim_job(intent.id, worker_id="worker-one")
    assert first is not None
    assert claim_job(intent.id, worker_id="worker-two") is None
    assert not renew_lease(intent.id, uuid.uuid4())
    assert not complete_job(intent.id, uuid.uuid4())
    assert renew_lease(intent.id, first.lease_token)
    assert complete_job(intent.id, first.lease_token)
    assert not complete_job(intent.id, first.lease_token)


@pytest.mark.django_db
def test_successful_handler_runs_once_with_bound_context():
    intent = make_intent()
    assert run_intent(intent.id, worker_id="worker-one") == "succeeded"
    assert run_intent(intent.id, worker_id="worker-two") == "not_claimed"
    intent.refresh_from_db()
    context, audit_context, payload = OBSERVED.pop()
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert intent.attempts == 1
    assert context.correlation_id == "correlation-456"
    assert audit_context.correlation_id == "correlation-456"
    assert audit_context.job_id == str(intent.id)
    assert payload == {"record_id": 1}


@pytest.mark.django_db
def test_retryable_failure_schedules_bounded_retry():
    intent = make_intent("tests.runner.retry")
    before = timezone.now()
    assert run_intent(intent.id) == "failed"
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.FAILED
    assert intent.last_error == "temporary_failure"
    assert intent.available_at > before


@pytest.mark.django_db
def test_permanent_failure_is_dead_immediately():
    intent = make_intent("tests.runner.permanent")
    assert run_intent(intent.id) == "dead"
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.DEAD
    assert intent.last_error == "invalid_target"


@pytest.mark.django_db
def test_unexpected_exception_body_never_enters_state_or_logs(caplog):
    intent = make_intent("tests.runner.unexpected")
    assert run_intent(intent.id) == "failed"
    intent.refresh_from_db()
    assert intent.last_error == "handler_error"
    assert "credential-canary" not in repr(intent.__dict__)
    assert "credential-canary" not in caplog.text


@pytest.mark.django_db
def test_expired_lease_is_recovered_and_old_worker_is_fenced():
    intent = make_intent()
    first = claim_job(intent.id, worker_id="worker-one")
    assert first is not None
    JobIntent.objects.filter(id=intent.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert sweep_expired_jobs() == (1, 0)
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.FAILED
    assert not complete_job(intent.id, first.lease_token)


@pytest.mark.django_db
def test_expired_final_attempt_becomes_dead():
    intent = make_intent(max_attempts=1)
    claim = claim_job(intent.id, worker_id="worker-one")
    assert claim is not None
    JobIntent.objects.filter(id=intent.id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert sweep_expired_jobs() == (0, 1)
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.DEAD
    assert intent.last_error == "lease_expired"
