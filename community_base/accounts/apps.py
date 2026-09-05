from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.accounts"
    label = "accounts"
    verbose_name = "Community Base Accounts"

    def ready(self):
        from community_base.accounts import self_api, signals  # noqa: F401
