from django.apps import AppConfig


class ContentSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.content_sync"
    label = "cb_content_sync"
    verbose_name = "Community Base Content Sync"

    def ready(self) -> None:
        from community_base.content_sync import (
            api_views,  # noqa: F401
            jobs,  # noqa: F401
        )
        from community_base.content_sync.studio_registration import register_studio

        register_studio()
