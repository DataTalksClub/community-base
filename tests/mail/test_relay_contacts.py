from __future__ import annotations

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured

from community_base.mail.relay_contacts import RelayContactsClient, RelayContactsError
from community_base.testing import FakeRelay, FakeResponse

BASE_URL = "https://relay.example.com"
CLIENT_SLUG = "aisl-website"
AUDIENCE = "aisl"
EMAIL = "person@example.com"


@pytest.fixture
def relay():
    return FakeRelay()


@pytest.fixture
def client(relay):
    return RelayContactsClient(BASE_URL, "relay-test-key", CLIENT_SLUG, transport=relay)


def test_upsert_posts_scope_and_parses_the_contact_document(relay, client):
    contact = client.upsert_contact(
        EMAIL,
        AUDIENCE,
        tags=["newsletter", "tier:main"],
        status="subscribed",
        verified=True,
    )
    assert contact.contact_id == 1
    assert contact.exists is True
    assert contact.verified is True
    assert contact.client_subscription["status"] == "subscribed"
    assert contact.can_send_marketing is True
    assert contact.tags == ("newsletter", "tier:main")
    method, url, kwargs = relay.calls[0]
    assert (method, url) == ("POST", f"{BASE_URL}/api/contacts")
    assert kwargs["json"]["client"] == CLIENT_SLUG
    assert kwargs["headers"]["Authorization"] == "Bearer relay-test-key"


def test_upsert_accepts_validation_and_suppression_inputs(client):
    contact = client.upsert_contact(
        EMAIL,
        AUDIENCE,
        email_validation={"status": "valid", "reason": "checked"},
        suppression={"hard_bounced": True},
    )
    assert contact.email_validation["status"] == "valid"
    assert contact.hard_bounced is True
    assert contact.can_send_marketing is False


def test_contact_status_of_unknown_email_is_not_exists(client):
    contact = client.contact_status(EMAIL, AUDIENCE)
    assert contact.exists is False
    assert contact.contact_id is None
    assert contact.can_send_transactional is False


def test_preferences_read_write_round_trip(client):
    defaults = client.contact_preferences(EMAIL, AUDIENCE, category_tags=("course-updates",))
    assert defaults.categories[0].enabled is True
    updated = client.update_contact_preferences(
        EMAIL, AUDIENCE, [{"tag": "course-updates", "enabled": False, "label": "Course updates"}]
    )
    assert updated.categories[0].enabled is False
    reread = client.contact_preferences(EMAIL, AUDIENCE, category_tags=("course-updates",))
    assert reread.categories[0].tag == "course-updates"
    assert reread.categories[0].enabled is False
    assert reread.suppressed is False


def test_enabling_a_category_on_a_suppressed_contact_conflicts(client):
    client.upsert_contact(EMAIL, AUDIENCE, suppression={"hard_bounced": True})
    with pytest.raises(RelayContactsError) as raised:
        client.update_contact_preferences(
            EMAIL, AUDIENCE, [{"tag": "course-updates", "enabled": True}]
        )
    error = raised.value
    assert error.code == "relay_validation_error"
    assert error.status == 409
    assert error.fields == {"categories": "suppressed_contact_cannot_be_enabled"}
    assert EMAIL not in str(error)


def test_replace_add_and_remove_tags(client):
    created = client.upsert_contact(EMAIL, AUDIENCE, tags=["tier:main"])
    contact_id = created.contact_id
    assert client.replace_tags(contact_id, AUDIENCE, ["a", "b"]).tags == ("a", "b")
    assert client.add_tag(contact_id, AUDIENCE, "c").tags == ("a", "b", "c")
    assert client.remove_tag(contact_id, AUDIENCE, "a").tags == ("b", "c")


def test_tag_endpoints_fail_with_not_found_for_unknown_contacts(client):
    with pytest.raises(RelayContactsError) as raised:
        client.replace_tags(999, AUDIENCE, ["a"])
    assert raised.value.status == 404
    assert raised.value.fields == {"contact_id": "not_found"}
    with pytest.raises(RelayContactsError):
        client.add_tag(999, AUDIENCE, "a")
    with pytest.raises(RelayContactsError):
        client.remove_tag(999, AUDIENCE, "a")


def test_subscribe_and_unsubscribe(client):
    subscribed = client.subscribe(EMAIL, AUDIENCE, tags=["newsletter"])
    assert subscribed.client_subscription["status"] == "subscribed"
    unsubscribed = client.unsubscribe(EMAIL, AUDIENCE, scope="global", reason="user request")
    assert unsubscribed.global_unsubscribed is True
    audience_unsubscribed = client.unsubscribe(EMAIL, AUDIENCE, scope="audience")
    assert audience_unsubscribed.exists is True


def test_unsubscribe_rejects_unknown_scopes_before_any_request(relay, client):
    with pytest.raises(ValueError, match="scope"):
        client.unsubscribe(EMAIL, AUDIENCE, scope="everything")
    assert relay.called is False


def test_double_opt_in_handoff_records_the_verification_send(relay, client):
    request = client.request_verification(
        EMAIL, AUDIENCE, category="course-updates", template_key="course-verify"
    )
    assert request.status == "verification_requested"
    assert request.template_key == "course-verify"
    assert len(relay.verification_sends) == 1
    token = relay.verification_sends[0]["context"]["verification_token"]
    confirmation = client.confirm_verification(token)
    assert confirmation.email == EMAIL
    assert confirmation.category.tag == "course-updates"
    assert confirmation.category.enabled is True


def test_confirm_rejects_unknown_tokens(client):
    with pytest.raises(RelayContactsError) as raised:
        client.confirm_verification("not-a-token")
    assert raised.value.fields == {"token": "invalid"}


