from django.urls import path

from community_base.content_sync import studio

urlpatterns = [
    path("content-sync/", studio.sources_list, name="community_base_content_sources"),
    path(
        "content-sync/history/",
        studio.history,
        name="community_base_content_sync_history",
    ),
    path(
        "content-sync/worker/",
        studio.worker,
        name="community_base_content_sync_worker",
    ),
    path(
        "content-sync/<uuid:source_id>/edit/",
        studio.source_edit,
        name="community_base_content_source_edit",
    ),
    path(
        "content-sync/<uuid:source_id>/sync/",
        studio.source_sync,
        name="community_base_content_source_sync",
    ),
]
