from importlib import import_module

from django.apps import AppConfig, apps


class ConfigAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.config"
    label = "cb_config"
    verbose_name = "Community Base Configuration"

    def ready(self) -> None:
        for app_config in apps.get_app_configs():
            module_name = f"{app_config.name}.settings_keys"
            try:
                import_module(module_name)
            except ModuleNotFoundError as error:
                if error.name != module_name:
                    raise
        import_module("community_base.config.api_views")
        from community_base.config.studio_registration import register_studio

        register_studio()
