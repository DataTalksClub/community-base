from django.apps import AppConfig, apps


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.accounts"
    label = "accounts"
    verbose_name = "Community Base Accounts"

    def ready(self):
        from community_base.accounts import self_api, signals  # noqa: F401

        if apps.is_installed("community_base.studio"):
            from community_base.accounts.studio_registration import register_studio

            register_studio()
