from django.apps import AppConfig


class APIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.api"
    label = "cb_api"
    verbose_name = "Community Base API"
