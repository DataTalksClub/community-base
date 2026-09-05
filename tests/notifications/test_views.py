import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse

from community_base.notifications.models import Notification
from community_base.notifications.registry import NotificationDraft, register_notification_source
from community_base.notifications.signals import notification_event

pytestmark = pytest.mark.django_db(transaction=True)


def account(email):
    return get_user_model().objects.create_user(email=email)


def notification(user, title, **kwargs):
    return Notification.objects.create(user=user, title=title, **kwargs)


def assert_private(response):
    assert {"private", "no-store", "max-age=0"}.issubset(
        {item.strip() for item in response["Cache-Control"].split(",")}
    )


def test_notification_routes_require_login(client):
    assert client.get(reverse("notification_list")).status_code == 302
    assert client.get(reverse("api_notification_list")).status_code == 302
    assert client.get(reverse("api_unread_count")).status_code == 302


def test_list_api_returns_only_current_recipient_and_supports_unread_filter(client):
    owner = account("owner@example.com")
    other = account("other@example.com")
    notification(owner, "Unread", body="x" * 100, url="/events/one")
    notification(owner, "Read", read=True)
    notification(other, "Foreign")
    client.force_login(owner)

    response = client.get(reverse("api_notification_list"), {"filter": "unread"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["notifications"][0]["title"] == "Unread"
    assert len(response.json()["notifications"][0]["body"]) == 80
    assert_private(response)


def test_list_api_rejects_invalid_filter_without_leaking_rows(client):
    owner = account("owner@example.com")
    notification(owner, "Private title")
    client.force_login(owner)

    response = client.get(reverse("api_notification_list"), {"filter": "secret"})

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "invalid_filter"}
    assert b"Private title" not in response.content


def test_unread_count_reflects_registered_source_signal(client):
    owner = account("owner@example.com")
    register_notification_source(
        "fixture",
        lambda **kwargs: [
            NotificationDraft(
                recipient_id=owner.pk,
                title="Fixture notification",
                dedupe_key="fixture:one",
            )
        ],
    )
    notification_event.send(sender=object(), source="fixture", event="created")
    client.force_login(owner)

    response = client.get(reverse("api_unread_count"))

    assert response.json() == {"count": 1}
    assert_private(response)


def test_mark_read_uses_recipient_ownership(client):
    owner = account("owner@example.com")
    other = account("other@example.com")
    owned = notification(owner, "Owned")
    foreign = notification(other, "Foreign")
    client.force_login(owner)

    denied = client.post(reverse("api_mark_read", args=(foreign.pk,)))
    accepted = client.post(reverse("api_mark_read", args=(owned.pk,)))

    assert denied.status_code == 404
    assert accepted.json() == {"ok": True}
    owned.refresh_from_db()
    foreign.refresh_from_db()
    assert owned.read is True and owned.read_at is not None
    assert foreign.read is False


def test_mark_all_read_changes_only_current_recipient(client):
    owner = account("owner@example.com")
    other = account("other@example.com")
    notification(owner, "One")
    notification(owner, "Two")
    foreign = notification(other, "Foreign")
    client.force_login(owner)

    response = client.post(reverse("api_mark_all_read"))

    assert response.json() == {"ok": True, "count": 2}
    assert not Notification.objects.filter(user=owner, read=False).exists()
    foreign.refresh_from_db()
    assert foreign.read is False


def test_page_defaults_to_unread_and_never_caches(client):
    owner = account("owner@example.com")
    notification(owner, "Unread")
    notification(owner, "Read", read=True)
    client.force_login(owner)

    response = client.get(reverse("notification_list"))

    assert response.status_code == 200
    assert b"Unread" in response.content
    assert b">Read<" not in response.content
    assert_private(response)


def test_template_tags_are_zero_for_anonymous_and_render_bell_for_member(rf):
    owner = account("owner@example.com")
    notification(owner, "Unread")
    request = RequestFactory().get("/")
    request.user = owner
    rendered = Template(
        "{% load notification_tags %}{% unread_notification_count as count %}"
        "{{ count }}{% notification_bell %}"
    ).render(Context({"request": request}))

    assert "1" in rendered
    assert reverse("notification_list") in rendered

    request.user = type("Anonymous", (), {"is_authenticated": False})()
    rendered = Template(
        "{% load notification_tags %}{% unread_notification_count as count %}{{ count }}"
    ).render(Context({"request": request}))
    assert rendered == "0"
