from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.events.anonymous_registration import (
    cancel_anonymous_registration,
    confirm_anonymous_registration,
    request_anonymous_registration,
)
from community_base.events.models import Event, EventRegistration
from community_base.events.tokens import RegistrationTokenError, generate_registration_token
from community_base.mail.context import resolve_delivery_context
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db


def event(**values):
    values.setdefault("title", "Open community event")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=3))
    values.setdefault("status", "upcoming")
    values.setdefault("required_level", 0)
    return Event.objects.create(**values)


def token_from_delivery(delivery, key):
    context = resolve_delivery_context(delivery=delivery, context=delivery.context_data)
    return parse_qs(urlsplit(context[key]).query)["token"][0]


def delivery_url(delivery, key):
    return resolve_delivery_context(delivery=delivery, context=delivery.context_data)[key]


def test_anonymous_request_is_idempotent_and_persists_no_bearer_token():
    occurrence = event()

    first = request_anonymous_registration(occurrence, " Person@Example.com ")
    replay = request_anonymous_registration(occurrence, "person@example.com")

    assert first.changed is True
    assert replay.changed is False
    assert replay.registration == first.registration
    assert replay.delivery == first.delivery
    assert first.registration.status == EventRegistration.Status.PENDING_VERIFICATION
    assert first.registration.original_email == "Person@Example.com"
    assert first.registration.normalized_email == "person@example.com"
    assert "token" not in str(first.delivery.context_data).lower()
    assert "verify_url" not in first.delivery.context_data
    assert EmailDelivery.objects.count() == 1


def test_verification_confirms_once_and_management_token_cancels_once():
    requested = request_anonymous_registration(event(), "person@example.com")
    verification_token = token_from_delivery(requested.delivery, "verify_url")
    assert urlsplit(delivery_url(requested.delivery, "verify_url")).path == (
        "/events/registration/verify/"
    )

    registration, changed = confirm_anonymous_registration(verification_token)
    replay, replayed = confirm_anonymous_registration(verification_token)
    confirmation = EmailDelivery.objects.get(purpose="events.registration_confirmed")
    management_token = token_from_delivery(confirmation, "manage_url")
    assert urlsplit(delivery_url(confirmation, "manage_url")).path == (
        "/events/registration/manage/"
    )
    cancelled, did_cancel = cancel_anonymous_registration(management_token)

    assert changed is True
    assert replayed is False
    assert replay == registration
    assert registration.verified_at is not None
    assert did_cancel is True
    assert cancelled.status == EventRegistration.Status.CANCELLED
    with pytest.raises(RegistrationTokenError, match="invalid"):
        cancel_anonymous_registration(management_token)


def test_cancelled_registration_reactivates_with_a_new_version():
    requested = request_anonymous_registration(event(), "person@example.com")
    verification_token = token_from_delivery(requested.delivery, "verify_url")
    registration, _changed = confirm_anonymous_registration(verification_token)
    confirmation = EmailDelivery.objects.get(purpose="events.registration_confirmed")
    management_token = token_from_delivery(confirmation, "manage_url")
    cancel_anonymous_registration(management_token)

    reactivated = request_anonymous_registration(registration.event, registration.original_email)

    assert reactivated.changed is True
    assert reactivated.registration.version == 3
    assert reactivated.registration.status == EventRegistration.Status.PENDING_VERIFICATION
    assert reactivated.delivery != requested.delivery


def test_suppressed_event_mail_creates_no_delivery_job(settings):
    configured = dict(settings.COMMUNITY_BASE)
    configured["MAIL_PREFERENCE_RESOLVER"] = lambda **_kwargs: "events_suppressed"
    settings.COMMUNITY_BASE = configured

    result = request_anonymous_registration(event(), "person@example.com")

    assert result.delivery.state == EmailDelivery.State.SUPPRESSED
    assert result.delivery.job is None
    assert result.registration.status == EventRegistration.Status.PENDING_VERIFICATION


def test_anonymous_registration_requires_a_free_open_event_and_valid_email():
    with pytest.raises(ValidationError, match="not available"):
        request_anonymous_registration(event(required_level=5), "person@example.com")
    with pytest.raises(ValidationError):
        request_anonymous_registration(event(title="Another"), "not-an-email")


def test_expired_and_wrong_version_tokens_fail_closed():
    requested = request_anonymous_registration(event(), "person@example.com")
    expired = generate_registration_token(
        requested.registration,
        action="verify",
        issued_at=datetime.now(UTC) - timedelta(days=2),
        expiry_hours=1,
    )
    stale = token_from_delivery(requested.delivery, "verify_url")
    requested.registration.version += 1
    requested.registration.save(update_fields=("version", "updated_at"))

    with pytest.raises(RegistrationTokenError, match="expired"):
        confirm_anonymous_registration(expired)
    with pytest.raises(RegistrationTokenError, match="invalid"):
        confirm_anonymous_registration(stale)
