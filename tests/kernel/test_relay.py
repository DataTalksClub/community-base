from __future__ import annotations

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured

from community_base.jobs.relay import RelayClient, RelayError
from community_base.kernel.relay import (
    DEFAULT_TIMEOUT_SECONDS,
    RETRYABLE_HTTP_STATUSES,
    RelayClientBase,
    RequestsTransport,
)
from community_base.mail.models import EmailDelivery
from community_base.mail.relay import RelayMailClient, RelayMailError
from community_base.testing import FakeRelay, FakeResponse

BASE_URL = "https://relay.example.com"
API_KEY = "relay-test-key"


def _mail_delivery() -> EmailDelivery:
    return EmailDelivery(
        idempotency_key="welcome:test",
        purpose="welcome",
        template_key="welcome",
        template_version=1,
        recipient_email="person@example.com",
        context_hash="0" * 64,
    )


def test_jobs_and_mail_clients_share_one_relay_http_client_base():
    from community_base.jobs import relay as jobs_relay
    from community_base.mail import relay as mail_relay

    assert issubclass(RelayClient, RelayClientBase)
    assert issubclass(RelayMailClient, RelayClientBase)
    assert RelayClient.__init__ is RelayClientBase.__init__
    assert RelayMailClient.__init__ is RelayClientBase.__init__
    assert RelayClient._request is RelayClientBase._request
    assert RelayMailClient._request is RelayClientBase._request
    assert jobs_relay.RequestsTransport is RequestsTransport
    assert mail_relay.RequestsTransport is RequestsTransport


def test_base_requires_subclass_timeout_classification_hook():
    class IncompleteClient(RelayClientBase):
        error_class = RelayError

    transport = FakeRelay(error=requests.Timeout("timed out"))
    client = IncompleteClient(BASE_URL, API_KEY, transport=transport)
    with pytest.raises(NotImplementedError):
        client._request("GET", "/health/ready", expected={200})


@pytest.mark.parametrize("client_cls", [RelayClient, RelayMailClient])
@pytest.mark.parametrize(
    ("base_url", "api_key", "timeout_seconds", "message"),
    [
        (None, API_KEY, DEFAULT_TIMEOUT_SECONDS, "RELAY_BASE_URL must be an absolute HTTP URL"),
        ("ftp://relay.example.com", API_KEY, DEFAULT_TIMEOUT_SECONDS, "absolute HTTP URL"),
        (
            "https://user:pass@relay.example.com",
            API_KEY,
            DEFAULT_TIMEOUT_SECONDS,
            "absolute HTTP URL",
        ),
        ("https://relay.example.com/api", API_KEY, DEFAULT_TIMEOUT_SECONDS, "absolute HTTP URL"),
        ("https://relay.example.com?a=1", API_KEY, DEFAULT_TIMEOUT_SECONDS, "absolute HTTP URL"),
        ("https://relay.example.com#frag", API_KEY, DEFAULT_TIMEOUT_SECONDS, "absolute HTTP URL"),
        (BASE_URL, "", DEFAULT_TIMEOUT_SECONDS, "RELAY_API_KEY must be configured"),
        (BASE_URL, None, DEFAULT_TIMEOUT_SECONDS, "RELAY_API_KEY must be configured"),
        (BASE_URL, API_KEY, True, "Relay timeout must be an integer"),
        (BASE_URL, API_KEY, "15", "Relay timeout must be an integer"),
        (BASE_URL, API_KEY, 0, "Relay timeout must be between 1 and 60 seconds"),
        (BASE_URL, API_KEY, 61, "Relay timeout must be between 1 and 60 seconds"),
    ],
)
def test_shared_constructor_validation(client_cls, base_url, api_key, timeout_seconds, message):
    with pytest.raises(ImproperlyConfigured, match=message):
        client_cls(base_url, api_key, timeout_seconds=timeout_seconds)


