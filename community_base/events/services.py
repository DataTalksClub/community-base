from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from community_base.events.models import Event, EventAlias, EventPublicIdSequence, EventSeries
from community_base.events.registration import enroll_series_registrants_in_event
from community_base.events.signals import event_cancelled, event_published, event_rescheduled
from community_base.kernel.access import can_access
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve


def _locked_public_id_sequence():
    sequence, _created = EventPublicIdSequence.objects.get_or_create(
        pk=1, defaults={"next_public_id": 1}
    )
    return EventPublicIdSequence.objects.select_for_update().get(pk=sequence.pk)


def can_register_for_event(user, event):
    return event.status == "upcoming" and event.is_upcoming and can_access(user, event)


def host_profile_url(host):
    configured = get("HOST_PROFILE_RESOLVER")
    if configured is None:
        return None
    callback = resolve(configured) if isinstance(configured, str) else configured
    value = callback(host)
    return str(value) if value else None


@transaction.atomic
def allocate_public_id(event):
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.public_id is not None:
        return event.public_id
    sequence = _locked_public_id_sequence()
    candidate = sequence.next_public_id
    while Event.objects.filter(public_id=candidate).exists():
        candidate += 1
    Event.objects.filter(pk=event.pk, public_id__isnull=True).update(public_id=candidate)
    sequence.next_public_id = candidate + 1
    sequence.save(update_fields=("next_public_id", "updated_at"))
    return candidate


@transaction.atomic
def reserve_public_id(event, public_id):
    if not isinstance(public_id, int) or isinstance(public_id, bool) or public_id < 1:
        raise ValidationError("public_id must be a positive integer")
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.public_id not in {None, public_id}:
        raise ValidationError("Event public_id is immutable.")
    if Event.objects.exclude(pk=event.pk).filter(public_id=public_id).exists():
        raise ValidationError("public_id is already allocated")
    Event.objects.filter(pk=event.pk).update(public_id=public_id)
    sequence = _locked_public_id_sequence()
    if sequence.next_public_id <= public_id:
        sequence.next_public_id = public_id + 1
        sequence.save(update_fields=("next_public_id", "updated_at"))
    return public_id


def add_alias(event, source_path, *, kind="reviewed", reason="Reviewed legacy path", **source):
    alias = EventAlias(
        event=event,
        source_path=str(source_path),
        kind=kind,
        reason=str(reason)[:255],
        source_repository=str(source.get("source_repository", ""))[:255],
        source_revision=str(source.get("source_revision", ""))[:64],
        source_key=str(source.get("source_key", ""))[:512],
    )
    alias.full_clean()
    alias.save()
    return alias


def _after_commit(signal, event, **values):
    transaction.on_commit(lambda: signal.send(sender=Event, event=event, **values))


@transaction.atomic
def publish_event(event):
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.status not in {"draft", "upcoming"}:
        raise ValidationError("Only draft or upcoming events can be published.")
    event.status = "upcoming"
    event.published_at = event.published_at or timezone.now()
    event.save(update_fields=("status", "published_at", "updated_at"))
    event.public_id = allocate_public_id(event)
    enroll_series_registrants_in_event(event)
    _after_commit(event_published, event)
    return event


@transaction.atomic
def cancel_event(event, *, reason=""):
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.status in {"completed", "archived"}:
        raise ValidationError("Completed or archived events cannot be cancelled.")
    event.status = "cancelled"
    event.ics_sequence += 1
    event.save(update_fields=("status", "ics_sequence", "updated_at"))
    _after_commit(event_cancelled, event, reason=str(reason)[:500])
    return event


@transaction.atomic
def reschedule_event(event, *, start_datetime, end_datetime=None, reason=""):
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.status in {"completed", "cancelled", "archived"}:
        raise ValidationError("Closed events cannot be rescheduled.")
    if end_datetime is not None and end_datetime < start_datetime:
        raise ValidationError("Event end must not precede its start.")
    old_start = event.start_datetime
    old_end = event.end_datetime
    event.start_datetime = start_datetime
    event.end_datetime = end_datetime
    event.ics_sequence += 1
    event.save(update_fields=("start_datetime", "end_datetime", "ics_sequence", "updated_at"))
    _after_commit(
        event_rescheduled,
        event,
        old_start=old_start,
        old_end=old_end,
        reason=str(reason)[:500],
    )
    return event


@transaction.atomic
def create_weekly_occurrences(series, *, first_date, count, duration=timedelta(hours=1)):
    series = EventSeries.objects.select_for_update().get(pk=series.pk)
    if series.cadence != "weekly" or series.day_of_week is None or series.start_time is None:
        raise ValidationError("Series must define a weekly cadence.")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 104:
        raise ValidationError("count must be between 1 and 104")
    if duration <= timedelta(0):
        raise ValidationError("duration must be positive")
    try:
        zone = ZoneInfo(series.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValidationError("Series timezone is invalid.") from error
    days_ahead = (series.day_of_week - first_date.weekday()) % 7
    first_day = first_date + timedelta(days=days_ahead)
    created = []
    next_position = (
        series.events.order_by("-series_position").values_list("series_position", flat=True).first()
        or 0
    ) + 1
    for offset in range(count):
        local_start = datetime.combine(
            first_day + timedelta(days=7 * offset), series.start_time, zone
        )
        position = next_position + offset
        created.append(
            Event.objects.create(
                event_series=series,
                series_position=position,
                title=f"{series.name} #{position}",
                slug=slugify(f"{series.name}-{position}")[:70],
                start_datetime=local_start,
                end_datetime=local_start + duration,
                timezone=series.timezone,
                required_level=series.required_level,
                status="draft",
            )
        )
    return tuple(created)
