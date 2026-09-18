import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
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


def configured(settings, **values):
    result = dict(settings.COMMUNITY_BASE)
    result.update(values)
    return result


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
    assert "public_url" not in fetched.json()["registration"]
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


@pytest.mark.parametrize(
    ("style", "expected_path"),
    [("slug", "/events/api-public/"), ("public_id", "/events/42/api-public/")],
)
def test_event_public_url_is_canonical_for_list_detail_create_and_update(
    client, settings, style, expected_path
):
    staff = user(f"{style}-staff@example.com", is_staff=True)
    item = event(slug="api-public", public_id=42)
    client.force_login(staff)

    with override_settings(
        COMMUNITY_BASE=configured(settings, EVENT_URL_STYLE=style, SITE_URL="https://example.org/")
    ):
        listed = client.get("/api/v1/events", HTTP_HOST="testserver")
        detail = client.get(f"/api/v1/events/{item.pk}", HTTP_HOST="testserver")
        created = request(
            client,
            "post",
            "/api/v1/events",
            {
                "title": f"Created {style}",
                "slug": f"created-{style}",
                "kind": "standard",
                "platform": "zoom",
                "start_datetime": (timezone.now() + timedelta(days=2)).isoformat(),
                "timezone": "UTC",
                "required_level": 0,
                "status": "upcoming",
                "materials": [],
            },
        )
        updated = request(client, "patch", f"/api/v1/events/{item.pk}", {"title": "Renamed"})

    expected = f"https://example.org{expected_path}"
    listed_item = next(row for row in listed.json()["results"] if row["id"] == item.pk)
    assert listed_item["url"] == expected_path
    assert listed_item["public_url"] == expected
    assert detail.json()["event"]["url"] == expected_path
    assert detail.json()["event"]["public_url"] == expected
    assert created.status_code == 201
    created_item = created.json()["event"]
    assert created_item["public_url"] == f"https://example.org{created_item['url']}"
    assert updated.json()["event"]["url"] == expected_path
    assert updated.json()["event"]["public_url"] == expected


def test_event_public_url_is_null_for_non_public_states_and_private_rows(client, settings):
    staff = user("visibility-staff@example.com", is_staff=True)
    draft = event(slug="draft-event", status="draft")
    cancelled = event(slug="cancelled-event", status="cancelled")
    completed = event(slug="completed-event", status="completed")
    client.force_login(staff)

    with override_settings(COMMUNITY_BASE=configured(settings, SITE_URL="https://example.org")):
        listing = client.get("/api/v1/events")
        draft_detail = client.get(f"/api/v1/events/{draft.pk}")
        cancelled_detail = client.get(f"/api/v1/events/{cancelled.pk}")
        completed_detail = client.get(f"/api/v1/events/{completed.pk}")

    rows = {row["id"]: row for row in listing.json()["results"]}
    assert rows[draft.pk]["url"] is None
    assert rows[draft.pk]["public_url"] is None
    assert rows[cancelled.pk]["public_url"] is None
    assert draft_detail.json()["event"]["public_url"] is None
    assert cancelled_detail.json()["event"]["public_url"] is None
    assert completed_detail.json()["event"]["public_url"] == (
        f"https://example.org{completed.get_absolute_url()}"
    )


def test_event_public_url_is_null_when_configured_route_cannot_reach_event(client, settings):
    staff = user("unreachable-staff@example.com", is_staff=True)
    item = event(slug="missing-public-id")
    client.force_login(staff)

    with override_settings(
        COMMUNITY_BASE=configured(
            settings, EVENT_URL_STYLE="public_id", SITE_URL="https://example.org"
        )
    ):
        response = client.get(f"/api/v1/events/{item.pk}")

    assert response.json()["event"]["url"] is None
    assert response.json()["event"]["public_url"] is None


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
            "visibility": "public",
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
    assert "public_url" not in series.json()["event_series"]
    assert "public_url" not in host.json()["host"]
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

    event_item = document["paths"]["/api/v1/events/{event_id}"]["get"]
    event_schema = event_item["responses"]["200"]["content"]["application/json"]["schema"]
    assert event_schema["properties"]["event"]["properties"]["public_url"] == {
        "description": "Absolute canonical public URL, when the event is public.",
        "format": "uri",
        "type": ["string", "null"],
    }
    list_schema = document["paths"]["/api/v1/events"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert list_schema["properties"]["results"]["items"]["properties"]["public_url"]["type"] == [
        "string",
        "null",
    ]
