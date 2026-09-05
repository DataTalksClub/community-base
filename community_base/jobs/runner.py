from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, RegistryError, handler_definition
from community_base.kernel.context import context_scope

logger = logging.getLogger(__name__)
WORKER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ERROR_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
DEFAULT_LEASE_SECONDS = 300
MIN_LEASE_SECONDS = 5
MAX_LEASE_SECONDS = 3_600
MAX_BACKOFF_SECONDS = 3_600


class JobExecutionError(RuntimeError):
    pass


class RetryableJobError(JobExecutionError):
    def __init__(self, code: str = "retryable_error"):
        self.code = validate_error_code(code)
        super().__init__(self.code)


class PermanentJobError(JobExecutionError):
    def __init__(self, code: str = "permanent_error"):
        self.code = validate_error_code(code)
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JobClaim:
    job_id: uuid.UUID
    handler: str
    payload: dict
    correlation_id: str | None
    external_id: str | None
    attempt: int
    worker_id: str
    lease_token: uuid.UUID


def claim_job(
    intent_id,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    using: str = DEFAULT_DB_ALIAS,
) -> JobClaim | None:
    worker_id = _validate_worker(worker_id)
    lease_seconds = _validate_lease_seconds(lease_seconds)
    now = timezone.now()
    intent = (
        JobIntent.objects.using(using)
        .filter(
            id=intent_id,
            status__in=JobIntent.CLAIMABLE_STATUSES,
            available_at__lte=now,
            lease_token__isnull=True,
        )
        .first()
    )
    if intent is None:
        return None
    if intent.attempts >= intent.max_attempts:
        JobIntent.objects.using(using).filter(
            id=intent.id,
            status=intent.status,
            attempts=intent.attempts,
        ).update(status=JobIntent.Status.DEAD, last_error="attempts_exhausted")
        return None
    lease_token = uuid.uuid4()
    next_attempt = intent.attempts + 1
    updated = (
        JobIntent.objects.using(using)
        .filter(
            id=intent.id,
            status=intent.status,
            attempts=intent.attempts,
            available_at=intent.available_at,
            lease_token__isnull=True,
        )
        .update(
            status=JobIntent.Status.RUNNING,
            attempts=next_attempt,
            lease_token=lease_token,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            last_error="",
            updated_at=now,
        )
    )
    if updated != 1:
        return None
    return JobClaim(
        job_id=intent.id,
        handler=intent.handler,
        payload=intent.payload,
        correlation_id=intent.correlation_id or None,
        external_id=intent.external_id or None,
        attempt=next_attempt,
        worker_id=worker_id,
        lease_token=lease_token,
    )


def renew_lease(
    intent_id,
    lease_token,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    using: str = DEFAULT_DB_ALIAS,
) -> bool:
    duration = _validate_lease_seconds(lease_seconds)
    now = timezone.now()
    updated = (
        JobIntent.objects.using(using)
        .filter(
            id=intent_id,
            status=JobIntent.Status.RUNNING,
            lease_token=lease_token,
            lease_expires_at__gt=now,
        )
        .update(lease_expires_at=now + timedelta(seconds=duration), updated_at=now)
    )
    return updated == 1


def complete_job(intent_id, lease_token, *, using: str = DEFAULT_DB_ALIAS) -> bool:
    now = timezone.now()
    updated = (
        JobIntent.objects.using(using)
        .filter(
            id=intent_id,
            status=JobIntent.Status.RUNNING,
            lease_token=lease_token,
            lease_expires_at__gt=now,
        )
        .update(
            status=JobIntent.Status.SUCCEEDED,
            lease_token=None,
            lease_expires_at=None,
            last_error="",
            updated_at=now,
        )
    )
    return updated == 1


def fail_job(
    intent_id,
    lease_token,
    *,
    error_code: str,
    retryable: bool,
    using: str = DEFAULT_DB_ALIAS,
) -> bool:
    error_code = validate_error_code(error_code)
    now = timezone.now()
    intent = (
        JobIntent.objects.using(using)
        .filter(
            id=intent_id,
            status=JobIntent.Status.RUNNING,
            lease_token=lease_token,
            lease_expires_at__gt=now,
        )
        .first()
    )
    if intent is None:
        return False
    will_retry = retryable and intent.attempts < intent.max_attempts
    updated = (
        JobIntent.objects.using(using)
        .filter(
            id=intent.id,
            status=JobIntent.Status.RUNNING,
            lease_token=lease_token,
            attempts=intent.attempts,
            lease_expires_at__gt=now,
        )
        .update(
            status=JobIntent.Status.FAILED if will_retry else JobIntent.Status.DEAD,
            available_at=now + retry_backoff(intent.attempts)
            if will_retry
            else intent.available_at,
            lease_token=None,
            lease_expires_at=None,
            last_error=error_code,
            updated_at=now,
        )
    )
    return updated == 1


