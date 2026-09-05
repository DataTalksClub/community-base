from __future__ import annotations

import uuid

from django.db import transaction

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import parse_pagination, read_json_object
from community_base.content_sync.models import ContentSource, SyncStatus
from community_base.content_sync.queue import queue_source_sync

SOURCE_SCHEMA = {
    "type": "object",
    "required": ["id", "slug", "repository", "enabled", "status"],
}
SOURCES_SCHEMA = {"type": "object", "properties": {"sources": {"type": "array"}}}
TRIGGER_SCHEMA = {
    "type": "object",
    "required": ["batch_id", "jobs"],
}


def _not_found():
    return APIError(404, "content_source_not_found", "Content source was not found.")


def _source(source_id):
    try:
        return ContentSource.objects.get(pk=source_id)
    except (ContentSource.DoesNotExist, ValueError) as error:
        raise _not_found() from error


def serialize(source):
    return {
        "id": str(source.pk),
        "slug": source.slug,
        "repository": source.repo_name,
        "private": source.is_private,
        "enabled": source.is_enabled,
        "status": source.last_sync_status or None,
        "last_synced_at": source.last_synced_at.isoformat() if source.last_synced_at else None,
        "last_synced_commit": source.last_synced_commit or None,
        "last_webhook_at": source.last_webhook_at.isoformat() if source.last_webhook_at else None,
    }


@route(
    "GET",
    "content-sources",
    "content_sync.read",
    "List content sync sources",
    SOURCES_SCHEMA,
)
def list_sources(request):
    page = parse_pagination(request)
    queryset = ContentSource.objects.all()
    total = queryset.count()
    selected = queryset[page.offset : page.offset + page.limit]
    return json_response(
        {
            "sources": [serialize(source) for source in selected],
            "pagination": {"limit": page.limit, "offset": page.offset, "total": total},
        }
    )


@route(
    "GET",
    "content-sources/<uuid:source_id>",
    "content_sync.read",
    "Read a content sync source",
    SOURCE_SCHEMA,
)
def get_source(request, source_id):
    del request
    return json_response(serialize(_source(source_id)))


@route(
    "POST",
    "content-sources/sync",
    "content_sync.write",
    "Queue all enabled content sources",
    TRIGGER_SCHEMA,
    {"type": "object", "properties": {"force": {"type": "boolean"}}},
)
def sync_sources(request):
    payload = read_json_object(request) if request.body else {}
    force = _force(payload)
    sources = list(
        ContentSource.objects.all() if force else ContentSource.objects.filter(is_enabled=True)
    )
    return _queue(sources, force=force)


@route(
    "POST",
    "content-sources/<uuid:source_id>/sync",
    "content_sync.write",
    "Queue one content sync source",
    TRIGGER_SCHEMA,
    {"type": "object", "properties": {"force": {"type": "boolean"}}},
)
def sync_source(request, source_id):
    payload = read_json_object(request) if request.body else {}
    force = _force(payload)
    source = _source(source_id)
    if not source.is_enabled and not force:
        raise APIError(409, "content_source_disabled", "Content source is disabled.")
    return _queue([source], force=force)


def _force(payload):
    force = payload.get("force", False)
    if not isinstance(force, bool):
        raise APIError(422, "validation_error", "force must be a boolean.")
    return force


def _queue(sources, *, force):
    batch_id = uuid.uuid4()
    jobs = []
    with transaction.atomic():
        for source in sources:
            intent, _ = queue_source_sync(
                source,
                key=f"api:{batch_id}",
                batch_id=batch_id,
                force=force,
            )
            ContentSource.objects.filter(pk=source.pk).update(last_sync_status=SyncStatus.QUEUED)
            jobs.append({"source_id": str(source.pk), "job_id": str(intent.pk)})
    return json_response({"batch_id": str(batch_id), "jobs": jobs}, status=202)
