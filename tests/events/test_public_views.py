from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from community_base.events.models import Event, EventFeedback, EventRegistration
from community_base.events.routing import event_url
from community_base.events.services import add_alias, reserve_public_id
from community_base.events.tokens import generate_registration_token

pytestmark = pytest.mark.django_db(transaction=True)


def configured(settings, **values):
    result = dict(settings.COMMUNITY_BASE)
    result.update(values)
    return result


def event(**values):
    public_id = values.pop("reserved_public_id", 17)
    values.setdefault("title", "Portable event")
    values.setdefault("slug", "portable-event")
    values.setdefault("status", "upcoming")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=2))
    values.setdefault("end_datetime", timezone.now() + timedelta(days=2, hours=1))
    item = Event.objects.create(**values)
    reserve_public_id(item, public_id)
    item.refresh_from_db()
    return item


def registration(item, user, **values):
    values.setdefault("status", EventRegistration.Status.CONFIRMED)
    return EventRegistration.objects.create(
        event=item,
        user=user,
        original_email=user.email,
        normalized_email=user.email,
        **values,
    )


@pytest.mark.parametrize(
    ("style", "expected"),
    [("slug", "/events/portable-event/"), ("public_id", "/events/17/portable-event/")],
)
def test_event_detail_uses_configured_canonical_style(client, settings, style, expected):
    item = event()

    with override_settings(COMMUNITY_BASE=configured(settings, EVENT_URL_STYLE=style)):
        assert event_url(item) == expected
        response = client.get(expected)
        alternate = "/events/17/portable-event/" if style == "slug" else "/events/portable-event/"
        redirected = client.get(alternate)

    assert response.status_code == 200
    assert response.templates[0].name == "events/event_detail.html"
    assert redirected.status_code == 301
    assert redirected.url == expected


def test_event_alias_redirects_to_current_canonical_route(client):
    item = event()
    add_alias(item, "/events/legacy/portable")

    response = client.get("/events/legacy/portable/")

    assert response.status_code == 301
    assert response.url == "/events/portable-event/"


def test_list_renders_only_public_events(client):
    upcoming = event(title="Upcoming", slug="upcoming", reserved_public_id=18)
    past = event(
        title="Completed",
        slug="completed",
        status="completed",
        start_datetime=timezone.now() - timedelta(days=2),
        end_datetime=timezone.now() - timedelta(days=2, hours=-1),
        reserved_public_id=19,
    )
    event(title="Draft", slug="draft", status="draft", reserved_public_id=20)

    response = client.get("/events/")

    assert response.status_code == 200
    assert list(response.context["upcoming_events"]) == [upcoming]
    assert list(response.context["past_events"]) == [past]
    assert "Draft" not in response.content.decode()


def test_member_can_register_and_unregister_from_detail(client):
    item = event()
    user = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(user)

    registered = client.post(reverse("event_register", kwargs={"slug": item.slug}))
    detail = client.get(item.get_absolute_url())
    unregistered = client.post(reverse("event_unregister", kwargs={"slug": item.slug}))

    row = EventRegistration.objects.get(event=item, user=user)
    assert registered.status_code == 302
    assert "no-store" in detail["Cache-Control"]
    assert "Cookie" in detail["Vary"]
    assert unregistered.status_code == 302
    assert row.status == EventRegistration.Status.CANCELLED


def test_anonymous_registration_and_verification_pages_are_private(client):
    item = event()

    requested = client.post(
        reverse("event_register", kwargs={"slug": item.slug}),
        {
            "email": "Guest@Example.com",
            "display_name": "Guest",
            "privacy_acknowledged": "on",
        },
    )
    row = EventRegistration.objects.get(event=item, normalized_email="guest@example.com")
    token = generate_registration_token(row, action="verify")
    verified = client.get(reverse("event_registration_verify"), {"token": token})

    row.refresh_from_db()
    assert requested.status_code == 200
    assert "no-store" in requested["Cache-Control"]
    assert verified.status_code == 200
    assert "no-store" in verified["Cache-Control"]
    assert row.status == EventRegistration.Status.CONFIRMED


def test_invalid_anonymous_registration_response_is_private(client):
    item = event()

    response = client.post(
        reverse("event_register", kwargs={"slug": item.slug}),
        {"email": "guest@example.com"},
    )

    assert response.status_code == 400
    assert "no-store" in response["Cache-Control"]
    assert "Cookie" in response["Vary"]


def test_anonymous_management_token_cancels_once(client):
    item = event()
    row = EventRegistration.objects.create(
        event=item,
        original_email="guest@example.com",
        normalized_email="guest@example.com",
        status=EventRegistration.Status.CONFIRMED,
    )
    token = generate_registration_token(row, action="manage")

    confirm = client.get(reverse("event_registration_manage"), {"token": token})
    cancelled = client.post(reverse("event_registration_manage"), {"token": token})

    row.refresh_from_db()
    assert confirm.status_code == 200
    assert cancelled.status_code == 200
    assert row.status == EventRegistration.Status.CANCELLED


def test_feedback_route_enforces_owner_and_event_time(client):
    item = event(
        status="completed",
        start_datetime=timezone.now() - timedelta(hours=2),
        end_datetime=timezone.now() - timedelta(hours=1),
    )
    owner = get_user_model().objects.create_user(email="owner@example.com")
    other = get_user_model().objects.create_user(email="other@example.com")
    registration(item, owner)
    client.force_login(other)

    denied = client.post(
        reverse("event_feedback", kwargs={"slug": item.slug}),
        {"rating": 5, "comment": "Useful"},
    )
    client.force_login(owner)
    saved = client.post(
        reverse("event_feedback", kwargs={"slug": item.slug}),
        {"rating": 5, "comment": "Useful"},
    )

    assert denied.status_code == 404
    assert saved.status_code == 302
    assert EventFeedback.objects.get().rating == 5


def test_calendar_download_uses_public_route_without_authentication(client):
    item = event()

    response = client.get(reverse("event_calendar", kwargs={"slug": item.slug}))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/calendar; charset=utf-8"
    assert b"BEGIN:VCALENDAR" in response.content
