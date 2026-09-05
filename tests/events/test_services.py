from datetime import date, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from community_base.events.models import Event, EventPublicIdSequence, EventSeries, Host
from community_base.events.services import (
    add_alias,
    allocate_public_id,
    can_register_for_event,
    cancel_event,
    create_weekly_occurrences,
    host_profile_url,
    publish_event,
    reschedule_event,
    reserve_public_id,
)
from community_base.events.signals import event_cancelled, event_published, event_rescheduled

pytestmark = pytest.mark.django_db(transaction=True)


def event(**values):
    values.setdefault("title", "Community event")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=2))
    return Event.objects.create(**values)


def test_allocator_skips_reserved_ids_and_never_reuses_an_assignment():
    imported = event(title="Imported")
    first = event(title="First")
    second = event(title="Second")

    assert reserve_public_id(imported, 7) == 7
    assert allocate_public_id(first) == 8
    assert allocate_public_id(first) == 8
    assert allocate_public_id(second) == 9
    assert EventPublicIdSequence.objects.get(pk=1).next_public_id == 10


def test_public_id_is_immutable_and_unique():
    first = event(title="First")
    second = event(title="Second")
    reserve_public_id(first, 3)
    first.refresh_from_db()
    first.public_id = 4

    with pytest.raises(ValidationError, match="immutable"):
        first.save()
    with pytest.raises(ValidationError, match="already allocated"):
        reserve_public_id(second, 3)


def test_public_id_cannot_be_assigned_by_saving_the_model():
    item = event()
    item.public_id = 3

    with pytest.raises(ValidationError, match="immutable"):
        item.save()


def test_aliases_are_owned_and_restricted_to_clean_event_paths():
    item = event()
    alias = add_alias(item, "/events/legacy/path", source_repository="donor")

    assert alias.event == item
    assert alias.source_repository == "donor"
    with pytest.raises(ValidationError, match="below /events/"):
        add_alias(item, "https://example.com/events/legacy")
    with pytest.raises(ValidationError, match="below /events/"):
        add_alias(item, "/events/legacy?source=old")


def test_alias_path_has_one_owner():
    add_alias(event(title="First"), "/events/shared")

    with pytest.raises(ValidationError, match="already exists"):
        add_alias(event(title="Second"), "/events/shared")


def test_host_profile_resolver_is_optional_and_configurable(settings):
    host = Host.objects.create(name="Speaker", slug="speaker", external_ref="speaker-1")

    assert host_profile_url(host) is None
    configured = dict(settings.COMMUNITY_BASE)
    configured["HOST_PROFILE_RESOLVER"] = lambda item: f"/people/{item.external_ref}.html"
    with override_settings(COMMUNITY_BASE=configured):
        assert host_profile_url(host) == "/people/speaker-1.html"


def test_registration_uses_the_package_access_policy():
    user = get_user_model().objects.create_user(email="member@example.com")
    item = event(status="upcoming", required_level=5)

    assert can_register_for_event(user, item) is True
    assert can_register_for_event(None, item) is False


def test_weekly_occurrences_preserve_local_time_across_dst():
    series = EventSeries.objects.create(
        name="Wednesday office hours",
        day_of_week=2,
        start_time=time(18),
        timezone="Europe/Berlin",
        required_level=5,
    )

    occurrences = create_weekly_occurrences(series, first_date=date(2026, 3, 25), count=2)
    starts = [item.start_datetime for item in occurrences]

    assert [value.hour for value in starts] == [18, 18]
    assert starts[0].utcoffset() != starts[1].utcoffset()
    assert [item.series_position for item in occurrences] == [1, 2]
    assert [item.required_level for item in occurrences] == [5, 5]


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1)])
def test_weekly_occurrences_require_positive_duration(duration):
    series = EventSeries.objects.create(name="Office hours", day_of_week=2, start_time=time(18))

    with pytest.raises(ValidationError, match="duration must be positive"):
        create_weekly_occurrences(series, first_date=date(2026, 3, 25), count=1, duration=duration)


def test_lifecycle_services_emit_after_commit(django_capture_on_commit_callbacks):
    item = event()
    received = []

    def receiver(sender, signal, **values):
        received.append((signal, values))

    signals = (event_published, event_rescheduled, event_cancelled)
    for signal in signals:
        signal.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            item = publish_event(item)
        new_start = item.start_datetime + timedelta(days=1)
        with django_capture_on_commit_callbacks(execute=True):
            item = reschedule_event(item, start_datetime=new_start, reason="New day")
        with django_capture_on_commit_callbacks(execute=True):
            item = cancel_event(item, reason="No host")
    finally:
        for signal in signals:
            signal.disconnect(receiver)

    assert [entry[0] for entry in received] == list(signals)
    assert received[1][1]["old_start"] == new_start - timedelta(days=1)
    assert received[1][1]["reason"] == "New day"
    assert received[2][1]["reason"] == "No host"
    assert item.status == "cancelled"
    assert item.ics_sequence == 2
