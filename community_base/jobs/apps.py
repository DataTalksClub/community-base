from django.apps import AppConfig


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.jobs"
    label = "cb_jobs"
    verbose_name = "Community Base Jobs"

    def ready(self) -> None:
        from community_base.jobs import builtin  # noqa: F401
        from community_base.jobs.studio_registration import register_studio

        register_studio()
