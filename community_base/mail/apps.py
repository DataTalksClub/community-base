from django.apps import AppConfig


class MailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.mail"
    label = "cb_mail"
    verbose_name = "Community Base Mail"

    def ready(self) -> None:
        from community_base.mail import jobs  # noqa: F401
