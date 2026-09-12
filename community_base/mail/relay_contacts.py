from __future__ import annotations

from dataclasses import dataclass

import requests
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email, validate_slug

from community_base.kernel.conf import get
from community_base.mail.relay import (
    DEFAULT_TIMEOUT_SECONDS,
    RETRYABLE_HTTP_STATUSES,
    RequestsTransport,
    Transport,
    _absolute_http_url,
    _json_object,
)

SUBSCRIPTION_STATUSES = frozenset({"pending", "subscribed", "unsubscribed"})
UNSUBSCRIBE_SCOPES = frozenset({"client", "audience", "global"})
EMAIL_VALIDATION_STATUSES = frozenset(
    {
        "unknown",
        "valid",
        "invalid_syntax",
        "no_mx",
        "disposable",
        "risky",
        "manually_invalid",
        "externally_validated",
    }
)
SUPPRESSION_FLAGS = ("global_unsubscribed", "hard_bounced", "complained")


class RelayContactsError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        ambiguous: bool = False,
        status: int | None = None,
        fields: dict | None = None,
    ):
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.status = status
        # Field names and error codes only; Relay validation errors never carry recipient data.
        self.fields = dict(fields) if isinstance(fields, dict) else {}
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RelayContact:
    contact_id: int | None
    exists: bool
    verified: bool
    verified_at: str | None
    email_validation: dict
    global_unsubscribed: bool
    hard_bounced: bool
    complained: bool
    audience_subscription: dict
    client_subscription: dict
    can_send_marketing: bool
    can_send_transactional: bool
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelayCategoryPreference:
    tag: str
    label: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class RelayContactPreferences:
    categories: tuple[RelayCategoryPreference, ...]
    global_unsubscribed: bool
    suppressed: bool
    suppression_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelayVerificationRequest:
    status: str
    category: str
    template_key: str


@dataclass(frozen=True, slots=True)
class RelayVerificationConfirmation:
    category: RelayCategoryPreference


