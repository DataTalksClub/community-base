from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from community_base.kernel.conf import get
from community_base.kernel.context import is_safe_external_context_id
from community_base.kernel.relay import RelayClientBase, Transport
from community_base.mail.relay_options import recipient_options
from community_base.mail.template_keys import TEMPLATE_KEY_PATTERN as TEMPLATE_KEY_PATTERN

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


class RelayMailClient(RelayClientBase):
    error_class = RelayMailError

    def _timeout_error(self) -> RelayMailError:
        # A POST timeout can happen after Relay accepted the request. Never auto-resend it.
        return RelayMailError("relay_ack_unknown", ambiguous=True)

    def send(self, delivery, *, context=None) -> RelaySendResult:
        payload = {
            "email": delivery.recipient_email,
            "template_key": delivery.template_key,
            "template_version": delivery.template_version,
            "idempotency_key": delivery.idempotency_key,
            "context": delivery.context_data if context is None else context,
        }
        if delivery.category:
            payload["category"] = delivery.category
        if delivery.sender_id:
            # Relay's existing API calls the approved sender identifier `from_email`.
            payload["from_email"] = delivery.sender_id
        payload.update(recipient_options(delivery.transport_options))
        document = self._request(
            "POST",
            "/api/transactional/send",
            payload,
            expected={200, 202},
            error_response=_suppression_error,
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
            not is_safe_external_context_id(message_id)
            or status not in MESSAGE_STATUSES
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or version != delivery.template_version
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
        if any(
            not isinstance(document.get(field), str)
            for field in ("subject", "html_body", "text_body")
        ):
            raise RelayMailError("malformed_preview_response")
        return document

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


def configured_client(*, transport: Transport | None = None) -> RelayMailClient:
    return RelayMailClient(get("RELAY_BASE_URL"), get("RELAY_API_KEY"), transport=transport)


def _suppression_error(status: int | None, document: dict | None) -> RelayMailError | None:
    if status == 409 and _is_suppression(document):
        return RelayMailError(
            "relay_suppressed",
            suppressed=True,
            reason_code=_suppression_reason(document),
            status=status,
        )
    return None


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
    if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", reason):
        return reason
    return "relay_suppressed"


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
        not is_safe_external_context_id(message_id)
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
    if not is_safe_external_context_id(message_id) or any(
        not isinstance(row.get(field), str) or not row[field] for field in fields
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