def sweep_expired_jobs(*, limit: int = 100, using: str = DEFAULT_DB_ALIAS) -> tuple[int, int]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise JobExecutionError("sweep limit must be between 1 and 1000")
    now = timezone.now()
    recovered = dead = 0
    expired = list(
        JobIntent.objects.using(using)
        .filter(status=JobIntent.Status.RUNNING, lease_expires_at__lte=now)
        .order_by("lease_expires_at", "id")[:limit]
    )
    for intent in expired:
        retryable = intent.attempts < intent.max_attempts
        updated = (
            JobIntent.objects.using(using)
            .filter(
                id=intent.id,
                status=JobIntent.Status.RUNNING,
                lease_token=intent.lease_token,
                lease_expires_at=intent.lease_expires_at,
                attempts=intent.attempts,
            )
            .update(
                status=JobIntent.Status.FAILED if retryable else JobIntent.Status.DEAD,
                available_at=now + retry_backoff(intent.attempts)
                if retryable
                else intent.available_at,
                lease_token=None,
                lease_expires_at=None,
                last_error="lease_expired",
                updated_at=now,
            )
        )
        if updated:
            recovered += int(retryable)
            dead += int(not retryable)
    return recovered, dead


def run_intent(
    intent_id,
    *,
    worker_id: str = "worker",
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    using: str = DEFAULT_DB_ALIAS,
) -> str:
    claim = claim_job(
        intent_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        using=using,
    )
    if claim is None:
        return "not_claimed"
    try:
        definition = handler_definition(claim.handler)
    except RegistryError:
        fail_job(
            claim.job_id,
            claim.lease_token,
            error_code="unknown_handler",
            retryable=False,
            using=using,
        )
        return "dead"
    context = JobContext(
        job_id=claim.job_id,
        correlation_id=claim.correlation_id,
        attempt=claim.attempt,
        worker_id=claim.worker_id,
        lease_token=claim.lease_token,
    )
    try:
        with context_scope(correlation_id=claim.correlation_id, job_id=str(claim.job_id)):
            definition.callback(context, claim.payload)
    except PermanentJobError as error:
        fail_job(
            claim.job_id,
            claim.lease_token,
            error_code=error.code,
            retryable=False,
            using=using,
        )
        return "dead"
    except RetryableJobError as error:
        failed = fail_job(
            claim.job_id,
            claim.lease_token,
            error_code=error.code,
            retryable=True,
            using=using,
        )
        return _failure_result(claim.job_id, failed, using=using)
    except Exception:
        failed = fail_job(
            claim.job_id,
            claim.lease_token,
            error_code="handler_error",
            retryable=True,
            using=using,
        )
        logger.warning(
            "durable_job_handler_failed",
            extra={"job_intent_id": str(claim.job_id), "handler": claim.handler},
        )
        return _failure_result(claim.job_id, failed, using=using)
    if definition.chunked and claim.external_id:
        return "accepted"
    return (
        "succeeded" if complete_job(claim.job_id, claim.lease_token, using=using) else "lease_lost"
    )


def retry_backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(MAX_BACKOFF_SECONDS, 5 * (2 ** max(0, attempt - 1))))


def _failure_result(intent_id, updated: bool, *, using: str) -> str:
    if not updated:
        return "lease_lost"
    status = (
        JobIntent.objects.using(using).filter(id=intent_id).values_list("status", flat=True).get()
    )
    return "dead" if status == JobIntent.Status.DEAD else "failed"


def _validate_worker(worker_id: str) -> str:
    if not isinstance(worker_id, str) or not WORKER_PATTERN.fullmatch(worker_id):
        raise JobExecutionError("invalid durable worker id")
    return worker_id


def _validate_lease_seconds(seconds: int) -> int:
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        raise JobExecutionError("lease duration must be an integer")
    if not MIN_LEASE_SECONDS <= seconds <= MAX_LEASE_SECONDS:
        raise JobExecutionError("lease duration is outside the safe range")
    return seconds


def validate_error_code(code: str) -> str:
    if not isinstance(code, str) or not ERROR_PATTERN.fullmatch(code):
        raise JobExecutionError("invalid durable job error code")
    return code
