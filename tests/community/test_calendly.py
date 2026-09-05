import hashlib
import hmac
import json
import time

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.accounts.models import EmailAlias
from community_base.community.calendly import verify_signature
from community_base.community.models import (
    STATUS_BOOKED,
    STATUS_CANCELED,
    BookedCall,
    CallHost,
    UnmatchedBookedCall,
)

pytestmark = pytest.mark.django_db(transaction=True)

HOST_URL = "https://calendly.com/community/intro"
SIGNING_KEY = "signing-secret"


def configured(settings, **overrides):
    settings.COMMUNITY_BASE = {
        "CALENDLY": True,
        "CALENDLY_WEBHOOK_SIGNING_KEY": SIGNING_KEY,
        **overrides,
    }


def signature(body, *, timestamp=None, key=SIGNING_KEY):
    timestamp = str(timestamp or int(time.time()))
    digest = hmac.new(key.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def payload(event="invitee.created", **overrides):
    resource = {
        "email": "member@example.com",
        "name": "Ada Member",
        "uri": "https://api.calendly.com/events/E1/invitees/I1",
        "scheduling_url": HOST_URL,
        "reschedule_url": "https://calendly.com/reschedule/one",
        "cancel_url": "https://calendly.com/cancellations/one",
        "scheduled_event": {
            "uri": "https://api.calendly.com/events/E1",
            "start_time": "2099-01-15T15:00:00Z",
        },
    }
    resource.update(overrides)
    return {"event": event, "created_at": "2026-01-01T12:00:00Z", "payload": resource}


def post(client, value, *, timestamp=None):
    body = json.dumps(value).encode()
    return client.post(
        reverse("community_base_calendly_webhook"),
        body,
        content_type="application/json",
        HTTP_CALENDLY_WEBHOOK_SIGNATURE=signature(body, timestamp=timestamp),
    )


@pytest.fixture
def host():
    return CallHost.objects.create(
        name="Community host",
        slug="community-host",
        booking_url=HOST_URL,
        is_active=True,
        capacity=3,
    )


def test_signature_fails_closed_and_accepts_any_valid_v1(settings):
    configured(settings)
    body = b"{}"
    valid = signature(body)
    timestamp, digest = valid.split(",")

    assert verify_signature(body, f"{timestamp},v1=bad,{digest}") is True
    assert verify_signature(body, "") is False
    configured(settings, CALENDLY_WEBHOOK_SIGNING_KEY="")
    assert verify_signature(body, valid) is False


def test_signature_rejects_stale_timestamp(settings):
    configured(settings, CALENDLY_WEBHOOK_TOLERANCE_SECONDS=300)
    body = b"{}"
    old = int(time.time()) - 301

    assert verify_signature(body, signature(body, timestamp=old)) is False


def test_disabled_calendly_is_not_exposed(client, settings):
    settings.COMMUNITY_BASE = {"CALENDLY": False}

    assert post(client, payload()).status_code == 404


def test_webhook_rejects_invalid_signature_json_and_oversize(client, settings):
    configured(settings, CALENDLY_WEBHOOK_MAX_BYTES=4)
    url = reverse("community_base_calendly_webhook")

    assert client.post(url, b"{}", content_type="application/json").status_code == 400
    assert post(client, payload()).status_code == 400
    configured(settings, CALENDLY_WEBHOOK_MAX_BYTES=100)
    body = b"no"
    assert (
        client.post(
            url,
            body,
            content_type="application/json",
            HTTP_CALENDLY_WEBHOOK_SIGNATURE=signature(body),
        ).status_code
        == 400
    )


def test_created_is_idempotent_matches_alias_and_increments_load_once(client, settings, host):
    configured(settings)
    member = get_user_model().objects.create_user(email="member@example.com")
    EmailAlias.objects.create(user=member, email="old@example.com")
    value = payload(email="old@example.com", scheduling_url=f"{HOST_URL}/?month=2099")

    assert post(client, value).status_code == 200
    assert post(client, value).status_code == 200

    call = BookedCall.objects.get()
    host.refresh_from_db()
    assert call.member == member
    assert call.status == STATUS_BOOKED
    assert host.current_load == 1


def test_cancel_is_idempotent_and_never_underflows(client, settings, host):
    configured(settings)

    post(client, payload())
    post(client, payload("invitee.canceled", canceled_at="2026-01-02T12:00:00Z"))
    post(client, payload("invitee.canceled", canceled_at="2026-01-02T12:00:00Z"))

    call = BookedCall.objects.get()
    host.refresh_from_db()
    assert call.status == STATUS_CANCELED
    assert call.canceled_at is not None
    assert host.current_load == 0


def test_cancel_before_create_is_a_terminal_tombstone(client, settings, host):
    configured(settings)

    post(client, payload("invitee.canceled"))
    post(client, payload("invitee.created"))

    assert BookedCall.objects.get().status == STATUS_CANCELED
    host.refresh_from_db()
    assert host.current_load == 0


def test_unknown_host_is_staged_then_promoted_once(client, settings, host):
    configured(settings)
    unknown = payload(scheduling_url="https://calendly.com/unknown/intro")

    post(client, unknown)
    post(client, unknown)
    assert UnmatchedBookedCall.objects.count() == 1
    assert not BookedCall.objects.exists()

    post(client, payload())
    assert not UnmatchedBookedCall.objects.exists()
    assert BookedCall.objects.get().status == STATUS_BOOKED
    host.refresh_from_db()
    assert host.current_load == 1


def test_unknown_host_cancel_before_create_remains_terminal(client, settings):
    configured(settings)
    unknown = "https://calendly.com/unknown/intro"

    post(client, payload("invitee.canceled", scheduling_url=unknown))
    post(client, payload("invitee.created", scheduling_url=unknown))

    assert UnmatchedBookedCall.objects.get().status == STATUS_CANCELED


def test_unknown_event_is_acknowledged_without_writes(client, settings, host):
    configured(settings)

    response = post(client, payload("routing_form_submission.created"))

    assert response.status_code == 200
    assert not BookedCall.objects.exists()
    assert not UnmatchedBookedCall.objects.exists()
