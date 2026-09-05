from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.events.integration_jobs import (
    enqueue_recording_processing,
    enqueue_zoom_sync,
)
from community_base.events.models import Event
from community_base.jobs.models import JobIntent

pytestmark = pytest.mark.django_db


def event():
    return Event.objects.create(
        title="Community event",
        slug="community-event",
        start_datetime=timezone.now() + timedelta(days=2),
    )


def test_zoom_enqueue_is_idempotent_and_contains_only_scalar_input():
    item = event()
    with transaction.atomic():
        first, created = enqueue_zoom_sync(item, "create")
        replay, replayed = enqueue_zoom_sync(item, "create")

    assert created is True
    assert replayed is False
    assert replay == first
    assert first.payload == {"event_id": item.pk, "action": "create"}


def test_zoom_update_key_changes_with_calendar_sequence():
    item = event()
    with transaction.atomic():
        first, _created = enqueue_zoom_sync(item, "update")
    item.ics_sequence += 1
    item.save(update_fields=("ics_sequence", "updated_at"))
    with transaction.atomic():
        second, _created = enqueue_zoom_sync(item, "update")

    assert first != second
    assert JobIntent.objects.filter(handler="events.sync_zoom").count() == 2


def test_recording_enqueue_hashes_reference_out_of_the_job_key():
    item = event()
    reference = "opaque-provider-reference"
    with transaction.atomic():
        intent, created = enqueue_recording_processing(item, reference)

    assert created is True
    assert reference not in intent.key_hash
    assert intent.payload == {"event_id": item.pk, "recording_reference": reference}


@pytest.mark.parametrize("reference", ["", "https://provider.example.com/video"])
def test_recording_enqueue_rejects_non_opaque_references(reference):
    with transaction.atomic(), pytest.raises(ValidationError, match="opaque provider"):
        enqueue_recording_processing(event(), reference)
