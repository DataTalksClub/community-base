from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.accounts.services.email_resolution import normalize_email
from community_base.events.models import (
    Event,
    EventRegistration,
    EventSeries,
    SeriesOccurrenceOptOut,
    SeriesRegistration,
)
from community_base.events.signals import event_registered, event_unregistered
from community_base.kernel.access import can_access


@dataclass(frozen=True)
class SeriesEnrollmentSummary:
    registered: int
    already_registered: int
    no_access: int
    opted_out: int
    total_occurrences: int


def _require_member(user):
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Authentication is required to register.")


def _require_available(event, user):
    if not event.is_upcoming:
        raise ValidationError("Event registration is not open.")
    if not can_access(user, event):
        raise PermissionDenied("This registration requires additional access.")


def _emit_after_commit(signal, registration):
    transaction.on_commit(
        lambda: signal.send(
            sender=EventRegistration,
            registration=registration,
            event=registration.event,
            user=registration.user,
        )
    )


@transaction.atomic
def register_for_event(event, user):
    _require_member(user)
    event = Event.objects.select_for_update().get(pk=event.pk)
    _require_available(event, user)
    email = normalize_email(user.email)
    registration = (
        EventRegistration.objects.select_for_update()
        .filter(event=event, normalized_email=email)
        .first()
    )
    now = timezone.now()
    changed = False
    if registration is None:
        registration = EventRegistration.objects.create(
            event=event,
            user=user,
            original_email=user.email,
            normalized_email=email,
            status=EventRegistration.Status.CONFIRMED,
            verified_at=now,
        )
        changed = True
    else:
        if registration.user_id not in {None, user.pk}:
            raise ValidationError("Registration email belongs to another member.")
        if registration.status != EventRegistration.Status.CONFIRMED:
            registration.version += 1
            registration.status = EventRegistration.Status.CONFIRMED
            registration.user = user
            registration.original_email = user.email
            registration.verified_at = now
            registration.cancelled_at = None
            registration.attended_at = None
            registration.save(
                update_fields=(
                    "version",
                    "status",
                    "user",
                    "original_email",
                    "verified_at",
                    "cancelled_at",
                    "attended_at",
                    "updated_at",
                )
            )
            changed = True
        elif registration.user_id is None:
            registration.user = user
            registration.save(update_fields=("user", "updated_at"))
    SeriesOccurrenceOptOut.objects.filter(event=event, user=user).delete()
    if changed:
        _emit_after_commit(event_registered, registration)
    return registration, changed


@transaction.atomic
def unregister_from_event(event, user):
    _require_member(user)
    registration = (
        EventRegistration.objects.select_for_update().filter(event=event, user=user).first()
    )
    if registration is None or registration.status == EventRegistration.Status.CANCELLED:
        return registration, False
    if registration.status == EventRegistration.Status.ATTENDED:
        raise ValidationError("An attended registration cannot be cancelled.")
    registration.status = EventRegistration.Status.CANCELLED
    registration.version += 1
    registration.cancelled_at = timezone.now()
    registration.save(update_fields=("status", "version", "cancelled_at", "updated_at"))
    if (
        event.event_series_id
        and SeriesRegistration.objects.filter(series_id=event.event_series_id, user=user).exists()
    ):
        SeriesOccurrenceOptOut.objects.get_or_create(
            event=event,
            user=user,
            defaults={"series_id": event.event_series_id},
        )
    _emit_after_commit(event_unregistered, registration)
    return registration, True


def _eligible_occurrences(series):
    return [
        event
        for event in series.events.exclude(status__in=("draft", "cancelled", "archived"))
        if event.is_upcoming
    ]


@transaction.atomic
def enroll_user_in_series(user, series):
    _require_member(user)
    occurrences = _eligible_occurrences(series)
    opted_out = set(
        SeriesOccurrenceOptOut.objects.filter(user=user, event__in=occurrences).values_list(
            "event_id", flat=True
        )
    )
    counts = {"registered": 0, "already_registered": 0, "no_access": 0, "opted_out": 0}
    for event in occurrences:
        if event.pk in opted_out:
            counts["opted_out"] += 1
        elif not can_access(user, event):
            counts["no_access"] += 1
        else:
            _registration, changed = register_for_event(event, user)
            counts["registered" if changed else "already_registered"] += 1
    return SeriesEnrollmentSummary(**counts, total_occurrences=len(occurrences))


@transaction.atomic
def register_for_series(series, user):
    _require_member(user)
    series = EventSeries.objects.select_for_update().get(pk=series.pk)
    standing, created = SeriesRegistration.objects.get_or_create(series=series, user=user)
    SeriesOccurrenceOptOut.objects.filter(series=series, user=user).delete()
    return standing, created, enroll_user_in_series(user, series)


@transaction.atomic
def unregister_from_series(series, user):
    _require_member(user)
    series = EventSeries.objects.select_for_update().get(pk=series.pk)
    deleted, _details = SeriesRegistration.objects.filter(series=series, user=user).delete()
    SeriesOccurrenceOptOut.objects.filter(series=series, user=user).delete()
    cancelled = 0
    for event in _eligible_occurrences(series):
        _registration, changed = unregister_from_event(event, user)
        cancelled += int(changed)
    return bool(deleted), cancelled


@transaction.atomic
def enroll_series_registrants_in_event(event):
    event = Event.objects.select_for_update().select_related("event_series").get(pk=event.pk)
    if event.event_series is None or not event.is_upcoming:
        return SeriesEnrollmentSummary(0, 0, 0, 0, 1)
    counts = {"registered": 0, "already_registered": 0, "no_access": 0, "opted_out": 0}
    opt_outs = set(
        SeriesOccurrenceOptOut.objects.filter(event=event).values_list("user_id", flat=True)
    )
    for standing in event.event_series.series_registrations.select_related("user"):
        if standing.user_id in opt_outs:
            counts["opted_out"] += 1
        elif not can_access(standing.user, event):
            counts["no_access"] += 1
        else:
            _registration, changed = register_for_event(event, standing.user)
            counts["registered" if changed else "already_registered"] += 1
    return SeriesEnrollmentSummary(**counts, total_occurrences=1)


@transaction.atomic
def expire_pending_registrations(*, at=None):
    at = at or timezone.now()
    registrations = list(
        EventRegistration.objects.select_for_update().filter(
            status=EventRegistration.Status.PENDING_VERIFICATION,
            verification_expires_at__lte=at,
        )
    )
    for registration in registrations:
        registration.status = EventRegistration.Status.EXPIRED
        registration.version += 1
        registration.save(update_fields=("status", "version", "updated_at"))
    return len(registrations)


@transaction.atomic
def record_attendance(registration, *, attended, at=None):
    registration = (
        EventRegistration.objects.select_for_update()
        .select_related("event", "user")
        .get(pk=registration.pk)
    )
    transition_at = at or timezone.now()
    if transition_at < registration.event.effective_end_datetime:
        raise ValidationError("Attendance can be recorded only after the event ends.")
    target = EventRegistration.Status.ATTENDED if attended else EventRegistration.Status.NO_SHOW
    if registration.status == target:
        return registration, False
    if registration.status != EventRegistration.Status.CONFIRMED:
        raise ValidationError("Only confirmed registrations can receive attendance state.")
    registration.status = target
    registration.attended_at = transition_at if attended else None
    registration.save(update_fields=("status", "attended_at", "updated_at"))
    return registration, True
