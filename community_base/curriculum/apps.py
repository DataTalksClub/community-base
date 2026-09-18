from django.apps import AppConfig, apps

#: The one content type the curriculum app registers a parser for.
CONTENT_TYPE = "curriculum_course"


def events_dependent_surfaces_active() -> bool:
    """Whether the curriculum API and Studio surfaces may be registered.

    Those surfaces manage hosts and events through the package events app.
    A site that installs curriculum for its models and sync contract while
    owning its own events app elsewhere cannot import them: the events
    models would raise outside their app registry.

    Uses `apps.is_installed()`, not a membership test against
    `settings.INSTALLED_APPS`: Django accepts both the plain module path
    (`"community_base.events"`) and the AppConfig path
    (`"community_base.events.apps.EventsConfig"`) in that list, and a raw
    string comparison only recognises the first.
    """

    return apps.is_installed("community_base.events")


class CurriculumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.curriculum"
    label = "cb_curriculum"
    verbose_name = "Curriculum"

    def ready(self):
        from community_base.content_sync.parsers import register_parser
        from community_base.curriculum.content_sync_parsers import CourseParser

        register_parser(CONTENT_TYPE, CourseParser())

        if events_dependent_surfaces_active():
            from community_base.curriculum import api_views  # noqa: F401
            from community_base.curriculum.studio_registration import register_studio

            register_studio()
