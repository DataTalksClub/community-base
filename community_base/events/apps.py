from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.events"
    label = "events"
    verbose_name = "Events"

    def ready(self):
        from community_base.events import jobs  # noqa: F401
        from community_base.events.studio_registration import register_studio
        from community_base.mail.context import register_context_resolver

        register_studio()
        register_context_resolver(
            "events.", "community_base.events.mail_context.resolve_delivery_context"
        )
