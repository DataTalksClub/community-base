from django.apps import AppConfig


class CommentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.comments"
    label = "comments"

    def ready(self):
        from django.apps import apps

        if apps.is_installed("community_base.studio"):
            from community_base.comments.studio_registration import register_studio

            register_studio()