class RelayContactsClient:
    """Client for the Relay contacts, tags and subscriptions contracts (C6.2).

    Relay owns contact data (decision D4); this client writes and reads it on a
    site's behalf and never persists recipient data. Raised errors carry codes
    and field names only, never recipient addresses.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        client: str,
        *,
        transport: Transport | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = _absolute_http_url(base_url).rstrip("/")
        if not isinstance(api_key, str) or not api_key:
            raise ImproperlyConfigured("RELAY_API_KEY must be configured")
        if not isinstance(client, str) or not client.strip():
            raise ImproperlyConfigured("the Relay client slug must be configured")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
            raise ImproperlyConfigured("Relay timeout must be an integer")
        if not 1 <= timeout_seconds <= 60:
            raise ImproperlyConfigured("Relay timeout must be between 1 and 60 seconds")
        self.api_key = api_key
        self.client = client.strip()
        self.transport = transport or RequestsTransport()
        self.timeout_seconds = timeout_seconds

    def upsert_contact(
        self,
        email: str,
        audience: str,
        *,
        tags: tuple[str, ...] | list[str] | None = None,
        status: str | None = None,
        verified: bool | None = None,
        email_validation: dict | None = None,
        suppression: dict | None = None,
    ) -> RelayContact:
        payload: dict = {
            "email": _email(email),
            "audience": _audience(audience),
            "client": self.client,
        }
        if tags is not None:
            payload["tags"] = list(_tags(tags))
        if status is not None:
            payload["status"] = _subscription_status(status)
        if verified is not None:
            payload["verified"] = _bool(verified, "verified")
        if email_validation is not None:
            payload["email_validation"] = _email_validation(email_validation)
        if suppression is not None:
            payload["suppression"] = _suppression(suppression)
        document = self._request("POST", "/api/contacts", payload, expected={200})
        return _parse_contact(document, with_tags=True)

    def contact_status(self, email: str, audience: str) -> RelayContact:
        document = self._request(
            "GET",
            "/api/contacts/status",
            expected={200},
            params={"email": _email(email), "audience": _audience(audience), "client": self.client},
        )
        return _parse_contact(document, with_tags=False)

    def contact_preferences(
        self, email: str, audience: str, *, category_tags: tuple[str, ...] | list[str] | None = None
    ) -> RelayContactPreferences:
        params = {"email": _email(email), "audience": _audience(audience), "client": self.client}
        if category_tags:
            params["category_tags"] = ",".join(_categories(category_tags))
        document = self._request("GET", "/api/contacts/preferences", expected={200}, params=params)
        return _parse_preferences(document)

    def update_contact_preferences(
        self,
        email: str,
        audience: str,
        categories: tuple[dict, ...] | list[dict],
        *,
        reason: str = "",
    ) -> RelayContactPreferences:
        payload = {
            "email": _email(email),
            "audience": _audience(audience),
            "client": self.client,
            "categories": _preference_input(categories),
        }
        if reason:
            payload["reason"] = _reason(reason)
        document = self._request("PUT", "/api/contacts/preferences", payload, expected={200})
        return _parse_preferences(document)

    def replace_tags(
        self, contact_id: int, audience: str, tags: tuple[str, ...] | list[str]
    ) -> RelayContact:
        payload = {
            "audience": _audience(audience),
            "client": self.client,
            "tags": list(_tags(tags)),
        }
        document = self._request("PUT", _contact_path(contact_id, "tags"), payload, expected={200})
        return _parse_contact(document, with_tags=True)

    def add_tag(self, contact_id: int, audience: str, tag: str) -> RelayContact:
        document = self._request(
            "POST",
            _contact_path(contact_id, f"tags/{_slug(tag)}"),
            expected={200},
            params={"audience": _audience(audience), "client": self.client},
        )
        return _parse_contact(document, with_tags=True)

    def remove_tag(self, contact_id: int, audience: str, tag: str) -> RelayContact:
        document = self._request(
            "DELETE",
            _contact_path(contact_id, f"tags/{_slug(tag)}"),
            expected={200},
            params={"audience": _audience(audience), "client": self.client},
        )
        return _parse_contact(document, with_tags=True)

    def subscribe(
        self,
        email: str,
        audience: str,
        *,
        tags: tuple[str, ...] | list[str] | None = None,
        category: str | None = None,
    ) -> RelayContact:
        payload: dict = {
            "email": _email(email),
            "audience": _audience(audience),
            "client": self.client,
        }
        if tags is not None:
            payload["tags"] = list(_tags(tags))
        if category is not None:
            payload["category"] = _slug(category)
        document = self._request("POST", "/api/subscriptions/subscribe", payload, expected={200})
        return _parse_contact(document, with_tags=True)

    def unsubscribe(
        self,
        email: str,
        audience: str,
        *,
        scope: str,
        reason: str = "",
        category: str | None = None,
    ) -> RelayContact:
        payload: dict = {
            "email": _email(email),
            "audience": _audience(audience),
            "client": self.client,
            "scope": _scope(scope),
        }
        if reason:
            payload["reason"] = _reason(reason)
        if category is not None:
            payload["category"] = _slug(category)
        document = self._request("POST", "/api/subscriptions/unsubscribe", payload, expected={200})
        contact = _parse_contact(document, with_tags=False)
        if document.get("scope") != payload["scope"]:
            raise RelayContactsError("malformed_contacts_response")
        return contact

    def request_verification(
        self, email: str, audience: str, *, category: str, template_key: str
    ) -> RelayVerificationRequest:
        payload = {
            "email": _email(email),
            "audience": _audience(audience),
            "client": self.client,
            "category": _slug(category),
            "template_key": template_key,
        }
        document = self._request(
            "POST", "/api/subscriptions/request-verification", payload, expected={200}
        )
        if (
            not isinstance(document, dict)
            or document.get("status") != "verification_requested"
            or not isinstance(document.get("email"), str)
            or document.get("category") != payload["category"]
            or document.get("template_key") != template_key
            or not isinstance(document.get("audience"), str)
            or not isinstance(document.get("client"), str)
        ):
            raise RelayContactsError("malformed_verification_response")
        return RelayVerificationRequest(
            status=document["status"],
            category=document["category"],
            template_key=document["template_key"],
        )

    def confirm_verification(self, token: str) -> RelayVerificationConfirmation:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("verification token is required")
        document = self._request(
            "POST", "/api/subscriptions/confirm", {"token": token}, expected={200}
        )
        category = document.get("category") if isinstance(document, dict) else None
        if not isinstance(category, dict):
            raise RelayContactsError("malformed_verification_response")
        try:
            parsed = _preference_row(category, "category")
        except RelayContactsError as error:
            raise RelayContactsError("malformed_verification_response") from error
        return RelayVerificationConfirmation(category=parsed)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        expected: set[int],
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
            if method == "POST":
                # A POST timeout can happen after Relay accepted the request. Never auto-resend it.
                raise RelayContactsError("relay_ack_unknown", ambiguous=True) from error
            raise RelayContactsError("relay_timeout", retryable=True) from error
        except requests.ConnectionError as error:
            raise RelayContactsError("relay_unavailable", retryable=True) from error
        except requests.RequestException as error:
            raise RelayContactsError("relay_transport_error", retryable=True) from error
        status = getattr(response, "status_code", None)
        document = _json_object(response)
        if status not in expected:
            if document is not None and isinstance(document.get("error"), dict):
                error = document["error"]
                if error.get("code") == "validation_error":
                    raise RelayContactsError(
                        "relay_validation_error", status=status, fields=error.get("fields")
                    )
            retryable = status in RETRYABLE_HTTP_STATUSES or (
                isinstance(status, int) and status >= 500
            )
            raise RelayContactsError("relay_http_error", retryable=retryable, status=status)
        if document is None:
            raise RelayContactsError("malformed_contacts_response")
        return document


def configured_contacts_client(client: str, *, transport: Transport | None = None):
    return RelayContactsClient(
        get("RELAY_BASE_URL"), get("RELAY_API_KEY"), client, transport=transport
    )


def _contact_path(contact_id: int, suffix: str) -> str:
    if not isinstance(contact_id, int) or isinstance(contact_id, bool) or contact_id < 1:
        raise ValueError("contact id must be a positive integer")
    return f"/api/contacts/{contact_id}/{suffix}"


def _email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("email must be a string")
    cleaned = value.strip()
    try:
        validate_email(cleaned)
    except ValidationError as error:
        raise ValueError("invalid email") from error
    return cleaned


def _audience(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("audience is required")
    return value.strip()


def _scope(value: str) -> str:
    if not isinstance(value, str) or value not in UNSUBSCRIBE_SCOPES:
        raise ValueError("scope must be one of client, audience, global")
    return value


def _subscription_status(value: str) -> str:
    if not isinstance(value, str) or value not in SUBSCRIPTION_STATUSES:
        raise ValueError("status must be one of pending, subscribed, unsubscribed")
    return value


def _slug(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tag slug is required")
    cleaned = value.strip()
    try:
        validate_slug(cleaned)
    except ValidationError as error:
        raise ValueError("invalid tag slug") from error
    return cleaned


def _categories(values) -> tuple[str, ...]:
    if not isinstance(values, tuple | list) or any(not isinstance(item, str) for item in values):
        raise ValueError("category tags must be strings")
    cleaned = tuple(item.strip() for item in values if item.strip())
    for item in cleaned:
        _slug(item)
    return cleaned


def _tags(values) -> tuple[str, ...]:
    if not isinstance(values, tuple | list):
        raise ValueError("tags must be a list of strings")
    cleaned = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("tags must be non-empty strings")
        cleaned.append(item.strip())
    return tuple(cleaned)


def _reason(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("reason must be a string")
    return value.strip()


def _bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _email_validation(value: dict) -> dict:
    if not isinstance(value, dict) or "status" not in value:
        raise ValueError("email_validation requires a status")
    status = value["status"]
    if not isinstance(status, str) or status not in EMAIL_VALIDATION_STATUSES:
        raise ValueError("email_validation.status is invalid")
    payload: dict = {"status": status}
    reason = value.get("reason", "")
    if not isinstance(reason, str):
        raise ValueError("email_validation.reason must be a string")
    if reason:
        payload["reason"] = reason
    if "validated_at" in value and value["validated_at"] is not None:
        if not isinstance(value["validated_at"], str):
            raise ValueError("email_validation.validated_at must be an ISO timestamp string")
        payload["validated_at"] = value["validated_at"]
    return payload


def _suppression(value: dict) -> dict:
    if not isinstance(value, dict) or not value:
        raise ValueError("suppression must be a non-empty object")
    payload = {}
    for flag in SUPPRESSION_FLAGS:
        if flag in value:
            payload[flag] = _bool(value[flag], f"suppression.{flag}")
    if not payload:
        raise ValueError("suppression has no known flags")
    return payload


def _preference_input(values) -> list[dict]:
    if not isinstance(values, tuple | list):
        raise ValueError("categories must be a list of objects")
    payload = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("categories must be a list of objects")
        tag = item.get("tag")
        enabled = item.get("enabled")
        label = item.get("label", "")
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError("categories.tag is required")
        if not isinstance(enabled, bool):
            raise ValueError("categories.enabled must be a boolean")
        if not isinstance(label, str):
            raise ValueError("categories.label must be a string")
        payload.append({"tag": tag.strip(), "enabled": enabled, "label": label.strip()})
    return payload


def _preference_row(row, field: str) -> RelayCategoryPreference:
    if not isinstance(row, dict):
        raise RelayContactsError(f"malformed_{field}_response")
    tag = row.get("tag")
    enabled = row.get("enabled")
    label = row.get("label", "")
    if (
        not isinstance(tag, str)
        or not tag.strip()
        or not isinstance(enabled, bool)
        or not isinstance(label, str)
    ):
        raise RelayContactsError(f"malformed_{field}_response")
    return RelayCategoryPreference(tag=tag, label=label, enabled=enabled)


def _parse_contact(document: dict, *, with_tags: bool) -> RelayContact:
    if not isinstance(document, dict):
        raise RelayContactsError("malformed_contacts_response")
    contact_id = document.get("contact_id")
    flags = {
        key: document.get(key)
        for key in (
            "exists",
            "verified",
            "global_unsubscribed",
            "hard_bounced",
            "complained",
            "can_send_marketing",
            "can_send_transactional",
        )
    }
    contact_id_ok = contact_id is None or (
        isinstance(contact_id, int) and not isinstance(contact_id, bool)
    )
    verified_at = document.get("verified_at")
    if (
        not contact_id_ok
        or any(not isinstance(value, bool) for value in flags.values())
        or not isinstance(document.get("email_validation"), dict)
        or not isinstance(document.get("audience"), dict)
        or not isinstance(document.get("client"), dict)
        or (verified_at is not None and not isinstance(verified_at, str))
    ):
        raise RelayContactsError("malformed_contacts_response")
    if with_tags:
        tags = document.get("tags")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise RelayContactsError("malformed_contacts_response")
    else:
        tags = []
    return RelayContact(
        contact_id=contact_id,
        exists=flags["exists"],
        verified=flags["verified"],
        verified_at=document.get("verified_at"),
        email_validation=document["email_validation"],
        global_unsubscribed=flags["global_unsubscribed"],
        hard_bounced=flags["hard_bounced"],
        complained=flags["complained"],
        audience_subscription=document["audience"],
        client_subscription=document["client"],
        can_send_marketing=flags["can_send_marketing"],
        can_send_transactional=flags["can_send_transactional"],
        tags=tuple(sorted(tags)),
    )


def _parse_preferences(document: dict) -> RelayContactPreferences:
    if not isinstance(document, dict):
        raise RelayContactsError("malformed_preferences_response")
    rows = document.get("categories")
    flags = {key: document.get(key) for key in ("global_unsubscribed", "suppressed")}
    reasons = document.get("suppression_reasons")
    if (
        not isinstance(rows, list)
        or any(not isinstance(value, bool) for value in flags.values())
        or not isinstance(reasons, list)
        or any(not isinstance(reason, str) for reason in reasons)
    ):
        raise RelayContactsError("malformed_preferences_response")
    try:
        categories = tuple(_preference_row(row, "categories") for row in rows)
    except RelayContactsError as error:
        raise RelayContactsError("malformed_preferences_response") from error
    return RelayContactPreferences(
        categories=categories,
        global_unsubscribed=flags["global_unsubscribed"],
        suppressed=flags["suppressed"],
        suppression_reasons=tuple(reasons),
    )
