from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from community_base.accounts.services.email_resolution import normalize_email
from community_base.events.models import Event, EventRegistration
from community_base.events.registration import _emit_after_commit
from community_base.events.signals import event_registered, event_unregistered
from community_base.events.tokens import RegistrationTokenError, load_registration_token
from community_base.kernel.access import LEVEL_OPEN
from community_base.mail import send


@dataclass(frozen=True)
class AnonymousRegistrationResult:
    registration: EventRegistration
    delivery: object | None
    changed: bool


def _registration_from_token(token, action):
    payload = load_registration_token(token, action=action)
    registration = (
        EventRegistration.objects.select_for_update()
        .select_related("event", "user")
        .filter(pk=payload["registration_id"])
        .first()
    )
    if registration is None or registration.version != payload["registration_version"]:
        raise RegistrationTokenError("invalid")
    return registration


@transaction.atomic
def request_anonymous_registration(
    event,
    email,
    *,
    display_name="",
    visitor_timezone="",
    privacy_notice_version="",
    newsletter_consent=None,
    newsletter_consent_version="",
    newsletter_consent_source="",
    acquisition_metadata=None,
    abuse_metadata=None,
):
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.required_level != LEVEL_OPEN or not event.is_upcoming:
        raise ValidationError("Anonymous registration is not available for this event.")
    original_email = str(email).strip()
    normalized_email = normalize_email(original_email)
    validate_email(normalized_email)
    now = timezone.now()
    registration = (
        EventRegistration.objects.select_for_update()
        .filter(event=event, normalized_email=normalized_email)
        .first()
    )
    changed = False
    if registration is None:
        registration = EventRegistration.objects.create(
            event=event,
            original_email=original_email,
            normalized_email=normalized_email,
            display_name=str(display_name).strip()[:200],
            timezone=str(visitor_timezone).strip()[:100],
            privacy_notice_version=str(privacy_notice_version)[:40],
            privacy_acknowledged_at=now if privacy_notice_version else None,
            newsletter_consent=newsletter_consent,
            newsletter_consent_version=str(newsletter_consent_version)[:40],
            newsletter_consent_source=str(newsletter_consent_source)[:80],
            newsletter_consented_at=now if newsletter_consent is not None else None,
            acquisition_metadata=dict(acquisition_metadata or {}),
            abuse_metadata=dict(abuse_metadata or {}),
        )
        changed = True
    elif registration.status in {
        EventRegistration.Status.CANCELLED,
        EventRegistration.Status.EXPIRED,
    }:
        registration.version += 1
        registration.status = EventRegistration.Status.PENDING_VERIFICATION
        registration.original_email = original_email
        registration.display_name = str(display_name).strip()[:200]
        registration.timezone = str(visitor_timezone).strip()[:100]
        registration.cancelled_at = None
        registration.verified_at = None
        registration.save(
            update_fields=(
                "version",
                "status",
                "original_email",
                "display_name",
                "timezone",
                "cancelled_at",
                "verified_at",
                "updated_at",
            )
        )
        changed = True
    if registration.status != EventRegistration.Status.PENDING_VERIFICATION:
        return AnonymousRegistrationResult(registration, None, changed)
    delivery = send(
        "events.verify_registration",
        registration.normalized_email,
        {
            "registration_id": str(registration.pk),
            "registration_version": registration.version,
            "event_id": event.pk,
            "event_title": event.title,
        },
        f"events.verify:{registration.pk}:{registration.version}",
        category="events",
        user=registration.user,
        related=registration,
    )
    return AnonymousRegistrationResult(registration, delivery, changed)


@transaction.atomic
def confirm_anonymous_registration(token):
    registration = _registration_from_token(token, "verify")
    if registration.status == EventRegistration.Status.CONFIRMED:
        return registration, False
    if registration.status != EventRegistration.Status.PENDING_VERIFICATION:
        raise RegistrationTokenError("invalid")
    registration.status = EventRegistration.Status.CONFIRMED
    registration.verified_at = timezone.now()
    registration.save(update_fields=("status", "verified_at", "updated_at"))
    send(
        "events.registration_confirmed",
        registration.normalized_email,
        {
            "registration_id": str(registration.pk),
            "registration_version": registration.version,
            "event_id": registration.event_id,
            "event_title": registration.event.title,
        },
        f"events.confirmed:{registration.pk}:{registration.version}",
        category="events",
        user=registration.user,
        related=registration,
    )
    _emit_after_commit(event_registered, registration)
    return registration, True


@transaction.atomic
def cancel_anonymous_registration(token):
    registration = _registration_from_token(token, "manage")
    if registration.status == EventRegistration.Status.CANCELLED:
        return registration, False
    if registration.status == EventRegistration.Status.ATTENDED:
        raise RegistrationTokenError("invalid")
    registration.status = EventRegistration.Status.CANCELLED
    registration.version += 1
    registration.cancelled_at = timezone.now()
    registration.save(update_fields=("status", "version", "cancelled_at", "updated_at"))
    _emit_after_commit(event_unregistered, registration)
    return registration, True
