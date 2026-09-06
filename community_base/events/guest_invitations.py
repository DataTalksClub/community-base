from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from community_base.accounts.services.email_resolution import normalize_email, resolve_user_by_email
from community_base.events.models import Event, EventRegistration
from community_base.events.registration import _emit_after_commit
from community_base.events.signals import event_registered
from community_base.mail import send


@dataclass(frozen=True)
class GuestInvitationResult:
    registration: EventRegistration
    delivery: object
    created: bool


@transaction.atomic
def invite_guest(event, email):
    event = Event.objects.select_for_update().get(pk=event.pk)
    if not event.is_upcoming:
        raise ValidationError("Guests can be invited only to upcoming events.")
    normalized = normalize_email(email)
    validate_email(normalized)
    if event.hosts.filter(email__iexact=normalized).exists():
        raise ValidationError("An event host cannot be invited as a guest.")
    user = resolve_user_by_email(normalized)
    registration = (
        EventRegistration.objects.select_for_update()
        .filter(event=event, normalized_email=normalized)
        .first()
    )
    created = registration is None
    if created:
        registration = EventRegistration.objects.create(
            event=event,
            user=user,
            original_email=str(email).strip(),
            normalized_email=normalized,
            status=EventRegistration.Status.CONFIRMED,
            verified_at=timezone.now(),
        )
        _emit_after_commit(event_registered, registration)
    elif registration.status != EventRegistration.Status.CONFIRMED:
        registration.status = EventRegistration.Status.CONFIRMED
        registration.version += 1
        registration.user = registration.user or user
        registration.verified_at = timezone.now()
        registration.cancelled_at = None
        registration.save(
            update_fields=(
                "status",
                "version",
                "user",
                "verified_at",
                "cancelled_at",
                "updated_at",
            )
        )
        _emit_after_commit(event_registered, registration)
    delivery = send(
        "events.guest_invitation",
        normalized,
        {
            "registration_id": str(registration.pk),
            "registration_version": registration.version,
            "event_id": event.pk,
            "event_title": event.title,
        },
        f"events.guest:{registration.pk}:{registration.version}",
        category="events",
        user=registration.user,
        related=registration,
    )
    return GuestInvitationResult(registration, delivery, created)
