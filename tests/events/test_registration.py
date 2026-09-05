from datetime import time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from community_base.events.models import (
    Event,
    EventRegistration,
    EventSeries,
    SeriesOccurrenceOptOut,
    SeriesRegistration,
)
from community_base.events.registration import (
    enroll_series_registrants_in_event,
    register_for_event,
    register_for_series,
    unregister_from_event,
)
from community_base.events.services import publish_event
from community_base.events.signals import event_registered, event_unregistered

pytestmark = pytest.mark.django_db


def user(email="member@example.com"):
    return get_user_model().objects.create_user(email=email)


def event(**values):
    values.setdefault("title", "Community event")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=3))
    values.setdefault("status", "upcoming")
    values.setdefault("required_level", 5)
    return Event.objects.create(**values)


def series():
    return EventSeries.objects.create(
        name="Office hours", day_of_week=2, start_time=time(18), required_level=5
    )


def test_member_registration_is_confirmed_and_idempotent():
    member = user()
    occurrence = event()

    registration, created = register_for_event(occurrence, member)
    replay, replayed = register_for_event(occurrence, member)

    assert created is True
    assert replayed is False
    assert replay == registration
    assert registration.status == EventRegistration.Status.CONFIRMED
    assert registration.normalized_email == member.email
    assert EventRegistration.objects.count() == 1


def test_member_registration_requires_authentication_access_and_open_event():
    occurrence = event()
    with pytest.raises(PermissionDenied, match="Authentication"):
        register_for_event(occurrence, None)

    restricted = event(title="Restricted", required_level=20)
    with pytest.raises(PermissionDenied, match="additional access"):
        register_for_event(restricted, user())

    closed = event(title="Closed", status="draft")
    with pytest.raises(ValidationError, match="not open"):
        register_for_event(closed, user("other@example.com"))


def test_series_registration_fans_out_and_new_occurrence_inherits_it():
    member = user()
    collection = series()
    first = event(event_series=collection, series_position=1)
    second = event(title="Second", event_series=collection, series_position=2)

    standing, created, summary = register_for_series(collection, member)
    third = event(title="Third", event_series=collection, series_position=3)
    inherited = enroll_series_registrants_in_event(third)

    assert created is True
    assert standing == SeriesRegistration.objects.get(series=collection, user=member)
    assert summary.registered == 2
    assert inherited.registered == 1
    assert set(
        EventRegistration.objects.filter(user=member).values_list("event_id", flat=True)
    ) == {first.pk, second.pk, third.pk}


def test_publishing_a_new_occurrence_enrolls_standing_registrants():
    member = user()
    collection = series()
    first = event(event_series=collection, series_position=1)
    register_for_series(collection, member)
    draft = event(title="Draft", event_series=collection, series_position=2, status="draft")

    publish_event(draft)

    assert EventRegistration.objects.filter(event=first, user=member).exists()
    assert EventRegistration.objects.filter(event=draft, user=member).exists()


def test_unregistering_one_series_occurrence_creates_an_opt_out():
    member = user()
    collection = series()
    occurrence = event(event_series=collection, series_position=1)
    register_for_series(collection, member)

    registration, changed = unregister_from_event(occurrence, member)
    inherited = enroll_series_registrants_in_event(occurrence)

    assert changed is True
    assert registration.status == EventRegistration.Status.CANCELLED
    assert SeriesOccurrenceOptOut.objects.filter(event=occurrence, user=member).exists()
    assert inherited.opted_out == 1
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.CANCELLED


def test_explicit_occurrence_registration_clears_an_opt_out():
    member = user()
    collection = series()
    occurrence = event(event_series=collection, series_position=1)
    register_for_series(collection, member)
    unregister_from_event(occurrence, member)

    registration, changed = register_for_event(occurrence, member)

    assert changed is True
    assert registration.status == EventRegistration.Status.CONFIRMED
    assert not SeriesOccurrenceOptOut.objects.filter(event=occurrence, user=member).exists()


def test_registration_signals_emit_only_after_changed_transactions(
    django_capture_on_commit_callbacks,
):
    member = user()
    occurrence = event()
    received = []

    def receiver(sender, signal, **values):
        received.append((signal, values["registration"].pk))

    event_registered.connect(receiver, weak=False)
    event_unregistered.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            registration, _created = register_for_event(occurrence, member)
        with django_capture_on_commit_callbacks(execute=True):
            register_for_event(occurrence, member)
        with django_capture_on_commit_callbacks(execute=True):
            unregister_from_event(occurrence, member)
    finally:
        event_registered.disconnect(receiver)
        event_unregistered.disconnect(receiver)

    assert received == [
        (event_registered, registration.pk),
        (event_unregistered, registration.pk),
    ]
