from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import requests
from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import get
from community_base.kernel.context import is_safe_external_context_id

DEFAULT_TIMEOUT_SECONDS = 15
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429})
TASK_STATUSES = frozenset({"queued", "running", "retrying", "succeeded", "failed", "cancelled"})


class RelayError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, status: int | None = None):
        self.code = code
        self.retryable = retryable
        self.status = status
        super().__init__(code)


class Transport(Protocol):
    def request(self, method: str, url: str, **kwargs): ...


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


class RequestsTransport:
    def __init__(self):
        self.session = requests.Session()

    def request(self, method: str, url: str, **kwargs):
        return self.session.request(method, url, **kwargs)


class RelayClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: Transport | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = _absolute_http_url(base_url, "RELAY_BASE_URL").rstrip("/")
        if not isinstance(api_key, str) or not api_key:
            raise ImproperlyConfigured("RELAY_API_KEY must be configured")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
            raise ImproperlyConfigured("Relay timeout must be an integer")
        if not 1 <= timeout_seconds <= 60:
            raise ImproperlyConfigured("Relay timeout must be between 1 and 60 seconds")
        self.api_key = api_key
        self.transport = transport or RequestsTransport()
        self.timeout_seconds = timeout_seconds

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

    def complete_task(self, task_id: str) -> dict:
        _validate_remote_id(task_id)
        return self._request("POST", f"/api/tasks/{task_id}/complete", {}, expected={200, 202})

    def fail_task(self, task_id: str, error_code: str) -> dict:
        _validate_remote_id(task_id)
        return self._request(
            "POST",
            f"/api/tasks/{task_id}/fail",
            {"error": error_code},
            expected={200, 202},
        )

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

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        expected: set[int],
    ) -> dict:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self.transport.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            raise RelayError("relay_unavailable", retryable=True) from error
        except requests.RequestException as error:
            raise RelayError("relay_transport_error", retryable=True) from error
        status = getattr(response, "status_code", None)
        if status not in expected:
            retryable = status in RETRYABLE_HTTP_STATUSES or (
                isinstance(status, int) and status >= 500
            )
            raise RelayError("relay_http_error", retryable=retryable, status=status)
        try:
            document = response.json()
        except (TypeError, ValueError) as error:
            raise RelayError("malformed_relay_response") from error
        if not isinstance(document, dict):
            raise RelayError("malformed_relay_response")
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


def _absolute_http_url(value, setting_name: str) -> str:
    if not isinstance(value, str):
        raise ImproperlyConfigured(f"{setting_name} must be an absolute HTTP URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ImproperlyConfigured(f"{setting_name} must be an absolute HTTP URL")
    return value
