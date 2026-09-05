from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from community_base.events.models import Event, EventHost, EventSeries, Host

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
