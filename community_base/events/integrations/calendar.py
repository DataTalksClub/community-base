from datetime import UTC, datetime
from email.utils import getaddresses

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from community_base.config import get as get_config
from community_base.kernel.conf import get

MAX_DESCRIPTION_CHARS = 2000
VALID_METHODS = frozenset({"REQUEST", "CANCEL", "PUBLISH"})
VALID_AUDIENCES = frozenset({"attendee", "public"})


class CalendarError(ValueError):
    pass


def _escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold(line, limit=75):
    chunks = []
    current = ""
    for character in line:
        prefix = " " if chunks else ""
        if current and len((prefix + current + character).encode()) > limit:
            chunks.append(current)
            current = character
        else:
            current += character
    chunks.append(current)
    return "\r\n ".join(chunks)


def _format_datetime(value):
    if value is None or not timezone.is_aware(value):
        raise CalendarError("Calendar datetimes must be timezone-aware.")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _organizer_lines():
    raw = get_config("EVENT_ORGANIZER_EMAIL")
    if not raw:
        return []
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise CalendarError("Calendar organizer must contain one valid mailbox.")
    parsed = getaddresses([raw], strict=True)
    if len(parsed) != 1:
        raise CalendarError("Calendar organizer must contain one valid mailbox.")
    _display_name, mailbox = parsed[0]
    try:
        validate_email(mailbox)
    except ValidationError as error:
        raise CalendarError("Calendar organizer must contain one valid mailbox.") from error
    name = _escape(get_config("EVENT_ORGANIZER_NAME"))
    return [f"ORGANIZER;CN={name}:mailto:{mailbox}"]


def _event_paths(event):
    identity = event.public_id or event.slug
    detail = f"/events/{identity}/{event.slug}" if event.public_id else f"/events/{event.slug}"
    return detail, f"{detail}/join"


def _absolute(path):
    site_url = get("SITE_URL").rstrip("/")
    if not site_url:
        raise CalendarError("SITE_URL is required for calendar output.")
    return f"{site_url}{path}"


def event_component(
    event, *, audience="attendee", attendee_email=None, method="REQUEST", dtstamp=None
):
    method = method.upper()
    if method not in VALID_METHODS or audience not in VALID_AUDIENCES:
        raise CalendarError("Unsupported calendar method or audience.")
    detail_path, join_path = _event_paths(event)
    detail_url = _absolute(detail_path)
    action_url = _absolute(join_path) if audience == "attendee" else detail_url
    description = (event.description or "").strip()[:MAX_DESCRIPTION_CHARS]
    body = f"{description}\n\nJoin: {action_url}" if description else f"Join: {action_url}"
    stamp = dtstamp or getattr(event, "updated_at", None) or datetime.now(UTC)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{_escape(event.calendar_uid)}",
        f"DTSTAMP:{_format_datetime(stamp)}",
        f"DTSTART:{_format_datetime(event.start_datetime)}",
        f"DTEND:{_format_datetime(event.effective_end_datetime)}",
        f"SEQUENCE:{event.ics_sequence}",
        f"SUMMARY:{_escape(event.title)}",
        f"DESCRIPTION:{_escape(body)}",
        f"URL:{_escape(action_url)}",
        f"LOCATION:{_escape(event.location or action_url)}",
        *_organizer_lines(),
    ]
    if attendee_email:
        try:
            validate_email(attendee_email)
        except ValidationError as error:
            raise CalendarError("Calendar attendee must be a valid mailbox.") from error
        lines.append(f"ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:{attendee_email}")
    if method == "CANCEL":
        lines.append("STATUS:CANCELLED")
    lines.append("END:VEVENT")
    return lines


def generate_ics(
    events, *, method="REQUEST", audience="attendee", attendee_email=None, dtstamp=None
):
    method = method.upper()
    rows = list(events) if not hasattr(events, "calendar_uid") else [events]
    if not rows:
        raise CalendarError("At least one event is required.")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//community-base//Events//EN"]
    if method != "PUBLISH" or audience != "public":
        lines.append(f"METHOD:{method}")
    for event in rows:
        lines.extend(
            event_component(
                event,
                audience=audience,
                attendee_email=attendee_email,
                method=method,
                dtstamp=dtstamp,
            )
        )
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()


def generate_series_ics(events, *, method="REQUEST", attendee_email=None, dtstamp=None):
    return generate_ics(
        events,
        method=method,
        audience="attendee",
        attendee_email=attendee_email,
        dtstamp=dtstamp,
    )


def generate_feed_ics(events, *, dtstamp=None):
    return generate_ics(events, method="PUBLISH", audience="public", dtstamp=dtstamp)
