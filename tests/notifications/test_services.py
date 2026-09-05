import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from community_base.accounts.services.privacy import build_user_data_export
from community_base.notifications.models import Notification, NotificationPreference
from community_base.notifications.registry import (
    NotificationDraft,
    NotificationSourceError,
    register_notification_source,
    registered_notification_sources,
)
from community_base.notifications.services import (
    create_notification,
    emit_notification,
    emit_notification_safely,
    mark_all_notifications_read,
    mark_notification_read,
    notifications_enabled,
    safe_notification_url,
    set_notification_preference,
)
from community_base.notifications.signals import notification_event

pytestmark = pytest.mark.django_db(transaction=True)


def account(email="member@example.com", **kwargs):
    return get_user_model().objects.create_user(email=email, **kwargs)


def test_notification_model_orders_newest_and_enforces_recipient_dedupe():
    user = account()
    first = Notification.objects.create(user=user, title="First", dedupe_key="event:1")
    second = Notification.objects.create(user=user, title="Second")

    assert list(Notification.objects.all()) == [second, first]
    with pytest.raises(IntegrityError):
        Notification.objects.create(user=user, title="Duplicate", dedupe_key="event:1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/events/one", "/events/one"),
        ("https://community.example.com/events/one", "https://community.example.com/events/one"),
        ("javascript:alert(1)", ""),
        ("//malicious.example/path", ""),
        ("/safe\\redirect", ""),
        ("relative/path", ""),
    ],
)
def test_notification_urls_allow_only_local_or_http_targets(value, expected):
    assert safe_notification_url(value) == expected


def test_source_registry_is_explicit_idempotent_and_rejects_conflicts():
    def builder(**kwargs):
        return ()

    assert register_notification_source("events", builder) is builder
    assert register_notification_source("events", builder) is builder
    assert registered_notification_sources() == ("events",)

    with pytest.raises(NotificationSourceError, match="already registered"):
        register_notification_source("events", lambda **kwargs: ())
    with pytest.raises(NotificationSourceError, match="invalid"):
        register_notification_source("Events Secret", builder)


def test_emit_builds_recipient_owned_notification_and_deduplicates():
    user = account()

    @register_notification_source("events")
    def events(*, event, payload):
        assert event == "published"
        return [
            NotificationDraft(
                recipient_id=user.pk,
                title=payload["title"],
                body="Join us",
                url="/events/one",
                notification_type="event",
                source_id="one",
                dedupe_key="published:one",
            )
        ]

    first = emit_notification("events", "published", {"title": "New event"})
    second = emit_notification("events", "published", {"title": "Changed text"})

    assert len(first) == 1
    assert second == ()
    notification = Notification.objects.get()
    assert notification.user == user
    assert notification.title == "New event"
    assert notification.source_key == "events"
    assert notification.source_id == "one"


def test_preferences_use_specific_override_then_global_default():
    user = account()

    assert notifications_enabled(user, "events") is True
    set_notification_preference(user, "*", False)
    assert notifications_enabled(user, "events") is False
    set_notification_preference(user, "events", True)
    assert notifications_enabled(user, "events") is True
    assert NotificationPreference.objects.count() == 2

    with pytest.raises(ValueError, match="invalid"):
        set_notification_preference(user, "Secret Source", False)


def test_disabled_preference_and_inactive_recipient_skip_creation():
    disabled = account("disabled@example.com")
    inactive = account("inactive@example.com", is_active=False)
    set_notification_preference(disabled, "events", False)

    assert create_notification(
        NotificationDraft(recipient_id=disabled.pk, title="Skip"), source_key="events"
    ) == (None, False)
    assert create_notification(
        NotificationDraft(recipient_id=inactive.pk, title="Skip"), source_key="events"
    ) == (None, False)


def test_mark_read_operations_never_change_another_recipient():
    owner = account("owner@example.com")
    other = account("other@example.com")
    owned = Notification.objects.create(user=owner, title="Owned")
    foreign = Notification.objects.create(user=other, title="Foreign")

    assert mark_notification_read(owner, foreign.pk) == 0
    assert mark_notification_read(owner, owned.pk) == 1
    assert mark_all_notifications_read(owner) == 0
    foreign.refresh_from_db()
    assert foreign.read is False


def test_signal_consumes_registered_source():
    user = account()
    register_notification_source(
        "plans",
        lambda **kwargs: [NotificationDraft(recipient_id=user.pk, title="Plan ready")],
    )

    notification_event.send(sender=object(), source="plans", event="shared")

    assert Notification.objects.get().title == "Plan ready"


def test_safe_emit_does_not_log_exception_message(caplog):
    @register_notification_source("events")
    def broken(**kwargs):
        raise RuntimeError("credential-canary")

    assert emit_notification_safely("events", "published", {"secret": "payload-canary"}) == ()
    assert "credential-canary" not in caplog.text
    assert "payload-canary" not in caplog.text


def test_account_privacy_export_includes_owned_notifications_and_preferences():
    user = account()
    Notification.objects.create(
        user=user,
        title="Owned notification",
        body="Member-owned body",
        source_key="events",
        source_id="event-one",
    )
    set_notification_preference(user, "events", False)

    exported = build_user_data_export(user)

    assert exported["notifications"][0]["title"] == "Owned notification"
    assert exported["notifications"][0]["source_id"] == "event-one"
    assert exported["notification_preferences"][0]["source_key"] == "events"