def test_post_timeout_is_ambiguous_and_get_timeout_is_retryable(relay, client):
    relay.error = requests.Timeout("read timed out")
    with pytest.raises(RelayContactsError) as raised:
        client.upsert_contact(EMAIL, AUDIENCE)
    assert raised.value.ambiguous is True
    with pytest.raises(RelayContactsError) as raised:
        client.contact_status(EMAIL, AUDIENCE)
    assert raised.value.retryable is True
    assert raised.value.ambiguous is False


def test_connection_errors_are_retryable(relay, client):
    relay.error = requests.ConnectionError("connection refused")
    with pytest.raises(RelayContactsError) as raised:
        client.contact_status(EMAIL, AUDIENCE)
    assert raised.value.code == "relay_unavailable"
    assert raised.value.retryable is True


def test_http_5xx_is_retryable_and_leaks_no_recipient_data(relay, client):
    relay.next_response = FakeResponse(503, {"error": {"code": "internal"}})
    with pytest.raises(RelayContactsError) as raised:
        client.upsert_contact(EMAIL, AUDIENCE)
    assert raised.value.code == "relay_http_error"
    assert raised.value.retryable is True
    assert EMAIL not in str(raised.value)


def test_malformed_documents_are_rejected(relay, client):
    body = {
        "contact_id": 1,
        "exists": True,
        "verified": False,
        "verified_at": None,
        "email_validation": {},
        "global_unsubscribed": False,
        "hard_bounced": False,
        "complained": False,
        "audience": {},
        "client": {},
        "can_send_marketing": False,
        "can_send_transactional": False,
    }
    relay.next_response = FakeResponse(200, {"contact_id": "one"})
    with pytest.raises(RelayContactsError, match="malformed_contacts_response"):
        client.contact_status(EMAIL, AUDIENCE)
    relay.next_response = FakeResponse(200, body | {"tags": "tier:main"})
    with pytest.raises(RelayContactsError, match="malformed_contacts_response"):
        client.upsert_contact(EMAIL, AUDIENCE)
    relay.next_response = FakeResponse(200, {"categories": "nope", "suppressed": "nope"})
    with pytest.raises(RelayContactsError, match="malformed_preferences_response"):
        client.contact_preferences(EMAIL, AUDIENCE)
    relay.next_response = FakeResponse(200, {"status": "surprise"})
    with pytest.raises(RelayContactsError, match="malformed_verification_response"):
        client.request_verification(EMAIL, AUDIENCE, category="a", template_key="t")


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda c: c.upsert_contact("not-an-email", AUDIENCE), "email"),
        (lambda c: c.upsert_contact(EMAIL, AUDIENCE, tags=[1]), "tags"),
        (lambda c: c.upsert_contact(EMAIL, AUDIENCE, status="maybe"), "status"),
        (lambda c: c.upsert_contact(EMAIL, AUDIENCE, verified="yes"), "verified"),
        (
            lambda c: c.upsert_contact(EMAIL, AUDIENCE, email_validation={"status": "who-knows"}),
            "email_validation",
        ),
        (
            lambda c: c.upsert_contact(EMAIL, AUDIENCE, suppression={"hard_bounced": "yes"}),
            "suppression",
        ),
        (lambda c: c.upsert_contact(EMAIL, AUDIENCE, suppression={}), "suppression"),
        (lambda c: c.unsubscribe(EMAIL, AUDIENCE, scope="everything"), "scope"),
        (lambda c: c.add_tag(1, AUDIENCE, "not a slug!"), "slug"),
    ],
)
def test_client_side_validation_fails_before_any_request(relay, client, call, match):
    with pytest.raises(ValueError, match=match):
        call(client)
    assert relay.called is False


def test_construction_requires_configuration():
    with pytest.raises(ImproperlyConfigured):
        RelayContactsClient(BASE_URL, "", CLIENT_SLUG)
    with pytest.raises(ImproperlyConfigured):
        RelayContactsClient(BASE_URL, "relay-test-key", " ")
    with pytest.raises(ImproperlyConfigured):
        RelayContactsClient("not-a-url", "relay-test-key", CLIENT_SLUG)
    with pytest.raises(ImproperlyConfigured):
        RelayContactsClient(BASE_URL, "relay-test-key", CLIENT_SLUG, timeout_seconds=0)


@pytest.fixture
def callback_secret(settings):
    secret = "converge-callback-secret"
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_WEBHOOK_SECRET": secret}
    return secret


@pytest.mark.django_db
def test_upsert_preferences_and_subscription_callback_converge(client, callback_secret):
    from django.test import Client
    from django.utils import timezone

    from community_base.mail.models import CallbackEvent

    subscribed = client.subscribe(EMAIL, AUDIENCE, tags=["tier:main"])
    preferences = client.update_contact_preferences(
        EMAIL, AUDIENCE, [{"tag": "course-updates", "enabled": False}]
    )
    assert subscribed.tags == ("tier:main",)
    assert subscribed.client_subscription["status"] == "subscribed"
    assert preferences.categories[0].enabled is False

    # Relay announces the client-level subscription change with a signed callback.
    callback = {
        "event_id": "callback:converge",
        "event_type": "subscription.changed",
        "message_id": None,
        "client_reference": None,
        "reason_code": "subscribed",
        "sequence": 1,
        "timestamp": timezone.now().isoformat(),
    }
    response = FakeRelay().post_callback(Client(), callback, callback_secret)
    assert response.status_code == 200

    event = CallbackEvent.objects.get(event_id="callback:converge")
    assert event.reason_code == "subscribed"
    assert event.sequence == 1
    status = client.contact_status(EMAIL, AUDIENCE)
    assert status.client_subscription["status"] == "subscribed"
