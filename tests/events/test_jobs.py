from datetime import timedelta

import pytest
import requests
from django.contrib.auth import get_user_model
from django.utils import timezone

from community_base.events import jobs
from community_base.events.integrations.zoom import (
    ZoomAmbiguousError,
    ZoomMeetingResult,
    ZoomTemporaryError,
)
from community_base.events.models import Event, EventReminder
from community_base.events.registration import register_for_event
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import registered_handler_names, registered_schedules
from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db


def event(**values):
    values.setdefault("title", "Community event")
    values.setdefault("slug", "community-event")
    values.setdefault("start_datetime", timezone.now() + timedelta(hours=23))
    values.setdefault("status", "upcoming")
    values.setdefault("required_level", 5)
    return Event.objects.create(**values)


def registration():
    user = get_user_model().objects.create_user(email="member@example.com")
    return register_for_event(event(), user)[0]


def test_event_handlers_and_schedules_are_registered():
    names = registered_handler_names()
    schedules = {item.handler: item.cron for item in registered_schedules()}

    assert {
        "events.plan_reminders",
        "events.send_reminder",
        "events.expire_registration_verifications",
        "events.sync_zoom",
        "events.process_recording",
    } <= set(names)
    assert schedules["events.plan_reminders"] == "*/15 * * * *"
    assert schedules["events.expire_registration_verifications"] == "*/15 * * * *"


def test_reminder_plan_commits_claim_and_scalar_job_input_together():
    item = registration()

    jobs.plan_reminders_handler(None, {})

    reminder = EventReminder.objects.get(interval="24h")
    intent = JobIntent.objects.get(handler="events.send_reminder")
    assert reminder.status == EventReminder.Status.CLAIMED
    assert intent.payload == {"reminder_id": str(reminder.pk)}
    assert item.normalized_email not in str(intent.payload)


def test_reminder_handler_creates_one_logical_delivery_and_is_idempotent():
    registration()
    jobs.plan_reminders_handler(None, {})
    reminder = EventReminder.objects.get(interval="24h")

    jobs.send_reminder_handler(None, {"reminder_id": str(reminder.pk)})
    jobs.send_reminder_handler(None, {"reminder_id": str(reminder.pk)})

    reminder.refresh_from_db()
    assert reminder.status == EventReminder.Status.SENT
    assert reminder.delivery.purpose == "events.reminder"
    assert EmailDelivery.objects.filter(purpose="events.reminder").count() == 1


def test_suppressed_reminder_is_terminal_without_a_delivery_job(settings):
    configured = dict(settings.COMMUNITY_BASE)
    configured["MAIL_PREFERENCE_RESOLVER"] = lambda **_kwargs: "events_suppressed"
    settings.COMMUNITY_BASE = configured
    registration()
    jobs.plan_reminders_handler(None, {})
    reminder = EventReminder.objects.get(interval="24h")

    jobs.send_reminder_handler(None, {"reminder_id": str(reminder.pk)})

    reminder.refresh_from_db()
    assert reminder.status == EventReminder.Status.SKIPPED
    assert reminder.reason == "events_suppressed"
    assert reminder.delivery.job is None


def test_zoom_create_job_persists_result_once(monkeypatch):
    item = event(required_level=0)
    calls = []

    class Client:
        def create_meeting(self, request):
            calls.append(request)
            return ZoomMeetingResult("123", "https://zoom.example.com/j/123")

    monkeypatch.setattr(jobs, "ZoomClient", Client)
    payload = {"event_id": item.pk, "action": "create"}

    jobs.sync_zoom_handler(None, payload)
    jobs.sync_zoom_handler(None, payload)

    item.refresh_from_db()
    assert item.zoom_meeting_id == "123"
    assert item.zoom_join_url == "https://zoom.example.com/j/123"
    assert len(calls) == 1


def test_zoom_retry_and_ambiguous_states_map_to_job_outcomes(monkeypatch):
    item = event(required_level=0)

    class TemporaryClient:
        def create_meeting(self, request):
            del request
            raise ZoomTemporaryError("temporary")

    monkeypatch.setattr(jobs, "ZoomClient", TemporaryClient)
    with pytest.raises(RetryableJobError, match="zoom_temporarily_unavailable"):
        jobs.sync_zoom_handler(None, {"event_id": item.pk, "action": "create"})

    class AmbiguousClient:
        def create_meeting(self, request):
            del request
            raise ZoomAmbiguousError("unknown result")

    monkeypatch.setattr(jobs, "ZoomClient", AmbiguousClient)
    with pytest.raises(PermanentJobError, match="zoom_outcome_ambiguous"):
        jobs.sync_zoom_handler(None, {"event_id": item.pk, "action": "create"})


def test_recording_job_uses_opaque_reference_and_maps_disabled_configuration(settings):
    item = event(required_level=0)
    with pytest.raises(PermanentJobError, match="event_recording_not_configured"):
        jobs.process_recording_handler(
            None,
            {"event_id": item.pk, "recording_reference": "recording-42"},
        )

    configured = dict(settings.COMMUNITY_BASE)
    configured["EVENT_RECORDING_PROCESSOR"] = lambda _event, _reference: {
        "recording_url": "https://recordings.example.com/event.mp4"
    }
    settings.COMMUNITY_BASE = configured
    jobs.process_recording_handler(
        None,
        {"event_id": item.pk, "recording_reference": "recording-42"},
    )
    item.refresh_from_db()
    assert item.recording_url == "https://recordings.example.com/event.mp4"

    with pytest.raises(PermanentJobError, match="invalid_event_recording_payload"):
        jobs.process_recording_handler(
            None,
            {"event_id": item.pk, "recording_reference": "https://secret.example.com/video"},
        )


def test_recording_timeout_is_retryable_without_exposing_provider_data(settings):
    item = event(required_level=0)

    def timeout(_event, _reference):
        raise requests.Timeout("https://provider.example.com?token=secret")

    configured = dict(settings.COMMUNITY_BASE)
    configured["EVENT_RECORDING_PROCESSOR"] = timeout
    settings.COMMUNITY_BASE = configured

    with pytest.raises(
        RetryableJobError, match="event_recording_temporarily_unavailable"
    ) as captured:
        jobs.process_recording_handler(
            None,
            {"event_id": item.pk, "recording_reference": "recording-42"},
        )
    assert "provider.example" not in str(captured.value)
