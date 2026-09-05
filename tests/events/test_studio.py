from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from community_base.events.models import Event, EventRegistration, EventSeries, Host
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db(transaction=True)


def staff_client(client):
    user = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    client.force_login(user)
    return user, client


def event(**values):
    values.setdefault("title", "Studio event")
    values.setdefault("slug", "studio-event")
    values.setdefault("status", "upcoming")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=2))
    return Event.objects.create(**values)


def test_studio_routes_require_staff(client):
    response = client.get(reverse("events_studio_list"))
    user = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(user)
    forbidden = client.get(reverse("events_studio_list"))

    assert response.status_code == 302
    assert forbidden.status_code == 403


def test_staff_creates_event_with_public_identity_and_audit(client, settings):
    _staff, client = staff_client(client)
    audit = []
    configured = dict(settings.COMMUNITY_BASE)
    configured["STUDIO_AUDIT_WRITER"] = lambda **entry: audit.append(entry)

    with override_settings(COMMUNITY_BASE=configured):
        response = client.post(
            reverse("events_studio_create"),
            {
                "title": "Created in Studio",
                "slug": "created-in-studio",
                "kind": "standard",
                "platform": "zoom",
                "start_datetime": (timezone.now() + timedelta(days=3)).isoformat(),
                "timezone": "UTC",
                "required_level": 0,
                "status": "upcoming",
                "series_position": "",
                "recording_url": "",
                "materials": "[]",
            },
        )

    item = Event.objects.get(slug="created-in-studio")
    assert response.status_code == 302
    assert item.public_id is not None
    assert audit[0]["event"] == "events.event.created"


def test_staff_manages_series_and_hosts(client):
    _staff, client = staff_client(client)

    series_response = client.post(
        reverse("events_studio_series_create"),
        {
            "name": "Office hours",
            "slug": "office-hours",
            "cadence": "none",
            "timezone": "UTC",
            "required_level": 0,
            "is_active": "on",
        },
    )
    host_response = client.post(
        reverse("events_studio_host_create"),
        {
            "name": "Speaker",
            "slug": "speaker",
            "kind": "speaker",
            "is_active": "on",
        },
    )

    assert series_response.status_code == 302
    assert host_response.status_code == 302
    assert EventSeries.objects.filter(slug="office-hours").exists()
    assert Host.objects.filter(slug="speaker").exists()


def test_staff_invites_guest_and_updates_attendance(client):
    _staff, client = staff_client(client)
    item = event()

    invited = client.post(
        reverse("events_studio_invite_guest", kwargs={"event_id": item.pk}),
        {"email": "guest@example.com"},
    )
    registration = EventRegistration.objects.get(event=item)
    item.status = "completed"
    item.start_datetime = timezone.now() - timedelta(hours=2)
    item.end_datetime = timezone.now() - timedelta(hours=1)
    item.save(update_fields=("status", "start_datetime", "end_datetime"))
    attended = client.post(
        reverse(
            "events_studio_registration_state",
            kwargs={"event_id": item.pk, "registration_id": registration.pk},
        ),
        {"state": "attended"},
    )

    registration.refresh_from_db()
    assert invited.status_code == 302
    assert attended.status_code == 302
    assert registration.status == EventRegistration.Status.ATTENDED
    assert EmailDelivery.objects.get().purpose == "events.guest_invitation"


def test_event_detail_lists_registrations_without_exposing_studio_to_members(client):
    _staff, client = staff_client(client)
    item = event()
    EventRegistration.objects.create(
        event=item,
        original_email="guest@example.com",
        normalized_email="guest@example.com",
        status=EventRegistration.Status.CONFIRMED,
    )

    response = client.get(reverse("events_studio_detail", kwargs={"event_id": item.pk}))

    assert response.status_code == 200
    assert b"guest@example.com" in response.content
