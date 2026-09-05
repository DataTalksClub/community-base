import re
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.events.models import Event, EventRegistration, EventReminder

DEFAULT_INTERVALS = {"24h": timedelta(hours=24), "20m": timedelta(minutes=20)}
REASON_PATTERN = re.compile(r"^[a-z0-9_]{1,128}$")


@dataclass(frozen=True)
class ReminderJobInput:
    reminder_id: str
    registration_id: str
    registration_version: int
    event_id: int
    interval: str


@transaction.atomic
def plan_event_reminders(event, *, intervals=None):
    event = Event.objects.select_for_update().get(pk=event.pk)
    configured = dict(intervals or DEFAULT_INTERVALS)
    if not configured or any(
        not isinstance(value, timedelta) or value <= timedelta(0) for value in configured.values()
    ):
        raise ValidationError("Reminder intervals must be positive durations.")
    reminders = []
    registrations = event.registrations.filter(status=EventRegistration.Status.CONFIRMED)
    for registration in registrations:
        for interval, delta in configured.items():
            reminder, _created = EventReminder.objects.get_or_create(
                registration=registration,
                registration_version=registration.version,
                interval=str(interval)[:32],
                defaults={"scheduled_for": event.start_datetime - delta},
            )
            reminders.append(reminder)
    return tuple(reminders)


@transaction.atomic
def claim_due_reminders(*, at=None, limit=100):
    at = at or timezone.now()
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValidationError("Reminder claim limit must be between 1 and 1000.")
    candidates = list(
        EventReminder.objects.select_for_update()
        .select_related("registration__event")
        .filter(status=EventReminder.Status.PENDING, scheduled_for__lte=at)
        .order_by("scheduled_for", "id")[:limit]
    )
    claimed = []
    for reminder in candidates:
        registration = reminder.registration
        event = registration.event
        stale_reason = ""
        if registration.version != reminder.registration_version:
            stale_reason = "registration_version_changed"
        elif registration.status != EventRegistration.Status.CONFIRMED:
            stale_reason = "registration_inactive"
        elif event.status != "upcoming" or event.effective_end_datetime <= at:
            stale_reason = "event_inactive"
        if stale_reason:
            reminder.status = EventReminder.Status.SKIPPED
            reminder.reason = stale_reason
            reminder.completed_at = at
            reminder.save(update_fields=("status", "reason", "completed_at", "updated_at"))
            continue
        reminder.status = EventReminder.Status.CLAIMED
        reminder.claimed_at = at
        reminder.save(update_fields=("status", "claimed_at", "updated_at"))
        claimed.append(
            ReminderJobInput(
                reminder_id=str(reminder.pk),
                registration_id=str(registration.pk),
                registration_version=registration.version,
                event_id=event.pk,
                interval=reminder.interval,
            )
        )
    return tuple(claimed)


@transaction.atomic
def complete_reminder(reminder_id, delivery):
    reminder = (
        EventReminder.objects.select_for_update().select_related("registration").get(pk=reminder_id)
    )
    if reminder.status == EventReminder.Status.SENT and reminder.delivery_id == delivery.pk:
        return reminder, False
    if reminder.status != EventReminder.Status.CLAIMED:
        raise ValidationError("Only claimed reminders can be completed.")
    if delivery.recipient_email != reminder.registration.normalized_email:
        raise ValidationError("Reminder delivery recipient does not own the registration.")
    reminder.status = EventReminder.Status.SENT
    reminder.delivery = delivery
    reminder.completed_at = timezone.now()
    reminder.reason = ""
    reminder.save(update_fields=("status", "delivery", "completed_at", "reason", "updated_at"))
    return reminder, True


@transaction.atomic
def fail_reminder(reminder_id, *, reason):
    if not isinstance(reason, str) or not REASON_PATTERN.fullmatch(reason):
        raise ValidationError("Reminder failure reason must be a safe code.")
    reminder = EventReminder.objects.select_for_update().get(pk=reminder_id)
    if reminder.status != EventReminder.Status.CLAIMED:
        raise ValidationError("Only claimed reminders can fail.")
    reminder.status = EventReminder.Status.FAILED
    reminder.reason = reason
    reminder.completed_at = timezone.now()
    reminder.save(update_fields=("status", "reason", "completed_at", "updated_at"))
    return reminder
