from django.apps import AppConfig


class SiteEventsConfig(AppConfig):
    name = "tests.curriculum.host_adapter"
    label = "events"


class ContentModelsConfig(AppConfig):
    # This consumer needs the source models, without unrelated API/Studio surfaces.
    name = "community_base.content_sync"
    label = "cb_content_sync"
