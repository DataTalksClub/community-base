from django.apps import AppConfig


class APIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.api"
    label = "cb_api"
    verbose_name = "Community Base API"

    def ready(self) -> None:
        from community_base.api.studio_registration import register_studio

        register_studio()
