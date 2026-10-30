from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import get
from community_base.kernel.context import is_safe_external_context_id
from community_base.kernel.relay import (
    DEFAULT_TIMEOUT_SECONDS as DEFAULT_TIMEOUT_SECONDS,
)
from community_base.kernel.relay import (
    RETRYABLE_HTTP_STATUSES as RETRYABLE_HTTP_STATUSES,
)
from community_base.kernel.relay import (
    RelayClientBase,
    Transport,
    _absolute_http_url,
)
from community_base.kernel.relay import (
    RequestsTransport as RequestsTransport,
)

TASK_STATUSES = frozenset({"queued", "running", "retrying", "succeeded", "failed", "cancelled"})


class RelayError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, status: int | None = None):
        self.code = code
        self.retryable = retryable
        self.status = status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RelaySchedule:
    id: str
    name: str
    cron: str
    task_type: str
    task: dict
    enabled: bool
    next_run_at: str | None
    last_run_at: str | None
    last_success_at: str | None


class RelayClient(RelayClientBase):
    error_class = RelayError

    def _timeout_error(self) -> RelayError:
        return RelayError("relay_unavailable", retryable=True)

    def submit_webhook(self, intent) -> dict:
        site_key = get("SITE_KEY")
        if not isinstance(site_key, str) or not site_key:
            raise ImproperlyConfigured("SITE_KEY must be configured for Relay jobs")
        site_url = _absolute_http_url(get("SITE_URL"), "SITE_URL").rstrip("/")
        payload = {
            "type": "webhook",
            "url": f"{site_url}/internal/jobs/run",
            "idempotency_key": f"{site_key}:{intent.key_hash}",
            "params": {"intent_id": str(intent.id)},
        }
        try:
            payload["correlation_id"] = str(uuid.UUID(intent.correlation_id))
        except (ValueError, AttributeError):
            pass
        document = self._request("POST", "/api/tasks", payload, expected={200, 202})
        task_id = document.get("id")
        if not is_safe_external_context_id(task_id):
            raise RelayError("malformed_task_response")
        status = document.get("status")
        if status not in TASK_STATUSES:
            raise RelayError("malformed_task_response")
        return document

    def task(self, task_id: str) -> dict:
        _validate_remote_id(task_id)
        document = self._request("GET", f"/api/tasks/{task_id}", expected={200})
        if document.get("id") != task_id or document.get("status") not in TASK_STATUSES:
            raise RelayError("malformed_task_response")
        return document

    def tasks(self) -> tuple[dict, ...]:
        document = self._request("GET", "/api/tasks", expected={200})
        rows = document.get("tasks")
        if not isinstance(rows, list):
            raise RelayError("malformed_task_response")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise RelayError("malformed_task_response")
            _validate_remote_id(row.get("id"))
            if row.get("status") not in TASK_STATUSES:
                raise RelayError("malformed_task_response")
            result.append(row)
        return tuple(result)

    def complete_task(self, task_id: str) -> dict:
        _validate_remote_id(task_id)
        document = self._request("POST", f"/api/tasks/{task_id}/complete", {}, expected={200, 202})
        return _validate_task_transition(document, task_id, {"succeeded"})

    def fail_task(self, task_id: str, error_code: str, *, retryable: bool) -> dict:
        _validate_remote_id(task_id)
        document = self._request(
            "POST",
            f"/api/tasks/{task_id}/fail",
            {"error": error_code, "retryable": retryable},
            expected={200, 202},
        )
        expected = {"retrying"} if retryable else {"failed"}
        return _validate_task_transition(document, task_id, expected)

    def schedules(self) -> tuple[RelaySchedule, ...]:
        document = self._request("GET", "/api/schedules", expected={200})
        rows = document.get("schedules")
        if not isinstance(rows, list):
            raise RelayError("malformed_schedule_response")
        return tuple(_parse_schedule(row) for row in rows)

    def upsert_schedule(self, payload: dict) -> RelaySchedule:
        document = self._request("POST", "/api/schedules", payload, expected={200, 201})
        return _parse_schedule(document)

    def delete_schedule(self, schedule_id: str) -> RelaySchedule:
        _validate_remote_id(schedule_id)
        document = self._request("DELETE", f"/api/schedules/{schedule_id}", expected={200})
        schedule = _parse_schedule(document)
        if schedule.enabled:
            raise RelayError("malformed_schedule_response")
        return schedule

    def health(self) -> dict:
        document = self._request("GET", "/health/ready", expected={200})
        if document.get("status") != "ready":
            raise RelayError("relay_not_ready", retryable=True)
        return document


def configured_client(*, transport: Transport | None = None) -> RelayClient:
    return RelayClient(get("RELAY_BASE_URL"), get("RELAY_API_KEY"), transport=transport)


def _parse_schedule(document) -> RelaySchedule:
    if not isinstance(document, dict):
        raise RelayError("malformed_schedule_response")
    required_strings = ("id", "name", "cron", "type")
    if any(not isinstance(document.get(key), str) or not document[key] for key in required_strings):
        raise RelayError("malformed_schedule_response")
    _validate_remote_id(document["id"])
    if not isinstance(document.get("task"), dict) or not isinstance(document.get("enabled"), bool):
        raise RelayError("malformed_schedule_response")
    return RelaySchedule(
        id=document["id"],
        name=document["name"],
        cron=document["cron"],
        task_type=document["type"],
        task=document["task"],
        enabled=document["enabled"],
        next_run_at=_optional_string(document.get("next_run_at")),
        last_run_at=_optional_string(document.get("last_run_at")),
        last_success_at=_optional_string(document.get("last_success_at")),
    )


def _optional_string(value) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise RelayError("malformed_schedule_response")


def _validate_remote_id(value: str) -> str:
    if not is_safe_external_context_id(value):
        raise RelayError("invalid_remote_id")
    return value


def _validate_task_transition(document: dict, task_id: str, statuses: set[str]) -> dict:
    if document.get("id") != task_id or document.get("status") not in statuses:
        raise RelayError("malformed_task_response")
    return document
