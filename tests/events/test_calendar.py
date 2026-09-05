from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from community_base.events.integrations.calendar import (
    CalendarError,
    generate_feed_ics,
    generate_ics,
    generate_series_ics,
)
from community_base.events.models import Event

pytestmark = pytest.mark.django_db

BERLIN = ZoneInfo("Europe/Berlin")


def event(**values):
    values.setdefault("title", "Community, calendars; and events")
    values.setdefault("slug", "community-calendars")
    values.setdefault("start_datetime", datetime(2026, 4, 1, 18, tzinfo=BERLIN))
    values.setdefault("end_datetime", datetime(2026, 4, 1, 19, tzinfo=BERLIN))
    values.setdefault("description", "A useful session\nwith two lines")
    values.setdefault("status", "upcoming")
    values.setdefault("public_id", 42)
    return Event.objects.create(**values)


def test_attendee_calendar_uses_stable_identity_and_gated_join_url():
    item = event()
    content = generate_ics(
        item,
        attendee_email="member@example.com",
        dtstamp=datetime(2026, 3, 1, tzinfo=BERLIN),
    ).decode()

    assert content.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0")
    assert f"UID:{item.calendar_uid}" in content
    assert "DTSTART:20260401T160000Z" in content
    assert "SUMMARY:Community\\, calendars\\; and events" in content
    assert "http://testserver/events/42/community-calendars/join" in content
    assert "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:member@" in content


def test_public_feed_omits_method_and_join_route():
    content = generate_feed_ics([event()], dtstamp=timezone.now()).decode()

    assert "METHOD:" not in content
    assert "http://testserver/events/42/community-calendars" in content
    assert "/join" not in content


def test_cancelled_series_calendar_marks_each_component_cancelled():
    first = event()
    second = event(
        title="Second",
        slug="second",
        public_id=43,
        start_datetime=datetime(2026, 4, 8, 18, tzinfo=BERLIN),
        end_datetime=datetime(2026, 4, 8, 19, tzinfo=BERLIN),
    )

    content = generate_series_ics([first, second], method="CANCEL").decode()

    assert content.count("BEGIN:VEVENT") == 2
    assert content.count("STATUS:CANCELLED") == 2
    assert "METHOD:CANCEL" in content


def test_calendar_lines_are_folded_to_rfc_octet_limit():
    content = generate_ics(event(title="é" * 100)).decode()

    assert all(len(line.encode()) <= 75 for line in content.split("\r\n") if line)


def test_calendar_rejects_invalid_attendee_and_naive_datetimes():
    with pytest.raises(CalendarError, match="valid mailbox"):
        generate_ics(event(), attendee_email="not-an-email")
    with pytest.raises(CalendarError, match="timezone-aware"):
        generate_ics(
            Event(
                title="Naive",
                public_id=44,
                slug="naive",
                start_datetime=datetime(2026, 4, 1, 18),
                end_datetime=datetime(2026, 4, 1, 19),
                calendar_uid="naive@example.com",
            )
        )


def test_calendar_uses_one_hour_effective_end():
    item = event(public_id=45, slug="default-end", end_datetime=None)
    content = generate_ics(item).decode()

    expected = item.start_datetime + timedelta(hours=1)
    assert expected.astimezone(ZoneInfo("UTC")).strftime("DTEND:%Y%m%dT%H%M%SZ") in content
