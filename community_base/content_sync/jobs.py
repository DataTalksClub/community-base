from community_base.jobs.registry import register_handler


@register_handler("cb_content_sync.sync_source", chunked=True)
def sync_source(context, payload):
    from community_base.content_sync.models import ContentSource
    from community_base.content_sync.orchestration import sync_content_source

    del context
    source = ContentSource.objects.get(pk=payload["source_id"])
    sync_content_source(
        source,
        batch_id=payload.get("batch_id"),
        force=bool(payload.get("force", False)),
    )
