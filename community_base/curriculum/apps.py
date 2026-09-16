from django.apps import AppConfig


def events_dependent_surfaces_active(installed_apps) -> bool:
    """Whether the curriculum API and Studio surfaces may be registered.

    Those surfaces manage hosts and events through the package events app.
    A site that installs curriculum for its models and sync contract while
    owning its own events app elsewhere cannot import them: the events
    models would raise outside their app registry.
    """

    return "community_base.events" in set(installed_apps)


class CurriculumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.curriculum"
    label = "cb_curriculum"
    verbose_name = "Curriculum"

    def ready(self):
        from django.conf import settings

        from community_base.content_sync.parsers import register_parser
        from community_base.curriculum.content_sync_parsers import (
            AislCourseParser,
            DtcCourseRepositoryParser,
        )

        register_parser("curriculum_aisl_course", AislCourseParser())
        register_parser("curriculum_dtc_course_repository", DtcCourseRepositoryParser())

        if events_dependent_surfaces_active(settings.INSTALLED_APPS):
            from community_base.curriculum import api_views  # noqa: F401
            from community_base.curriculum.studio_registration import register_studio

            register_studio()
