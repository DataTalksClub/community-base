from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from django.db import transaction

from community_base.config.registry import definition
from community_base.jobs.models import JobIntent
from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.mail.backends import ses_local
from community_base.mail.backends.ses_local import render_delivery
from community_base.mail.models import EmailDelivery
from community_base.mail.service import MailError, send

FIXTURES = Path(__file__).parent / "fixtures" / "ses_local"
PREVIEW_CONTEXTS = {
    "free_welcome": {
        "user_name": "Ada",
        "site_url": "https://aishippinglabs.com",
    },
    "event_registration": {
        "user_name": "Ada",
        "event_title": "AI Shipping Workshop",
        "event_datetime": "March 21, 2026, 18:00 Europe/Berlin",
        "join_url": "https://aishippinglabs.com/events/42/community-lunch/join",
        "cancel_url": (
            "https://aishippinglabs.com/events/community-lunch/"
            "cancel-registration?token=preview-token"
        ),
        "google_calendar_url": (
            "https://calendar.google.com/calendar/render?action=TEMPLATE"
            "&text=AI%20Shipping%20Workshop"
            "&dates=20260321T180000Z%2F20260321T190000Z"
            "&details=Join%3A%20https%3A%2F%2Faishippinglabs.com"
            "%2Fevents%2Fcommunity-lunch%2Fjoin"
            "&location=https%3A%2F%2Faishippinglabs.com"
            "%2Fevents%2Fcommunity-lunch%2Fjoin"
        ),
        "outlook_calendar_url": (
            "https://outlook.live.com/calendar/0/deeplink/compose"
            "?path=%2Fcalendar%2Faction%2Fcompose&rru=addevent"
            "&subject=AI%20Shipping%20Workshop"
            "&startdt=2026-03-21T18%3A00%3A00Z"
            "&enddt=2026-03-21T19%3A00%3A00Z"
            "&body=Join%3A%20https%3A%2F%2Faishippinglabs.com"
            "%2Fevents%2Fcommunity-lunch%2Fjoin"
            "&location=https%3A%2F%2Faishippinglabs.com"
            "%2Fevents%2Fcommunity-lunch%2Fjoin"
        ),
        "office365_calendar_url": (
            "https://outlook.office.com/calendar/0/deeplink/compose"
            "?path=%2Fcalendar%2Faction%2Fcompose&rru=addevent"
            "&subject=AI%20Shipping%20Workshop"
            "&startdt=2026-03-21T18%3A00%3A00Z"
            "&enddt=2026-03-21T19%3A00%3A00Z"
            "&body=Join%3A%20https%3A%2F%2Faishippinglabs.com"
            "%2Fevents%2Fcommunity-lunch%2Fjoin"
            "&location=https%3A%2F%2Faishippinglabs.com"
            "%2Fevents%2Fcommunity-lunch%2Fjoin"
        ),
    },
    "password_reset": {
        "user_name": "Ada",
        "reset_url": "https://aishippinglabs.com/reset?token=demo",
    },
}


class FakeBotoCoreError(Exception):
    pass


class FakeClientError(Exception):
    pass


class FakeConnectionClosedError(FakeBotoCoreError):
    pass


class FakeConnectTimeoutError(FakeBotoCoreError):
    pass


class FakeEndpointConnectionError(FakeBotoCoreError):
    pass


class FakeNoCredentialsError(FakeBotoCoreError):
    pass


class FakePartialCredentialsError(FakeBotoCoreError):
    pass


class FakeReadTimeoutError(FakeBotoCoreError):
    pass


class StubSES:
    def __init__(self, response=None):
        self.response = response or {"MessageId": "ses-message-1"}
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def ses_settings(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_BACKEND": "ses_local",
        "MAIL_TEMPLATE_DIR": FIXTURES,
        "SITE_URL": "https://aishippinglabs.com",
        "STUDIO_TITLE": "AI Shipping Labs Studio",
    }
    return settings


