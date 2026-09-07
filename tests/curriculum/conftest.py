import pytest

from community_base.content_sync import parsers


@pytest.fixture(autouse=True)
def curriculum_parsers():
    """Isolated registry with the app-level curriculum parsers registered."""

    parsers._clear()
    from community_base.curriculum.content_sync_parsers import (
        AislCourseParser,
        DtcCourseRepositoryParser,
    )

    parsers.register_parser("curriculum_aisl_course", AislCourseParser())
    parsers.register_parser("curriculum_dtc_course_repository", DtcCourseRepositoryParser())
    yield
    parsers._clear()
