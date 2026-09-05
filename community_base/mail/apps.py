from django.apps import AppConfig


class MailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.mail"
    label = "cb_mail"
    verbose_name = "Community Base Mail"

    def ready(self) -> None:
        from community_base.mail import (
            api_views,  # noqa: F401
            jobs,  # noqa: F401
        )
        from community_base.mail.studio_registration import register_studio

        register_studio()
