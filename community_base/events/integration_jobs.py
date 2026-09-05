import hashlib

from django.core.exceptions import ValidationError

from community_base.jobs.dispatch import dispatch_after_commit


def enqueue_zoom_sync(event, action):
    if action not in {"create", "update", "delete"}:
        raise ValidationError("Zoom action must be create, update or delete.")
    version = 0 if action == "create" else event.ics_sequence
    return dispatch_after_commit(
        "events.sync_zoom",
        f"events.zoom:{action}:{event.pk}:{version}",
        {"event_id": event.pk, "action": action},
    )


def enqueue_recording_processing(event, recording_reference):
    reference = str(recording_reference)
    if not reference or len(reference) > 512 or "://" in reference:
        raise ValidationError("Recording reference must be an opaque provider value.")
    digest = hashlib.sha256(reference.encode()).hexdigest()[:32]
    return dispatch_after_commit(
        "events.process_recording",
        f"events.recording:{event.pk}:{digest}",
        {"event_id": event.pk, "recording_reference": reference},
    )
