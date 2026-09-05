import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from community_base.api.openapi import build_document
from community_base.events.models import Event, EventFeedback, EventRegistration, EventSeries, Host

pytestmark = pytest.mark.django_db(transaction=True)


def event(**values):
    values.setdefault("title", "API event")
    values.setdefault("slug", "api-event")
    values.setdefault("status", "upcoming")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=2))
    return Event.objects.create(**values)


def user(email, **values):
    return get_user_model().objects.create_user(email=email, **values)


def request(client, method, path, payload=None):
    return getattr(client, method)(
        path,
        data=json.dumps(payload) if payload is not None else None,
        content_type="application/json",
    )


def test_event_api_requires_session_and_staff_for_management(client):
    anonymous = client.get("/api/v1/events")
    client.force_login(user("member@example.com"))
    member = client.get("/api/v1/events")

    assert anonymous.status_code == 401
    assert member.status_code == 403
    assert anonymous.json()["error"]["code"] == "authentication_required"
    assert "no-store" in anonymous["Cache-Control"]


def test_member_registration_api_is_owner_scoped(client):
    item = event()
    owner = user("owner@example.com")
    other = user("other@example.com")
    client.force_login(owner)

    created = request(client, "post", f"/api/v1/events/{item.pk}/registration", {})
    fetched = client.get(f"/api/v1/events/{item.pk}/registration")
    client.force_login(other)
    hidden = client.get(f"/api/v1/events/{item.pk}/registration")

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["registration"]["email"] == owner.email
    assert hidden.status_code == 404


def test_member_feedback_api_updates_only_owned_registration(client):
    item = event(
        status="completed",
        start_datetime=timezone.now() - timedelta(hours=2),
        end_datetime=timezone.now() - timedelta(hours=1),
    )
    owner = user("owner@example.com")
    EventRegistration.objects.create(
        event=item,
        user=owner,
        original_email=owner.email,
        normalized_email=owner.email,
        status=EventRegistration.Status.CONFIRMED,
    )
    client.force_login(owner)

    response = request(
        client,
        "put",
        f"/api/v1/events/{item.pk}/feedback",
        {"rating": 5, "comment": "Clear"},
    )

    assert response.status_code == 201
    assert EventFeedback.objects.get().comment == "Clear"


def test_staff_manages_events_and_guest_invitations(client):
    client.force_login(user("staff@example.com", is_staff=True))
    starts = timezone.now() + timedelta(days=2)

    created = request(
        client,
        "post",
        "/api/v1/events",
        {
            "title": "Created over API",
            "slug": "created-over-api",
            "kind": "standard",
            "platform": "zoom",
            "start_datetime": starts.isoformat(),
            "timezone": "UTC",
            "required_level": 0,
            "status": "upcoming",
            "materials": [],
        },
    )
    item = Event.objects.get(slug="created-over-api")
    invited = request(
        client,
        "post",
        f"/api/v1/events/{item.pk}/guest-invitations",
        {"email": "guest@example.com"},
    )
    zoom = request(
        client,
        "post",
        f"/api/v1/events/{item.pk}/zoom-sync",
        {"action": "create"},
    )
    recording = request(
        client,
        "post",
        f"/api/v1/events/{item.pk}/recording-processing",
        {"recording_reference": "zoom-recording-42"},
    )
    listed = client.get(f"/api/v1/events/{item.pk}/registrations")
    updated = request(
        client,
        "patch",
        f"/api/v1/events/{item.pk}",
        {"title": "Updated over API"},
    )

    assert created.status_code == 201
    assert created.json()["event"]["public_id"] is not None
    assert invited.status_code == 201
    assert zoom.status_code == 201
    assert recording.status_code == 201
    assert listed.json()["results"][0]["email"] == "guest@example.com"
    assert updated.status_code == 200
    assert updated.json()["event"]["title"] == "Updated over API"


def test_staff_manages_series_and_hosts(client):
    client.force_login(user("staff@example.com", is_staff=True))

    series = request(
        client,
        "post",
        "/api/v1/event-series",
        {
            "name": "Office hours",
            "slug": "office-hours",
            "cadence": "none",
            "timezone": "UTC",
            "required_level": 0,
            "is_active": True,
        },
    )
    host = request(
        client,
        "post",
        "/api/v1/event-hosts",
        {"name": "Speaker", "slug": "speaker", "kind": "speaker", "is_active": True},
    )

    assert series.status_code == 201
    assert host.status_code == 201
    assert EventSeries.objects.filter(slug="office-hours").exists()
    assert Host.objects.filter(slug="speaker").exists()


def test_staff_api_rejects_closed_event_reactivation(client):
    client.force_login(user("staff@example.com", is_staff=True))
    item = event(status="completed")

    response = request(
        client,
        "patch",
        f"/api/v1/events/{item.pk}",
        {"status": "upcoming"},
    )

    item.refresh_from_db()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert item.status == "completed"


def test_event_routes_are_published_in_openapi():
    document = build_document()

    assert document["paths"]["/api/v1/events"]["post"]["security"] == [{"cookieAuth": []}]
    assert "/api/v1/events/{event_id}/registration" in document["paths"]
    assert "/api/v1/events/{event_id}/guest-invitations" in document["paths"]
    assert "/api/v1/events/{event_id}/zoom-sync" in document["paths"]
    assert "/api/v1/events/{event_id}/recording-processing" in document["paths"]
    assert "/api/v1/event-series/{series_id}" in document["paths"]
    assert "/api/v1/event-hosts/{host_id}" in document["paths"]
