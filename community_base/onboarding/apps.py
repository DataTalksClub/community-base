from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.onboarding"
    label = "cb_onboarding"

    def ready(self):
        from django.apps import apps

        if apps.is_installed("community_base.studio"):
            from community_base.onboarding.studio_registration import register_studio

            register_studio()
