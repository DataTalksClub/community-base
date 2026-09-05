from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.events.feedback import submit_feedback
from community_base.events.models import Event, EventRegistration, EventReminder
from community_base.events.registration import (
    expire_pending_registrations,
    record_attendance,
    register_for_event,
    unregister_from_event,
)
from community_base.events.reminders import (
    claim_due_reminders,
    complete_reminder,
    plan_event_reminders,
)
from community_base.mail import send

pytestmark = pytest.mark.django_db


def user(email="member@example.com"):
    return get_user_model().objects.create_user(email=email)


def event(**values):
    values.setdefault("title", "Community event")
    values.setdefault("start_datetime", timezone.now() + timedelta(hours=23))
    values.setdefault("status", "upcoming")
    values.setdefault("required_level", 5)
    return Event.objects.create(**values)


def test_expired_pending_registration_invalidates_its_version():
    occurrence = event(required_level=0)
    registration = EventRegistration.objects.create(
        event=occurrence,
        original_email="guest@example.com",
        normalized_email="guest@example.com",
        verification_expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert expire_pending_registrations() == 1
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.EXPIRED
    assert registration.version == 2


@pytest.mark.parametrize(
    ("attended", "expected"),
    [(True, EventRegistration.Status.ATTENDED), (False, EventRegistration.Status.NO_SHOW)],
)
def test_attendance_transitions_only_after_an_event(attended, expected):
    member = user(f"{expected}@example.com")
    occurrence = event(
        title=expected,
        start_datetime=timezone.now() - timedelta(hours=2),
        end_datetime=timezone.now() - timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=occurrence,
        user=member,
        original_email=member.email,
        normalized_email=member.email,
        status=EventRegistration.Status.CONFIRMED,
    )

    transitioned, changed = record_attendance(registration, attended=attended)

    assert changed is True
    assert transitioned.status == expected
    assert (transitioned.attended_at is not None) is attended


def test_reminder_selection_claims_due_active_registration_with_scalar_payload():
    member = user()
    occurrence = event()
    registration, _created = register_for_event(occurrence, member)
    reminders = plan_event_reminders(occurrence)

    payloads = claim_due_reminders()

    assert len(reminders) == 2
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.registration_id == str(registration.pk)
    assert payload.event_id == occurrence.pk
    assert payload.interval == "24h"
    assert not hasattr(payload, "email")


def test_cancelled_registration_makes_a_planned_reminder_terminally_skipped():
    member = user()
    occurrence = event()
    registration, _created = register_for_event(occurrence, member)
    reminder = plan_event_reminders(occurrence)[0]
    unregister_from_event(occurrence, member)

    assert claim_due_reminders() == ()
    reminder.refresh_from_db()
    assert reminder.status == EventReminder.Status.SKIPPED
    assert reminder.reason == "registration_version_changed"


def test_completed_reminder_delivery_must_match_registration_owner():
    member = user()
    occurrence = event()
    registration, _created = register_for_event(occurrence, member)
    plan_event_reminders(occurrence)
    payload = claim_due_reminders()[0]
    with transaction.atomic():
        wrong = send(
            "events.reminder",
            "other@example.com",
            {"event_id": occurrence.pk},
            "events.reminder:wrong",
        )

    with pytest.raises(ValidationError, match="does not own"):
        complete_reminder(payload.reminder_id, wrong)


def test_feedback_requires_the_owner_after_the_event_and_updates_in_place():
    member = user()
    other = user("other@example.com")
    occurrence = event(
        start_datetime=timezone.now() - timedelta(hours=2),
        end_datetime=timezone.now() - timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=occurrence,
        user=member,
        original_email=member.email,
        normalized_email=member.email,
        status=EventRegistration.Status.CONFIRMED,
    )

    with pytest.raises(PermissionDenied, match="owner"):
        submit_feedback(registration, user=other, rating=5)
    feedback, created = submit_feedback(registration, user=member, rating=5, comment="Great")
    updated, created_again = submit_feedback(registration, user=member, rating=4, comment="Useful")

    assert created is True
    assert created_again is False
    assert updated == feedback
    assert updated.rating == 4
    assert updated.comment == "Useful"
