from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlsplit

import requests
from django.core.exceptions import ImproperlyConfigured

DEFAULT_TIMEOUT_SECONDS = 15
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429})


class Transport(Protocol):
    def request(self, method: str, url: str, **kwargs): ...


class RequestsTransport:
    def __init__(self):
        self.session = requests.Session()

    def request(self, method: str, url: str, **kwargs):
        return self.session.request(method, url, **kwargs)


class RelayClientBase:
    error_class: type[RuntimeError]

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

    def _timeout_error(self) -> RuntimeError:
        raise NotImplementedError

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        expected: set[int],
        params: dict[str, str] | None = None,
        error_response: Callable[[int | None, dict | None], RuntimeError | None] | None = None,
    ) -> dict:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request_kwargs: dict[str, object] = {
            "headers": headers,
            "json": payload,
            "timeout": self.timeout_seconds,
        }
        if params is not None:
            request_kwargs["params"] = params
        try:
            response = self.transport.request(
                method,
                f"{self.base_url}{path}",
                **request_kwargs,
            )
        except requests.Timeout as error:
            raise self._timeout_error() from error
        except requests.ConnectionError as error:
            raise self.error_class("relay_unavailable", retryable=True) from error
        except requests.RequestException as error:
            raise self.error_class("relay_transport_error", retryable=True) from error
        status = getattr(response, "status_code", None)
        document = _json_object(response)
        if status not in expected:
            if error_response is not None:
                classified = error_response(status, document)
                if classified is not None:
                    raise classified
            retryable = status in RETRYABLE_HTTP_STATUSES or (
                isinstance(status, int) and status >= 500
            )
            raise self.error_class("relay_http_error", retryable=retryable, status=status)
        if document is None:
            raise self.error_class("malformed_relay_response")
        return document


def _json_object(response: object) -> dict | None:
    try:
        document = response.json()
    except (AttributeError, TypeError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _absolute_http_url(value: object, setting_name: str = "RELAY_BASE_URL") -> str:
    if not isinstance(value, str):
        raise ImproperlyConfigured(f"{setting_name} must be an absolute HTTP URL")
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
        raise ImproperlyConfigured(f"{setting_name} must be an absolute HTTP URL")
    return value
