from django.apps import AppConfig


class CourseworkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.coursework"
    label = "cb_coursework"
    verbose_name = "Coursework"

    def ready(self):
        # C5.2g: pooling.py registers the coursework.expire_pooled_reviews job handler and its
        # schedule as module-level side effects; it must be imported eagerly here, the same way
        # reminders.py's three handlers already are, or a pooled site never registers it (every
        # other import of pooling.py is a lazy, function-local import to break an import cycle
        # with review.py/projects.py -- see those modules for why).
        from community_base.coursework import api_views, pooling, reminders  # noqa: F401
        from community_base.coursework.studio_registration import register_studio

        register_studio()
