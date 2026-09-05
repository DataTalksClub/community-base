from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

import requests
from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import get

DEFAULT_TIMEOUT_SECONDS = 15
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429})
MESSAGE_STATUSES = frozenset(
    {
        "queued",
        "provider_accepted",
        "delivered",
        "retryable",
        "ambiguous",
        "suppressed",
        "dead",
        "hard_bounced",
        "complained",
    }
)


class RelayMailError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        ambiguous: bool = False,
        suppressed: bool = False,
        reason_code: str = "",
        status: int | None = None,
    ):
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.suppressed = suppressed
        self.reason_code = reason_code
        self.status = status
        super().__init__(code)


class Transport(Protocol):
    def request(self, method: str, url: str, **kwargs): ...


class RequestsTransport:
    def __init__(self):
        self.session = requests.Session()

    def request(self, method: str, url: str, **kwargs):
        return self.session.request(method, url, **kwargs)


@dataclass(frozen=True, slots=True)
class RelaySendResult:
    message_id: str
    status: str
    template_version: int
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class RelayMessage:
    message_id: str
    client_reference: str
    status: str
    template_key: str
    template_version: int
    reason_code: str
    updated_at: str


TEMPLATE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RelayMailClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: Transport | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = _absolute_http_url(base_url).rstrip("/")
        if not isinstance(api_key, str) or not api_key:
            raise ImproperlyConfigured("RELAY_API_KEY must be configured")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
            raise ImproperlyConfigured("Relay timeout must be an integer")
        if not 1 <= timeout_seconds <= 60:
            raise ImproperlyConfigured("Relay timeout must be between 1 and 60 seconds")
        self.api_key = api_key
        self.transport = transport or RequestsTransport()
        self.timeout_seconds = timeout_seconds

    def send(self, delivery) -> RelaySendResult:
        payload = {
            "email": delivery.recipient_email,
            "template_key": delivery.template_key,
            "template_version": delivery.template_version,
            "idempotency_key": delivery.idempotency_key,
            "context": delivery.context_data,
        }
        if delivery.category:
            payload["category"] = delivery.category
        if delivery.sender_id:
            payload["sender_id"] = delivery.sender_id
        document = self._request(
            "POST",
            "/api/transactional/send",
            payload,
            expected={200, 202},
            suppression_statuses={409},
        )
        message = document.get("message")
        if not isinstance(message, dict):
            raise RelayMailError("malformed_send_response")
        raw_id = message.get("id")
        message_id = str(raw_id) if isinstance(raw_id, str | int) else ""
        status = message.get("status")
        version = message.get("template_version", delivery.template_version)
        replay = document.get("idempotent_replay")
        if (
            not message_id
            or len(message_id) > 128
            or status not in MESSAGE_STATUSES
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or not isinstance(replay, bool)
            or message.get("idempotency_key") != delivery.idempotency_key
            or message.get("template_key") != delivery.template_key
        ):
            raise RelayMailError("malformed_send_response")
        return RelaySendResult(message_id, status, version, replay)

    def messages_since(self, since: datetime) -> tuple[RelayMessage, ...]:
        if not isinstance(since, datetime) or since.tzinfo is None:
            raise ValueError("since must be a timezone-aware datetime")
        document = self._request(
            "GET",
            "/api/transactional/messages",
            expected={200},
            params={"since": since.isoformat()},
        )
        rows = document.get("messages")
        if not isinstance(rows, list):
            raise RelayMailError("malformed_messages_response")
        return tuple(_parse_message(row) for row in rows)

    def templates(self) -> tuple[dict, ...]:
        document = self._request("GET", "/api/transactional/templates", expected={200})
        rows = document.get("templates")
        if not isinstance(rows, list):
            raise RelayMailError("malformed_templates_response")
        return tuple(_parse_template(item) for item in rows)

    def template_versions(self, template_key: str) -> tuple[dict, ...]:
        key = _template_key(template_key)
        document = self._request(
            "GET", f"/api/transactional/templates/{key}/versions", expected={200}
        )
        rows = document.get("versions")
        if not isinstance(rows, list):
            raise RelayMailError("malformed_templates_response")
        return tuple(_parse_version(item, key) for item in rows)

    def put_template(self, template_key: str, draft: dict) -> dict:
        key = _template_key(template_key)
        if not isinstance(draft, dict):
            raise ValueError("template draft must be an object")
        document = self._request(
            "PUT", f"/api/transactional/templates/{key}", draft, expected={200, 201}
        )
        return _parse_template(document.get("template"))

    def publish_template(self, template_key: str) -> dict:
        key = _template_key(template_key)
        document = self._request(
            "POST", f"/api/transactional/templates/{key}/publish", {}, expected={200, 201}
        )
        return _parse_version(document.get("version"), key)

    def preview_template(
        self, template_key: str, context: dict, *, version: int | None = None
    ) -> dict:
        key = _template_key(template_key)
        payload = {"context": context}
        if version is not None:
            payload["template_version"] = _version(version)
        document = self._request(
            "POST", f"/api/transactional/templates/{key}/preview", payload, expected={200}
        )
        rendered = document.get("rendered")
        if not isinstance(rendered, dict) or any(
            not isinstance(rendered.get(field), str)
            for field in ("subject", "html_body", "text_body")
        ):
            raise RelayMailError("malformed_preview_response")
        return rendered

    def test_send_template(
        self,
        template_key: str,
        recipient: str,
        context: dict,
        *,
        version: int | None = None,
    ) -> RelaySendResult:
        key = _template_key(template_key)
        payload = {"email": recipient, "context": context}
        if version is not None:
            payload["template_version"] = _version(version)
        document = self._request(
            "POST", f"/api/transactional/templates/{key}/test-send", payload, expected={200, 202}
        )
        return _parse_send_result(document, key, version or 1)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        expected: set[int],
        suppression_statuses: set[int] = frozenset(),
        params: dict[str, str] | None = None,
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
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as error:
            # A POST timeout can happen after Relay accepted the request. Never auto-resend it.
            raise RelayMailError("relay_ack_unknown", ambiguous=True) from error
        except requests.ConnectionError as error:
            raise RelayMailError("relay_unavailable", retryable=True) from error
        except requests.RequestException as error:
            raise RelayMailError("relay_transport_error", retryable=True) from error
        status = getattr(response, "status_code", None)
        document = _json_object(response)
        if status in suppression_statuses and _is_suppression(document):
            raise RelayMailError(
                "relay_suppressed",
                suppressed=True,
                reason_code=_suppression_reason(document),
                status=status,
            )
        if status not in expected:
            retryable = status in RETRYABLE_HTTP_STATUSES or (
                isinstance(status, int) and status >= 500
            )
            raise RelayMailError("relay_http_error", retryable=retryable, status=status)
        if document is None:
            raise RelayMailError("malformed_relay_response")
        return document