@pytest.fixture
def fake_botocore(monkeypatch):
    package = ModuleType("botocore")
    exceptions = ModuleType("botocore.exceptions")
    classes = {
        "BotoCoreError": FakeBotoCoreError,
        "ClientError": FakeClientError,
        "ConnectionClosedError": FakeConnectionClosedError,
        "ConnectTimeoutError": FakeConnectTimeoutError,
        "EndpointConnectionError": FakeEndpointConnectionError,
        "NoCredentialsError": FakeNoCredentialsError,
        "PartialCredentialsError": FakePartialCredentialsError,
        "ReadTimeoutError": FakeReadTimeoutError,
    }
    for name, value in classes.items():
        setattr(exceptions, name, value)
    package.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "botocore", package)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exceptions)


@pytest.mark.parametrize("template_key", PREVIEW_CONTEXTS)
def test_render_matches_captured_aisl_fixture(settings, template_key):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_TEMPLATE_DIR": FIXTURES,
        "SITE_URL": "https://aishippinglabs.com",
        "STUDIO_TITLE": "AI Shipping Labs Studio",
    }
    delivery = EmailDelivery(
        template_key=template_key,
        purpose=template_key,
        recipient_email="ada@example.com",
        context_hash="0" * 64,
    )
    rendered = render_delivery(delivery, PREVIEW_CONTEXTS[template_key])
    normalized = re.sub(r"\s+", " ", rendered.html).strip()
    captured = json.loads((FIXTURES / "parity_hashes.json").read_text())
    assert hashlib.sha256(normalized.encode()).hexdigest() == captured[template_key]


@pytest.mark.django_db(transaction=True)
def test_handler_sends_with_ses_and_records_result(ses_settings):
    ses = StubSES()
    recorded = []
    ses_settings.COMMUNITY_BASE["MAIL_SEND_RECORDER"] = lambda delivery, rendered, result: (
        recorded.append((delivery, rendered, result))
    )
    ses_settings.COMMUNITY_BASE["MAIL_UNSUBSCRIBE_URL_BUILDER"] = lambda delivery: (
        "https://aishippinglabs.com/api/unsubscribe?token=test-token"
    )
    with patch("community_base.mail.backends.ses_local.configured_client", return_value=ses):
        with transaction.atomic():
            delivery = send(
                "password_reset",
                "ada@example.com",
                PREVIEW_CONTEXTS["password_reset"],
                "password-reset:1",
                sender="noreply@aishippinglabs.com",
                extra={"cc": "copy@example.com", "bcc": ["audit@example.com"]},
            )

    delivery.refresh_from_db()
    delivery.job.refresh_from_db()
    assert delivery.state == EmailDelivery.State.PROVIDER_ACCEPTED
    assert delivery.external_message_id == "ses-message-1"
    assert delivery.job.status == JobIntent.Status.SUCCEEDED
    assert len(recorded) == 1
    assert recorded[0][2].message_id == "ses-message-1"
    payload = ses.calls[0]
    assert payload["FromEmailAddress"] == "noreply@aishippinglabs.com"
    assert payload["Destination"] == {
        "ToAddresses": ["ada@example.com"],
        "CcAddresses": ["copy@example.com"],
        "BccAddresses": ["audit@example.com"],
    }
    assert payload["Content"]["Simple"]["Headers"][1] == {
        "Name": "List-Unsubscribe-Post",
        "Value": "List-Unsubscribe=One-Click",
    }


