from django.apps import AppConfig


class StudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.studio"
    label = "cb_studio"
    verbose_name = "Community Base Studio"

    def ready(self) -> None:
        from community_base.studio import builtin

        builtin.register_builtin_section()
