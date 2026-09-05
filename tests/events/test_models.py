from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from community_base.accounts.models import User
from community_base.events.models import (
    Event,
    EventFeedback,
    EventHost,
    EventRegistration,
    EventReminder,
    EventSeries,
    Host,
    SeriesOccurrenceOptOut,
    SeriesRegistration,
)

pytestmark = pytest.mark.django_db(transaction=True)

BERLIN = ZoneInfo("Europe/Berlin")


def event(**values):
    values.setdefault("title", "Community event")
    values.setdefault("start_datetime", datetime(2026, 4, 1, 18, tzinfo=BERLIN))
    return Event.objects.create(**values)


def test_event_rejects_end_before_start():
    item = Event(
        title="Backwards event",
        start_datetime=datetime(2026, 4, 1, 18, tzinfo=BERLIN),
        end_datetime=datetime(2026, 4, 1, 17, tzinfo=BERLIN),
    )

    with pytest.raises(ValidationError, match="must not precede"):
        item.full_clean()


def test_event_uses_one_hour_when_end_is_unspecified():
    item = event()

    assert item.effective_end_datetime == item.start_datetime + timedelta(hours=1)


@pytest.mark.parametrize(
    ("cadence", "day_of_week", "start_time", "message"),
    [
        ("weekly", None, None, "require a day and start time"),
        ("none", 2, time(18), "cannot define a day or start time"),
    ],
)
def test_series_validates_its_schedule(cadence, day_of_week, start_time, message):
    series = EventSeries(
        name="Office hours",
        cadence=cadence,
        day_of_week=day_of_week,
        start_time=start_time,
    )

    with pytest.raises(ValidationError, match=message):
        series.full_clean()


def test_series_and_position_must_be_set_together():
    series = EventSeries.objects.create(name="Office hours", day_of_week=2, start_time=time(18))

    with pytest.raises(ValidationError, match="must be set together"):
        Event(
            title="Unpositioned event",
            start_datetime=datetime(2026, 4, 1, 18, tzinfo=BERLIN),
            event_series=series,
        ).full_clean()


def test_series_positions_are_unique():
    series = EventSeries.objects.create(name="Office hours", day_of_week=2, start_time=time(18))
    event(event_series=series, series_position=1)

    with pytest.raises(IntegrityError):
        event(title="Duplicate position", event_series=series, series_position=1)


def test_event_hosts_preserve_position_and_role():
    item = event()
    first = Host.objects.create(name="First", slug="first")
    second = Host.objects.create(name="Second", slug="second", kind="speaker")
    EventHost.objects.create(event=item, host=second, position=2, role="speaker")
    EventHost.objects.create(event=item, host=first, position=1, role="host")

    assert item.ordered_hosts == [first, second]
    assert list(item.event_host_links.values_list("role", flat=True)) == ["host", "speaker"]


def test_registration_identity_is_unique_by_email_and_member():
    item = event()
    user = User.objects.create_user(email="member@example.com")
    EventRegistration.objects.create(
        event=item,
        user=user,
        original_email=user.email,
        normalized_email=user.email,
        status=EventRegistration.Status.CONFIRMED,
    )

    with pytest.raises(IntegrityError):
        EventRegistration.objects.create(
            event=item,
            original_email="MEMBER@example.com",
            normalized_email=user.email,
        )


def test_series_registration_and_occurrence_opt_out_are_distinct():
    user = User.objects.create_user(email="member@example.com")
    series = EventSeries.objects.create(name="Office hours", day_of_week=2, start_time=time(18))
    occurrence = event(event_series=series, series_position=1)
    standing = SeriesRegistration.objects.create(series=series, user=user)
    opt_out = SeriesOccurrenceOptOut.objects.create(series=series, event=occurrence, user=user)

    assert standing.series == series
    assert opt_out.event == occurrence


def test_occurrence_opt_out_must_match_the_events_series():
    user = User.objects.create_user(email="member@example.com")
    first = EventSeries.objects.create(name="First", day_of_week=2, start_time=time(18))
    second = EventSeries.objects.create(name="Second", day_of_week=3, start_time=time(19))
    occurrence = event(event_series=first, series_position=1)

    with pytest.raises(ValidationError, match="must belong"):
        SeriesOccurrenceOptOut(series=second, event=occurrence, user=user).full_clean()


def test_feedback_and_reminders_have_explicit_registration_ownership():
    user = User.objects.create_user(email="member@example.com")
    item = event()
    registration = EventRegistration.objects.create(
        event=item,
        user=user,
        original_email=user.email,
        normalized_email=user.email,
        status=EventRegistration.Status.CONFIRMED,
    )
    feedback = EventFeedback.objects.create(registration=registration, rating=5)
    reminder = EventReminder.objects.create(
        registration=registration,
        registration_version=registration.version,
        interval="24h",
        scheduled_for=item.start_datetime - timedelta(hours=24),
    )

    assert feedback.registration.user == user
    assert reminder.registration.event == item


def test_feedback_rejects_an_empty_submission():
    user = User.objects.create_user(email="member@example.com")
    item = event()
    registration = EventRegistration.objects.create(
        event=item,
        user=user,
        original_email=user.email,
        normalized_email=user.email,
        status=EventRegistration.Status.CONFIRMED,
    )

    with pytest.raises(ValidationError, match="rating or a comment"):
        EventFeedback(registration=registration).full_clean()
