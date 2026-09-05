from dataclasses import dataclass
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from community_base.events.models import Event
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve


@dataclass(frozen=True, slots=True)
class EventWriteup:
    url: str
    title: str


@dataclass(frozen=True, slots=True)
class RecordingResult:
    recording_url: str = ""
    recording_embed_url: str = ""
    recording_s3_url: str = ""


def _callback(setting):
    configured = get(setting)
    if configured is None:
        return None
    return resolve(configured) if isinstance(configured, str) else configured


def _safe_url(value, *, allow_query=False):
    if not isinstance(value, str) or len(value) > 500:
        raise ImproperlyConfigured("Event integration returned an invalid URL.")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ImproperlyConfigured("Event integration returned an invalid URL.")
    if not allow_query and (parsed.query or parsed.fragment):
        raise ImproperlyConfigured(
            "Persisted recording URLs cannot contain query or fragment data."
        )
    return value


def generate_banner(event):
    callback = _callback("EVENT_BANNER_GENERATOR")
    if callback is None:
        return None
    value = callback(event)
    return _safe_url(value, allow_query=True) if value else None


def resolve_writeup(event):
    callback = _callback("EVENT_WRITEUP_RESOLVER")
    if callback is None:
        return None
    value = callback(event)
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"url", "title"}:
        raise ImproperlyConfigured("Event writeup resolver must return url and title.")
    title = str(value["title"]).strip()
    if not title or len(title) > 300:
        raise ImproperlyConfigured("Event writeup resolver returned an invalid title.")
    return EventWriteup(_safe_url(value["url"], allow_query=True), title)


def process_recording(event, reference):
    callback = _callback("EVENT_RECORDING_PROCESSOR")
    if callback is None:
        raise ImproperlyConfigured("Event recording processor is not configured.")
    value = callback(event, str(reference))
    if not isinstance(value, dict) or not value:
        raise ImproperlyConfigured("Event recording processor returned no result.")
    unknown = set(value) - {"recording_url", "recording_embed_url", "recording_s3_url"}
    if unknown:
        raise ImproperlyConfigured("Event recording processor returned unsupported fields.")
    result = RecordingResult(**{name: _safe_url(raw) if raw else "" for name, raw in value.items()})
    if not any((result.recording_url, result.recording_embed_url, result.recording_s3_url)):
        raise ImproperlyConfigured("Event recording processor returned no recording URL.")
    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event.pk)
        for field in ("recording_url", "recording_embed_url", "recording_s3_url"):
            field_value = getattr(result, field)
            if field_value:
                setattr(event, field, field_value)
        event.save(
            update_fields=(
                "recording_url",
                "recording_embed_url",
                "recording_s3_url",
                "updated_at",
            )
        )
        ready = _callback("EVENT_RECORDING_READY_HOOK")
        if ready is not None:
            transaction.on_commit(lambda: ready(event))
    return event, result
