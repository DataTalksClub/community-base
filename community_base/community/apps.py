from django.apps import AppConfig


class CommunityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.community"
    label = "community"

    def ready(self):
        from django.apps import apps

        from community_base.community.import_slack import register_slack_import_adapter

        register_slack_import_adapter()

        if apps.is_installed("community_base.onboarding"):
            from community_base.community import signals  # noqa: F401
