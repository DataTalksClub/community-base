from __future__ import annotations

from django.utils import timezone

from community_base.jobs.models import JobIntent
from community_base.jobs.registry import RegistryError, handler_definition
from community_base.jobs.relay import RelayClient, configured_client
from community_base.jobs.runner import complete_job, fail_job, validate_error_code


def complete_chunked_job(
    intent_id,
    lease_token,
    *,
    client: RelayClient | None = None,
) -> bool:
    intent = _active_chunked_intent(intent_id, lease_token)
    if intent is None:
        return False
    (client or configured_client()).complete_task(intent.external_id)
    return complete_job(intent.id, lease_token)


def fail_chunked_job(
    intent_id,
    lease_token,
    *,
    error_code: str,
    retryable: bool,
    client: RelayClient | None = None,
) -> bool:
    error_code = validate_error_code(error_code)
    intent = _active_chunked_intent(intent_id, lease_token)
    if intent is None:
        return False
    (client or configured_client()).fail_task(
        intent.external_id,
        error_code,
        retryable=retryable,
    )
    return fail_job(
        intent.id,
        lease_token,
        error_code=error_code,
        retryable=retryable,
    )


def _active_chunked_intent(intent_id, lease_token) -> JobIntent | None:
    intent = (
        JobIntent.objects.filter(
            id=intent_id,
            status=JobIntent.Status.RUNNING,
            lease_token=lease_token,
            lease_expires_at__gt=timezone.now(),
        )
        .exclude(external_id="")
        .first()
    )
    if intent is None:
        return None
    try:
        definition = handler_definition(intent.handler)
    except RegistryError:
        return None
    return intent if definition.chunked else None
