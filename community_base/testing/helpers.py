from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.test import override_settings
from django.utils import timezone

from community_base.jobs.ingress import sign_body
from community_base.mail.backends.memory import outbox


@contextmanager
def sync_jobs():
    """Run dispatched jobs synchronously inside this context."""

    from django.conf import settings

    configured = {**getattr(settings, "COMMUNITY_BASE", {}), "JOBS_BACKEND": "sync"}
    with override_settings(COMMUNITY_BASE=configured):
        yield


@contextmanager
def mail_outbox():
    """Select memory mail and yield an isolated outbox list."""

    from django.conf import settings

    configured = {**getattr(settings, "COMMUNITY_BASE", {}), "MAIL_BACKEND": "memory"}
    outbox.clear()
    try:
        with override_settings(COMMUNITY_BASE=configured):
            yield outbox
    finally:
        outbox.clear()


@dataclass(frozen=True, slots=True)
class SignedRelayRequest:
    body: bytes
    headers: dict[str, str]

    def django_kwargs(self) -> dict[str, Any]:
        return {
            "data": self.body,
            "content_type": "application/json",
            "headers": self.headers,
        }

    def post(self, client, path: str):
        """Submit this request through a Django test client."""

        return client.post(path, **self.django_kwargs())


def signed_relay_request(
    payload: object,
    secret: str,
    *,
    timestamp: str | None = None,
    task_id: str | None = None,
    correlation_id: str | None = None,
) -> SignedRelayRequest:
    """Serialize a payload canonically and add Relay HMAC headers."""

    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = timestamp or str(int(timezone.now().timestamp()))
    headers = {
        "X-Relay-Timestamp": timestamp,
        "X-Relay-Signature": sign_body(body, timestamp, secret),
    }
    if task_id is not None:
        headers["X-Relay-Task-Id"] = task_id
        headers["X-Relay-Correlation-Id"] = correlation_id or str(uuid.uuid4())
    return SignedRelayRequest(body, headers)
