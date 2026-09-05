import uuid
from datetime import timedelta

import requests
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from community_base.events.integrations.hooks import process_recording
from community_base.events.integrations.zoom import (
    ZoomAmbiguousError,
    ZoomClient,
    ZoomConfigurationError,
    ZoomDisabled,
    ZoomRejected,
    ZoomTemporaryError,
    meeting_request_for_event,
)
from community_base.events.models import (
    Event,
    EventIntegrationAttempt,
    EventRegistration,
    EventReminder,
)
from community_base.events.registration import expire_pending_registrations
from community_base.events.reminders import (
    claim_due_reminders,
    complete_reminder,
    plan_event_reminders,
)
from community_base.jobs.dispatch import dispatch_after_commit
from community_base.jobs.registry import JobContext, JobPayload, register_handler, schedule
from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.mail import send


def _uuid(value, code):
    if not isinstance(value, str):
        raise PermanentJobError(code)
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise PermanentJobError(code) from error


def _positive_id(value, code):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PermanentJobError(code)
    return value


def _begin_zoom_attempt(context, event, action):
    operation = f"zoom.{action}"
    terminal_error = None
    with transaction.atomic():
        attempt, _created = EventIntegrationAttempt.objects.select_for_update().get_or_create(
            pk=context.job_id,
            defaults={"event": event, "operation": operation},
        )
        if attempt.event_id != event.pk or attempt.operation != operation:
            raise PermanentJobError("event_zoom_attempt_conflict")
        if attempt.status == EventIntegrationAttempt.Status.SUCCEEDED:
            return attempt, True
        if attempt.status in {
            EventIntegrationAttempt.Status.PROVIDER_REQUESTED,
            EventIntegrationAttempt.Status.AMBIGUOUS,
        }:
            attempt.status = EventIntegrationAttempt.Status.AMBIGUOUS
            attempt.save(update_fields=("status", "updated_at"))
            terminal_error = "zoom_outcome_ambiguous"
        elif attempt.status == EventIntegrationAttempt.Status.REJECTED:
            terminal_error = "zoom_request_rejected"
    if terminal_error:
        raise PermanentJobError(terminal_error)
    return attempt, False


def _mark_zoom_provider_requested(attempt):
    updated = EventIntegrationAttempt.objects.filter(
        pk=attempt.pk, status=EventIntegrationAttempt.Status.STARTING
    ).update(status=EventIntegrationAttempt.Status.PROVIDER_REQUESTED, updated_at=timezone.now())
    if updated != 1:
        raise PermanentJobError("zoom_outcome_ambiguous")


def _finish_zoom_attempt(attempt, *, status, result_reference=""):
    EventIntegrationAttempt.objects.filter(pk=attempt.pk).update(
        status=status,
        result_reference=str(result_reference)[:255],
        updated_at=timezone.now(),
    )


@register_handler("events.plan_reminders")
def plan_reminders_handler(context: JobContext, payload: JobPayload):
    del context
    if payload:
        raise PermanentJobError("invalid_event_reminder_plan_payload")
    horizon = timezone.now() + timedelta(hours=25)
    for event in Event.objects.filter(status="upcoming", start_datetime__lte=horizon):
        plan_event_reminders(event)
    with transaction.atomic():
        for reminder in claim_due_reminders(limit=500):
            dispatch_after_commit(
                "events.send_reminder",
                f"events.reminder:{reminder.reminder_id}",
                {"reminder_id": reminder.reminder_id},
            )


@register_handler("events.send_reminder")
def send_reminder_handler(context: JobContext, payload: JobPayload):
    del context
    reminder_id = _uuid(payload.get("reminder_id"), "invalid_event_reminder_payload")
    with transaction.atomic():
        reminder = (
            EventReminder.objects.select_for_update()
            .select_related("registration__event", "registration__user")
            .filter(pk=reminder_id)
            .first()
        )
        if reminder is None:
            raise PermanentJobError("event_reminder_not_found")
        if reminder.status in {EventReminder.Status.SENT, EventReminder.Status.SKIPPED}:
            return
        registration = reminder.registration
        if (
            reminder.status != EventReminder.Status.CLAIMED
            or registration.version != reminder.registration_version
            or registration.status != EventRegistration.Status.CONFIRMED
        ):
            raise PermanentJobError("event_reminder_stale")
        delivery = send(
            "events.reminder",
            registration.normalized_email,
            {
                "registration_id": str(registration.pk),
                "registration_version": registration.version,
                "event_id": registration.event_id,
                "event_title": registration.event.title,
                "interval": reminder.interval,
            },
            f"events.reminder:{reminder.pk}",
            category="events",
            user=registration.user,
            related=reminder,
        )
        complete_reminder(reminder.pk, delivery)


