"""Durable, one-source-per-job content sync dispatch."""

from community_base.jobs.dispatch import dispatch_after_commit


def queue_source_sync(source, *, key, batch_id=None, force=False):
    payload = {"source_id": str(source.pk), "force": bool(force)}
    if batch_id is not None:
        payload["batch_id"] = str(batch_id)
    return dispatch_after_commit(
        "cb_content_sync.sync_source",
        f"content-sync:{source.pk}:{key}",
        payload,
    )
