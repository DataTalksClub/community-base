from django.apps import AppConfig


class CourseworkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.coursework"
    label = "cb_coursework"
    verbose_name = "Coursework"

    def ready(self):
        from community_base.coursework import api_views, reminders  # noqa: F401
