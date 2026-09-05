from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from community_base.jobs.backends import get_backend
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import get_handler, validate_payload
from community_base.kernel.context import current_context

logger = logging.getLogger(__name__)
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class DispatchError(RuntimeError):
    pass


class DispatchConflict(DispatchError):
    pass


def dispatch_after_commit(
    handler: str,
    key: str,
    payload: Mapping[str, object],
    max_attempts: int = 5,
    available_at: datetime | None = None,
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> tuple[JobIntent, bool]:
    if not connections[using].in_atomic_block:
        raise DispatchError("durable dispatch requires an active transaction")
    get_handler(handler)
    normalized = validate_payload(payload)
    key_hash = hash_key(key)
    payload_hash = hash_payload(normalized)
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise DispatchError("max attempts must be an integer")
    if not 1 <= max_attempts <= 100:
        raise DispatchError("max attempts must be between 1 and 100")
    due_at = available_at or timezone.now()
    if not isinstance(due_at, datetime) or not timezone.is_aware(due_at):
        raise DispatchError("available_at must be timezone-aware")
    context = current_context()
    intent, created = JobIntent.objects.using(using).get_or_create(
        key_hash=key_hash,
        defaults={
            "handler": handler,
            "payload": normalized,
            "payload_hash": payload_hash,
            "max_attempts": max_attempts,
            "available_at": due_at,
            "correlation_id": context.correlation_id or "",
        },
    )
    if not created:
        immutable = (intent.handler, intent.payload_hash, intent.max_attempts)
        supplied = (handler, payload_hash, max_attempts)
        if immutable != supplied:
            raise DispatchConflict("deduplication key conflicts with an existing durable job")
        return intent, False
    if due_at <= timezone.now():
        transaction.on_commit(
            lambda: _best_effort_submit(intent.id),
            using=using,
            robust=True,
        )
    return intent, True


def _best_effort_submit(intent_id) -> bool:
    try:
        get_backend().submit(intent_id)
    except Exception:
        logger.warning("durable_job_submit_failed", extra={"job_intent_id": str(intent_id)})
        return False
    return True


def hash_key(raw_key: str) -> str:
    if not isinstance(raw_key, str) or not KEY_PATTERN.fullmatch(raw_key):
        raise DispatchError("invalid durable job deduplication key")
    return hashlib.sha256(f"community-base-job-key-v1\0{raw_key}".encode()).hexdigest()


def hash_payload(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()