@pytest.mark.django_db
def test_override_hook_wins_over_filesystem(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_TEMPLATE_DIR": FIXTURES,
        "MAIL_TEMPLATE_OVERRIDE_LOADER": lambda key: (
            ("Overridden {{ value }}", "Body **{{ value }}**", "Custom footer")
            if key == "password_reset"
            else None
        ),
        "MAIL_VERIFY_EMAIL_URL_BUILDER": (
            lambda delivery: "https://aishippinglabs.com/api/verify-email?token=test-token"
        ),
    }
    delivery = EmailDelivery(
        template_key="password_reset",
        purpose="password_reset",
        recipient_email="ada@example.com",
        context_hash="0" * 64,
    )
    rendered = render_delivery(delivery, {"value": "content"})
    assert rendered.subject == "Overridden content"
    assert rendered.body_html == "<p>Body <strong>content</strong></p>"
    assert "Custom footer" in rendered.html
    assert "Your email is not verified" in rendered.html
    assert rendered.verify_email_url.endswith("token=test-token")


@pytest.mark.django_db(transaction=True)
def test_malformed_ses_response_is_terminal(ses_settings):
    with patch(
        "community_base.mail.backends.ses_local.configured_client",
        return_value=StubSES({"unexpected": True}),
    ):
        with transaction.atomic():
            delivery = send(
                "password_reset",
                "ada@example.com",
                PREVIEW_CONTEXTS["password_reset"],
                "password-reset:malformed",
                sender="noreply@aishippinglabs.com",
            )

    delivery.refresh_from_db()
    delivery.job.refresh_from_db()
    assert delivery.state == EmailDelivery.State.DEAD
    assert delivery.job.status == JobIntent.Status.DEAD


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "expected_state", "expected_exception"),
    [
        (
            FakeEndpointConnectionError("unavailable"),
            EmailDelivery.State.RETRYABLE,
            RetryableJobError,
        ),
        (
            FakeReadTimeoutError("uncertain acknowledgement"),
            EmailDelivery.State.AMBIGUOUS,
            PermanentJobError,
        ),
    ],
)
def test_transport_failure_classification(
    ses_settings, fake_botocore, error, expected_state, expected_exception
):
    delivery = EmailDelivery.objects.create(
        idempotency_key=f"password-reset:{expected_state}",
        template_key="password_reset",
        purpose="password_reset",
        recipient_email="ada@example.com",
        context_hash="0" * 64,
        sender_id="noreply@aishippinglabs.com",
    )
    with patch(
        "community_base.mail.backends.ses_local.configured_client",
        return_value=StubSES(error),
    ):
        with pytest.raises(expected_exception):
            ses_local.deliver(delivery, PREVIEW_CONTEXTS["password_reset"])
    delivery.refresh_from_db()
    assert delivery.state == expected_state


@pytest.mark.django_db
def test_accepted_delivery_retries_recorder_without_resending(ses_settings):
    delivery = EmailDelivery.objects.create(
        idempotency_key="password-reset:accepted",
        template_key="password_reset",
        purpose="password_reset",
        recipient_email="ada@example.com",
        context_hash="0" * 64,
        sender_id="noreply@aishippinglabs.com",
        state=EmailDelivery.State.PROVIDER_ACCEPTED,
        external_message_id="ses-message-existing",
    )
    recorded = []
    ses_settings.COMMUNITY_BASE["MAIL_SEND_RECORDER"] = lambda *args: recorded.append(args)
    with patch("community_base.mail.backends.ses_local.configured_client") as client:
        ses_local.deliver(delivery, PREVIEW_CONTEXTS["password_reset"])
    client.assert_not_called()
    assert recorded[0][2].message_id == "ses-message-existing"


@pytest.mark.django_db(transaction=True)
def test_transport_options_are_validated():
    with transaction.atomic():
        with pytest.raises(MailError, match="unsupported mail extra option"):
            send(
                "password_reset",
                "ada@example.com",
                {},
                "password-reset:bad-extra",
                extra={"reply_to": "person@example.com"},
            )


def test_ses_runtime_keys_are_declared():
    assert definition("AWS_SES_REGION").default == "us-east-1"
    assert definition("AWS_ACCESS_KEY_ID").secret is True
    assert definition("AWS_SECRET_ACCESS_KEY").secret is True
    assert definition("SES_FROM_EMAIL").is_email is True
