import pytest

from community_base.content_sync import parsers


@pytest.fixture(autouse=True)
def curriculum_parsers():
    """Isolated registry with the one course parser registered."""

    parsers._clear()
    from community_base.curriculum.apps import CONTENT_TYPE
    from community_base.curriculum.content_sync_parsers import CourseParser

    parsers.register_parser(CONTENT_TYPE, CourseParser())
    yield
    parsers._clear()
