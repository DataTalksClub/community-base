import shutil

import pytest

from community_base.content_sync.models import SyncLog, SyncStatus
from community_base.content_sync.orchestration import sync_content_source
from community_base.coursework.models import Homework, Question
from community_base.curriculum.content_sync_parsers import CourseParser
from community_base.curriculum.models import Course
from community_base.curriculum.site_adaptation import (
    CourseSiteBoundaryError,
    CourseSitePartialError,
    _clear_course_site_adapter,
    register_course_site_adapter,
)
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.course_site_fixtures import (
    ACTIVE_SITE_RENDERER,
    RecordingCourseAdapter,
    TransactionalCourseAdapter,
    two_course_repository_with_homework,
)
from tests.curriculum.utils import AISL_CONTENT, checkout, make_source

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_course_adapter():
    _clear_course_site_adapter()
    yield
    _clear_course_site_adapter()


def test_pre_core_post_and_homework_share_one_rollback_with_valid_sibling(tmp_path, monkeypatch):
    root = two_course_repository_with_homework(tmp_path)
    adapter = TransactionalCourseAdapter()
    adapter.fail_after_slugs.add("ml-zoomcamp")
    register_course_site_adapter(adapter)
    parser = CourseParser()
    source = make_source()
    core_calls = []
    homework_calls = []
    _observe_actual_core(monkeypatch, core_calls)
    _observe_actual_homework(monkeypatch, homework_calls)

    with checkout(root) as active:
        items = list(parser.discover(active, source))
        results = [parser.upsert(item, source, None) for item in items]
        with pytest.raises(CourseSitePartialError):
            parser.soft_delete_missing({item.key for item in items}, source)

    assert [result.action for result in results] == ["unchanged", "created"]
    assert core_calls == homework_calls == ["ml-zoomcamp", "agents"]
    assert not Course.objects.filter(slug="ml-zoomcamp").exists()
    assert not Homework.objects.exists()
    assert not Question.objects.exists()
    assert Course.objects.filter(slug="agents").exists()
    markers = SyncLog.objects.filter(source=source).values_list("warnings", flat=True)
    assert sorted(marker[0] for marker in markers) == ["post:agents", "pre:agents"]


def _observe_actual_core(monkeypatch, calls):
    from community_base.curriculum import content_sync_parsers

    actual = content_sync_parsers.apply_curriculum_graph

    def observed(parsed, *args, **kwargs):
        assert ACTIVE_SITE_RENDERER.get() == parsed.course.slug
        calls.append(parsed.course.slug)
        return actual(parsed, *args, **kwargs)

    monkeypatch.setattr(content_sync_parsers, "apply_curriculum_graph", observed)


def _observe_actual_homework(monkeypatch, calls):
    actual = CourseParser._apply_homework

    def observed(self, parsed, *args, **kwargs):
        assert ACTIVE_SITE_RENDERER.get() == parsed.course.slug
        calls.append(parsed.course.slug)
        return actual(self, parsed, *args, **kwargs)

    monkeypatch.setattr(CourseParser, "_apply_homework", observed)


def test_authored_parse_error_continues_sibling_and_preserves_cleanup(tmp_path):
    source = make_source()
    _run_default_parser(source, AISL_CONTENT)
    edited = tmp_path / "invalid-first-course"
    shutil.copytree(AISL_CONTENT, edited)
    course_path = edited / "courses" / "ai-hero" / "course.yaml"
    course_path.write_text(
        course_path.read_text().replace("1a2b3c4d-0001-4000-8000-000000000001", "invalid")
    )
    adapter = RecordingCourseAdapter()
    register_course_site_adapter(adapter)
    parser = CourseParser()

    with checkout(edited) as active:
        items = list(parser.discover(active, source))
        results = [parser.upsert(item, source, None) for item in items]
        with pytest.raises(CourseSitePartialError):
            parser.soft_delete_missing({item.key for item in items}, source)

    assert [result.action for result in results] == ["unchanged", "updated"]
    assert Course.objects.get(slug="ai-hero").status == "published"
    assert Course.objects.filter(slug="agents").exists()
    item, error, authored = adapter.reports[0][1][0]
    assert item.path == "courses/ai-hero/course.yaml"
    assert isinstance(error, CurriculumParseError)
    assert error.__traceback__ is not None
    assert authored is True


def _run_default_parser(source, root):
    parser = CourseParser()
    with checkout(root) as active:
        items = list(parser.discover(active, source))
        for item in items:
            parser.upsert(item, source, None)
        parser.soft_delete_missing({item.key for item in items}, source)


def test_generic_sync_reports_partial_while_site_boundary_upgrade_stays_external(tmp_path):
    source = make_source()
    _run_default_parser(source, AISL_CONTENT)
    edited = tmp_path / "fatal-second-course"
    shutil.copytree(AISL_CONTENT, edited)
    shutil.copytree(edited / "courses" / "agents", edited / "courses" / "fatal")
    manifest = edited / "content.yaml"
    agents_entry = "  - kind: course\n    path: courses/agents\n"
    fatal_entry = "  - kind: course\n    path: courses/fatal\n"
    manifest.write_text(manifest.read_text().replace(agents_entry, fatal_entry + agents_entry))
    adapter = RecordingCourseAdapter()
    adapter.boundary_slugs.add("fatal")
    register_course_site_adapter(adapter)

    log = sync_content_source(source, repo_dir=str(edited))

    assert log.status == SyncStatus.PARTIAL
    stopped_sibling = Course.objects.get(slug="agents")
    assert stopped_sibling.status == "published"
    assert not stopped_sibling.cover_image_url.startswith("site:")
    assert not Course.objects.filter(slug="fatal").exists()
    assert adapter.reports[0][0][0].detail["slug"] == "ai-hero"
    assert adapter.reports[0][3]["updated"] > 0
    assert isinstance(adapter.reports[1][1][0][1], CourseSiteBoundaryError)
    assert all(not report[2] for report in adapter.reports)
