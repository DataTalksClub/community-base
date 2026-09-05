from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.notifications"
    label = "notifications"

    def ready(self):
        from community_base.notifications import signals  # noqa: F401