@pytest.mark.parametrize("client_cls", [RelayClient, RelayMailClient])
def test_default_transport_and_base_url_normalization(client_cls):
    client = client_cls("https://relay.example.com/", API_KEY)
    assert client.base_url == BASE_URL
    assert isinstance(client.transport, RequestsTransport)
    assert client.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_timeout_hook_preserves_jobs_retryable_and_mail_ambiguous_semantics():
    jobs_transport = FakeRelay(error=requests.Timeout("jobs timeout"))
    jobs_client = RelayClient(BASE_URL, API_KEY, transport=jobs_transport)
    with pytest.raises(RelayError) as jobs_err:
        jobs_client.health()
    assert jobs_err.value.code == "relay_unavailable"
    assert jobs_err.value.retryable is True
    assert jobs_err.value.status is None

    mail_transport = FakeRelay(error=requests.Timeout("mail timeout"))
    mail_client = RelayMailClient(BASE_URL, API_KEY, transport=mail_transport)
    with pytest.raises(RelayMailError) as mail_err:
        mail_client.templates()
    assert mail_err.value.code == "relay_ack_unknown"
    assert mail_err.value.ambiguous is True
    assert mail_err.value.retryable is False
    assert mail_err.value.suppressed is False
    assert mail_err.value.status is None


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (requests.ConnectionError("refused"), "relay_unavailable"),
        (requests.RequestException("broken"), "relay_transport_error"),
    ],
)
def test_connection_and_request_exceptions_keep_error_semantics(exc, expected_code):
    jobs_client = RelayClient(BASE_URL, API_KEY, transport=FakeRelay(error=exc))
    with pytest.raises(RelayError) as jobs_err:
        jobs_client.health()
    assert jobs_err.value.code == expected_code
    assert jobs_err.value.retryable is True

    mail_client = RelayMailClient(BASE_URL, API_KEY, transport=FakeRelay(error=exc))
    with pytest.raises(RelayMailError) as mail_err:
        mail_client.templates()
    assert mail_err.value.code == expected_code
    assert mail_err.value.retryable is True
    assert mail_err.value.ambiguous is False


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (400, False),
        (404, False),
        (409, False),
        *((code, True) for code in sorted(RETRYABLE_HTTP_STATUSES)),
        (500, True),
        (503, True),
    ],
)
def test_http_status_classification_matches_across_both_clients(status, retryable):
    jobs_transport = FakeRelay()
    jobs_transport.next_response = FakeResponse(status, {"error": "failed"})
    jobs_client = RelayClient(BASE_URL, API_KEY, transport=jobs_transport)
    with pytest.raises(RelayError) as jobs_err:
        jobs_client.health()
    assert jobs_err.value.code == "relay_http_error"
    assert jobs_err.value.status == status
    assert jobs_err.value.retryable is retryable

    mail_transport = FakeRelay()
    mail_transport.next_response = FakeResponse(status, {"error": "failed"})
    mail_client = RelayMailClient(BASE_URL, API_KEY, transport=mail_transport)
    with pytest.raises(RelayMailError) as mail_err:
        mail_client.send(_mail_delivery())
    assert mail_err.value.code == "relay_http_error"
    assert mail_err.value.status == status
    assert mail_err.value.retryable is retryable
    assert mail_err.value.ambiguous is False
    assert mail_err.value.suppressed is False


@pytest.mark.parametrize("bad_document", [ValueError("bad json"), ["not", "a", "dict"], "text"])
def test_malformed_json_response_keep_error_semantics(bad_document):
    jobs_transport = FakeRelay()
    jobs_transport.next_response = FakeResponse(200, bad_document)
    jobs_client = RelayClient(BASE_URL, API_KEY, transport=jobs_transport)
    with pytest.raises(RelayError, match="^malformed_relay_response$"):
        jobs_client.health()

    mail_transport = FakeRelay()
    mail_transport.next_response = FakeResponse(200, bad_document)
    mail_client = RelayMailClient(BASE_URL, API_KEY, transport=mail_transport)
    with pytest.raises(RelayMailError, match="^malformed_relay_response$"):
        mail_client.templates()