@register_handler("events.expire_registration_verifications")
def expire_registration_verifications_handler(context: JobContext, payload: JobPayload):
    del context
    if payload:
        raise PermanentJobError("invalid_event_verification_expiry_payload")
    expire_pending_registrations()


@register_handler("events.sync_zoom")
def sync_zoom_handler(context: JobContext, payload: JobPayload):
    event_id = _positive_id(payload.get("event_id"), "invalid_event_zoom_payload")
    action = payload.get("action")
    if action not in {"create", "update", "delete"}:
        raise PermanentJobError("invalid_event_zoom_payload")
    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        raise PermanentJobError("event_not_found")
    if action == "create" and event.zoom_meeting_id:
        return
    if action != "create" and not event.zoom_meeting_id:
        raise PermanentJobError("event_zoom_meeting_missing")
    attempt, finished = _begin_zoom_attempt(context, event, action)
    if finished:
        return
    try:
        client = ZoomClient()
        if action == "create":
            result = client.create_meeting(
                meeting_request_for_event(event),
                before_mutation=lambda: _mark_zoom_provider_requested(attempt),
            )
            with transaction.atomic():
                locked = Event.objects.select_for_update().get(pk=event.pk)
                if not locked.zoom_meeting_id:
                    locked.zoom_meeting_id = result.meeting_id
                    locked.zoom_join_url = result.join_url
                    locked.save(update_fields=("zoom_meeting_id", "zoom_join_url", "updated_at"))
                _finish_zoom_attempt(
                    attempt,
                    status=EventIntegrationAttempt.Status.SUCCEEDED,
                    result_reference=result.meeting_id,
                )
        elif action == "update":
            client.update_meeting(
                event.zoom_meeting_id,
                meeting_request_for_event(event),
                before_mutation=lambda: _mark_zoom_provider_requested(attempt),
            )
            _finish_zoom_attempt(
                attempt,
                status=EventIntegrationAttempt.Status.SUCCEEDED,
                result_reference=event.zoom_meeting_id,
            )
        else:
            client.delete_meeting(
                event.zoom_meeting_id,
                before_mutation=lambda: _mark_zoom_provider_requested(attempt),
            )
            with transaction.atomic():
                Event.objects.filter(pk=event.pk, zoom_meeting_id=event.zoom_meeting_id).update(
                    zoom_meeting_id="", zoom_join_url="", updated_at=timezone.now()
                )
                _finish_zoom_attempt(
                    attempt,
                    status=EventIntegrationAttempt.Status.SUCCEEDED,
                    result_reference=event.zoom_meeting_id,
                )
    except ZoomTemporaryError as error:
        raise RetryableJobError(error.code) from error
    except ZoomAmbiguousError as error:
        _finish_zoom_attempt(attempt, status=EventIntegrationAttempt.Status.AMBIGUOUS)
        raise PermanentJobError(error.code) from error
    except (ZoomDisabled, ZoomConfigurationError, ZoomRejected) as error:
        _finish_zoom_attempt(attempt, status=EventIntegrationAttempt.Status.REJECTED)
        raise PermanentJobError(error.code) from error


@register_handler("events.process_recording")
def process_recording_handler(context: JobContext, payload: JobPayload):
    del context
    event_id = _positive_id(payload.get("event_id"), "invalid_event_recording_payload")
    reference = payload.get("recording_reference")
    if (
        not isinstance(reference, str)
        or not reference
        or len(reference) > 512
        or "://" in reference
    ):
        raise PermanentJobError("invalid_event_recording_payload")
    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        raise PermanentJobError("event_not_found")
    try:
        process_recording(event, reference)
    except (requests.Timeout, requests.ConnectionError) as error:
        raise RetryableJobError("event_recording_temporarily_unavailable") from error
    except ImproperlyConfigured as error:
        raise PermanentJobError("event_recording_not_configured") from error


schedule(
    "events.plan_reminders",
    "*/15 * * * *",
    {},
    name="events.plan_reminders.every_15_minutes",
)
schedule(
    "events.expire_registration_verifications",
    "*/15 * * * *",
    {},
    name="events.expire_registration_verifications.every_15_minutes",
)
