from django.apps import AppConfig


class CurriculumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.curriculum"
    label = "cb_curriculum"
    verbose_name = "Curriculum"

    def ready(self):
        from community_base.content_sync.parsers import register_parser
        from community_base.curriculum import api_views  # noqa: F401
        from community_base.curriculum.content_sync_parsers import (
            AislCourseParser,
            DtcCourseRepositoryParser,
        )
        from community_base.curriculum.studio_registration import register_studio

        register_parser("curriculum_aisl_course", AislCourseParser())
        register_parser("curriculum_dtc_course_repository", DtcCourseRepositoryParser())
        register_studio()
