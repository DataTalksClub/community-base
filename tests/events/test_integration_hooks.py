from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.utils import timezone

from community_base.events.integrations.hooks import (
    generate_banner,
    process_recording,
    resolve_writeup,
)
from community_base.events.models import Event

pytestmark = pytest.mark.django_db(transaction=True)


def event():
    return Event.objects.create(
        title="Community event",
        slug="community-event",
        start_datetime=timezone.now() + timedelta(days=2),
    )


def configure(settings, **values):
    settings.COMMUNITY_BASE = dict(settings.COMMUNITY_BASE) | values


def test_banner_and_writeup_hooks_are_optional(settings):
    item = event()

    assert generate_banner(item) is None
    assert resolve_writeup(item) is None

    configure(
        settings,
        EVENT_BANNER_GENERATOR=lambda _event: "https://cdn.example.com/banner.png",
        EVENT_WRITEUP_RESOLVER=lambda _event: {
            "url": "https://example.com/writeup",
            "title": "Event notes",
        },
    )
    assert generate_banner(item) == "https://cdn.example.com/banner.png"
    assert resolve_writeup(item).title == "Event notes"


def test_writeup_hook_rejects_unstable_shapes(settings):
    configure(settings, EVENT_WRITEUP_RESOLVER=lambda _event: {"url": "https://example.com"})

    with pytest.raises(ImproperlyConfigured, match="url and title"):
        resolve_writeup(event())


def test_recording_processor_runs_outside_transaction_and_persists_safe_result(settings):
    transaction_states = []
    ready = []

    def processor(_event, reference):
        transaction_states.append(connection.in_atomic_block)
        assert reference == "recording-42"
        return {
            "recording_s3_url": "https://recordings.example.com/event-42.mp4",
            "recording_embed_url": "https://player.example.com/event-42",
        }

    configure(
        settings,
        EVENT_RECORDING_PROCESSOR=processor,
        EVENT_RECORDING_READY_HOOK=lambda item: ready.append(item.pk),
    )
    item, result = process_recording(event(), "recording-42")

    assert transaction_states == [False]
    assert item.recording_s3_url == "https://recordings.example.com/event-42.mp4"
    assert result.recording_embed_url == "https://player.example.com/event-42"
    assert ready == [item.pk]


def test_recording_processor_rejects_presigned_or_unknown_output(settings):
    item = event()
    configure(
        settings,
        EVENT_RECORDING_PROCESSOR=lambda _event, _reference: {
            "recording_s3_url": "https://example.com/video?signature=secret"
        },
    )
    with pytest.raises(ImproperlyConfigured, match="query or fragment"):
        process_recording(item, "recording-42")

    configure(
        settings,
        EVENT_RECORDING_PROCESSOR=lambda _event, _reference: {"provider_payload": "unsafe"},
    )
    with pytest.raises(ImproperlyConfigured, match="unsupported fields"):
        process_recording(item, "recording-42")
    item.refresh_from_db()
    assert item.recording_s3_url == ""