def configured_client(*, transport: Transport | None = None) -> RelayMailClient:
    return RelayMailClient(get("RELAY_BASE_URL"), get("RELAY_API_KEY"), transport=transport)


def _json_object(response) -> dict | None:
    try:
        document = response.json()
    except (AttributeError, TypeError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _is_suppression(document: dict | None) -> bool:
    if document is None:
        return False
    error = document.get("error")
    message = document.get("message")
    return (
        isinstance(error, dict)
        and error.get("code") == "transactional_suppressed"
        and isinstance(message, dict)
        and message.get("status") in {"skipped", "suppressed"}
    )


def _suppression_reason(document: dict) -> str:
    error = document.get("error", {})
    reason = error.get("reason") if isinstance(error, dict) else None
    if isinstance(reason, str) and 0 < len(reason) <= 128:
        return reason
    return "relay_suppressed"


def _absolute_http_url(value: object) -> str:
    if not isinstance(value, str):
        raise ImproperlyConfigured("RELAY_BASE_URL must be an absolute HTTP URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ImproperlyConfigured("RELAY_BASE_URL must be an absolute HTTP URL")
    return value


def _parse_send_result(document: dict, template_key: str, fallback_version: int) -> RelaySendResult:
    message = document.get("message")
    if not isinstance(message, dict):
        raise RelayMailError("malformed_send_response")
    raw_id = message.get("id")
    message_id = str(raw_id) if isinstance(raw_id, str | int) else ""
    status = message.get("status")
    version = message.get("template_version", fallback_version)
    replay = document.get("idempotent_replay", False)
    if (
        not message_id
        or len(message_id) > 128
        or status not in MESSAGE_STATUSES
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
        or not isinstance(replay, bool)
        or message.get("template_key") != template_key
    ):
        raise RelayMailError("malformed_send_response")
    return RelaySendResult(message_id, status, version, replay)


def _parse_message(row) -> RelayMessage:
    if not isinstance(row, dict):
        raise RelayMailError("malformed_messages_response")
    raw_id = row.get("id")
    message_id = str(raw_id) if isinstance(raw_id, str | int) else ""
    fields = ("client_reference", "status", "template_key", "updated_at")
    if (
        not message_id
        or len(message_id) > 128
        or any(not isinstance(row.get(field), str) or not row[field] for field in fields)
    ):
        raise RelayMailError("malformed_messages_response")
    version = _version(row.get("template_version"))
    reason = row.get("reason_code", "")
    if not isinstance(reason, str) or len(reason) > 128:
        raise RelayMailError("malformed_messages_response")
    return RelayMessage(
        message_id=message_id,
        client_reference=row["client_reference"],
        status=row["status"],
        template_key=row["template_key"],
        template_version=version,
        reason_code=reason,
        updated_at=row["updated_at"],
    )


def _parse_template(item) -> dict:
    if not isinstance(item, dict):
        raise RelayMailError("malformed_templates_response")
    key = item.get("key")
    if not isinstance(key, str) or not TEMPLATE_KEY_PATTERN.fullmatch(key):
        raise RelayMailError("malformed_templates_response")
    result = dict(item)
    if "latest_version" in result and result["latest_version"] is not None:
        result["latest_version"] = _version(result["latest_version"])
    return result


def _parse_version(item, template_key: str) -> dict:
    if not isinstance(item, dict) or item.get("template_key") != template_key:
        raise RelayMailError("malformed_templates_response")
    result = dict(item)
    result["version"] = _version(item.get("version"))
    return result


def _template_key(value: str) -> str:
    if not isinstance(value, str) or not TEMPLATE_KEY_PATTERN.fullmatch(value):
        raise ValueError("invalid template key")
    return value


def _version(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RelayMailError("malformed_templates_response")
    return value
