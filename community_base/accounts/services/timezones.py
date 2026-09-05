from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.utils import timezone

DEFAULT_USER_DATETIME_FORMAT = "%B %d, %Y, %H:%M"


@dataclass(frozen=True, slots=True)
class TimezoneOption:
    value: str
    label: str
    offset_minutes: int


def is_valid_timezone(timezone_name):
    if not timezone_name:
        return False
    try:
        ZoneInfo(str(timezone_name))
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _format_offset(offset_minutes):
    sign = "+" if offset_minutes >= 0 else "-"
    hours, minutes = divmod(abs(offset_minutes), 60)
    return f"GMT{sign}{hours:02d}:{minutes:02d}"


def build_timezone_options():
    now = timezone.now().astimezone(UTC)
    options = []
    for name in available_timezones():
        offset = now.astimezone(ZoneInfo(name)).utcoffset()
        if offset is None:
            continue
        minutes = int(offset.total_seconds() // 60)
        options.append(TimezoneOption(name, f"{_format_offset(minutes)} {name}", minutes))
    return sorted(options, key=lambda option: (option.offset_minutes, option.value))


def format_user_datetime(value, user, *, fmt=None):
    if not isinstance(value, datetime):
        raise TypeError("format_user_datetime requires a datetime instance")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    name = getattr(user, "preferred_timezone", "") if user is not None else ""
    if is_valid_timezone(name):
        rendered = value.astimezone(ZoneInfo(name)).strftime(fmt or DEFAULT_USER_DATETIME_FORMAT)
        return f"{rendered} {name}"
    return f"{value.astimezone(UTC).strftime(fmt or DEFAULT_USER_DATETIME_FORMAT)} UTC"
