from django.apps import AppConfig, apps


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.accounts"
    label = "accounts"
    verbose_name = "Community Base Accounts"

    def ready(self):
        from community_base.accounts import self_api, signals  # noqa: F401
        from community_base.mail.context import register_context_resolver

        register_context_resolver(
            "accounts.", "community_base.accounts.mail_context.resolve_delivery_context"
        )

        if apps.is_installed("community_base.studio"):
            from community_base.accounts.studio_registration import register_studio

            register_studio()
