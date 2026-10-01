import shutil
from dataclasses import replace

import pytest

from community_base.content_sync.checkout import CheckoutError
from community_base.content_sync.models import SyncStatus
from community_base.content_sync.orchestration import sync_content_source
from community_base.coursework.models import Homework
from community_base.curriculum.content_sync_parsers import CourseParser
from community_base.curriculum.models import Course, CurriculumImportRun, Module, Unit
from community_base.curriculum.site_adaptation import (
    CourseSiteBoundaryError,
    CourseSitePartialError,
    _clear_course_site_adapter,
    register_course_site_adapter,
)
from tests.curriculum.course_site_fixtures import RecordingCourseAdapter
from tests.curriculum.utils import AISL_CONTENT, DTC_REPO, checkout, make_source

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_course_adapter():
    _clear_course_site_adapter()
    yield
    _clear_course_site_adapter()


def run_items(parser, root, source):
    with checkout(root) as active:
        items = list(parser.discover(active, source))
        results = [parser.upsert(item, source, None) for item in items]
        drafted = parser.soft_delete_missing({item.key for item in items}, source)
    return items, results, drafted


def test_registration_rejects_a_different_adapter():
    adapter = RecordingCourseAdapter()
    assert register_course_site_adapter(adapter) is adapter
    assert register_course_site_adapter(adapter) is adapter

    with pytest.raises(ValueError, match="already registered"):
        register_course_site_adapter(RecordingCourseAdapter())


def test_parser_created_before_registration_looks_up_adapter_at_discovery():
    parser = CourseParser()
    adapter = RecordingCourseAdapter()
    register_course_site_adapter(adapter)

    run_items(parser, AISL_CONTENT, make_source())

    assert adapter.events[0] == ("prepare", "ai-hero")


def test_site_lifecycle_rewrites_render_fields_and_package_calls_core_once(monkeypatch):
    adapter = RecordingCourseAdapter()
    register_course_site_adapter(adapter)
    calls = []
    from community_base.curriculum import content_sync_parsers

    original = content_sync_parsers.apply_curriculum_graph

    def counted_apply(*args, **kwargs):
        calls.append(args[0].course.slug)
        return original(*args, **kwargs)

    monkeypatch.setattr(content_sync_parsers, "apply_curriculum_graph", counted_apply)
    source = make_source()

    items, results, drafted = run_items(CourseParser(), AISL_CONTENT, source)

    assert len(items) == len(results) == 2
    assert drafted == []
    assert calls == ["ai-hero", "agents"]
    assert Course.objects.get(slug="ai-hero").cover_image_url.startswith("site:")
    assert adapter.events[:4] == [
        ("prepare", "ai-hero"),
        ("scope-enter", "ai-hero"),
        ("after", "ai-hero"),
        ("scope-exit", "ai-hero"),
    ]


def test_incompatible_identity_fails_before_scope_or_writes():
    adapter = RecordingCourseAdapter()
    adapter.incompatible_slugs.add("ai-hero")
    register_course_site_adapter(adapter)
    parser = CourseParser()
    source = make_source()

    with checkout(AISL_CONTENT) as active:
        items = list(parser.discover(active, source))
        result = parser.upsert(items[0], source, None)
        with pytest.raises(CourseSitePartialError):
            parser.soft_delete_missing({item.key for item in items}, source)

    assert result.action == "unchanged"
    assert not Course.objects.exists()
    assert not CurriculumImportRun.objects.exists()
    assert not any(event[0] == "scope-enter" for event in adapter.events)


def test_scope_suppression_rolls_back_core_and_fails_closed():
    adapter = RecordingCourseAdapter()
    adapter.suppressed_slugs.add("ai-hero")
    register_course_site_adapter(adapter)
    parser = CourseParser()
    source = make_source()

    with checkout(AISL_CONTENT) as active:
        (item, *_rest) = parser.discover(active, source)
        result = parser.upsert(item, source, None)
        with pytest.raises(CourseSitePartialError):
            parser.soft_delete_missing({item.key}, source)

    assert result.action == "unchanged"
    assert not Course.objects.exists()
    assert not CurriculumImportRun.objects.exists()


def test_post_apply_failure_rolls_back_item_continues_sibling_and_skips_cleanup():
    source = make_source()
    run_items(CourseParser(), AISL_CONTENT, source)
    adapter = RecordingCourseAdapter()
    adapter.fail_after_slugs.add("ai-hero")
    register_course_site_adapter(adapter)
    parser = CourseParser()

    with checkout(AISL_CONTENT) as active:
        items = list(parser.discover(active, source))
        results = [parser.upsert(item, source, None) for item in items]
        with pytest.raises(CourseSitePartialError):
            parser.soft_delete_missing({item.key for item in items}, source)

    assert [result.action for result in results] == ["unchanged", "updated"]
    assert Course.objects.get(slug="ai-hero").status == "published"
    assert Course.objects.filter(slug="agents").exists()
    assert adapter.reports[0][1][0][2] is False


def test_nonfatal_item_failure_makes_the_package_run_partial():
    adapter = RecordingCourseAdapter()
    adapter.fail_after_slugs.add("ai-hero")
    register_course_site_adapter(adapter)
    source = make_source()

    log = sync_content_source(source, repo_dir=str(AISL_CONTENT))

    assert log.status == SyncStatus.PARTIAL
    assert not Course.objects.filter(slug="ai-hero").exists()
    assert Course.objects.filter(slug="agents").exists()


@pytest.mark.parametrize("error_type", [CheckoutError, CourseSiteBoundaryError])
def test_accepted_details_survive_a_later_fatal_checkout(error_type):
    adapter = RecordingCourseAdapter()
    register_course_site_adapter(adapter)
    parser = CourseParser()
    source = make_source()

    with checkout(AISL_CONTENT) as active:
        items = list(parser.discover(active, source))
        parser.upsert(items[0], source, None)
        adapter.boundary_slugs.add("agents")
        if error_type is CheckoutError:
            adapter.boundary_error = CheckoutError
        with pytest.raises(error_type):
            parser.upsert(items[1], source, None)

    first_results, first_errors, _drafted, first_totals = adapter.reports[0]
    assert first_results[0].detail["slug"] == "ai-hero"
    assert first_errors == ()
    assert first_totals["created"] > 0
    assert adapter.reports[1][1][0][1].args[0].startswith("checkout refused")


def test_authored_refusal_is_distinct_from_an_internal_failure():
    adapter = RecordingCourseAdapter()
    adapter.refused_slugs.add("ai-hero")
    adapter.fail_after_slugs.add("agents")
    register_course_site_adapter(adapter)
    parser = CourseParser()
    source = make_source()

    with checkout(AISL_CONTENT) as active:
        items = list(parser.discover(active, source))
        for item in items:
            parser.upsert(item, source, None)

    assert adapter.reports[0][1][0][2] is True
    assert adapter.reports[1][1][0][2] is False


def test_safe_warning_allows_stale_cleanup_and_reports_partial(tmp_path):
    source = make_source()
    run_items(CourseParser(), AISL_CONTENT, source)
    edited = tmp_path / "one-course"
    shutil.copytree(AISL_CONTENT, edited)
    shutil.rmtree(edited / "courses" / "agents")
    manifest = edited / "content.yaml"
    agents_entry = "  - kind: course\n    path: courses/agents\n"
    manifest.write_text(manifest.read_text().replace(agents_entry, ""))
    adapter = RecordingCourseAdapter()
    adapter.warning_slugs.add("ai-hero")
    register_course_site_adapter(adapter)
    parser = CourseParser()

    with checkout(edited) as active:
        items = list(parser.discover(active, source))
        parser.upsert(items[0], source, None)
        with pytest.raises(CourseSitePartialError):
            parser.soft_delete_missing({items[0].key}, source)

    assert Course.objects.get(slug="agents").status == "draft"
    assert adapter.reports[-1][2][0].slug == "agents"


def test_render_rewrite_preserves_persisted_homework_bindings_and_repeat_identity():
    adapter = RecordingCourseAdapter()
    register_course_site_adapter(adapter)
    source = make_source()
    parser = CourseParser()

    with checkout(DTC_REPO) as active:
        item = parser.discover(active, source)[0]
        parsed = parser._parse(item)
        course, binding = render_rewritten_course(parsed)
        adapter._prepared_course = lambda _course: course
        parser.upsert(item, source, None)
        parser.soft_delete_missing({item.key}, source)

    identities = assert_persisted_binding(binding)

    _items, results, drafted = run_items(CourseParser(), DTC_REPO, source)
    assert results[0].action == "unchanged"
    assert drafted == []
    assert assert_persisted_binding(binding) == identities


def render_rewritten_course(parsed):
    binding = None
    for cohort in parsed.course.cohorts:
        if cohort.slug == "2026":
            (binding,) = cohort.homework_bindings
    assert binding is not None
    module = parsed.course.modules[0]
    unit = replace(module.units[1], body="site body", homework="site homework")
    rewritten = replace(module, overview="site overview", units=(module.units[0], unit))
    course = replace(
        parsed.course,
        cover_image_url="site cover",
        modules=(rewritten, *parsed.course.modules[1:]),
    )
    return course, binding


def assert_persisted_binding(binding):
    course = Course.objects.get(slug="ml-zoomcamp")
    module = Module.objects.get(course=course, slug=binding["module"])
    unit = Unit.objects.get(source_content_id=binding["unit"])
    homework = Homework.objects.get(cohort__slug="2026")
    questions = tuple(homework.questions.order_by("authored_position"))
    assert homework.module_id == module.pk
    assert homework.unit_id == unit.pk
    assert homework.instructions_source_path.endswith("homework/core/homework.md")
    assert len(questions) == 2
    assert all(question.homework_id == homework.pk for question in questions)
    assert unit.body == "site body"
    assert unit.homework == "site homework"
    return course.pk, module.pk, unit.pk, homework.pk, tuple(question.pk for question in questions)


def test_changed_homework_binding_fails_before_scope_or_writes():
    adapter = RecordingCourseAdapter()

    def change_binding(course):
        cohort = replace(course.cohorts[0], homework_bindings=())
        return replace(course, cohorts=(cohort,))

    adapter._prepared_course = change_binding
    register_course_site_adapter(adapter)
    source = make_source()
    parser = CourseParser()

    with checkout(DTC_REPO) as active:
        (item,) = parser.discover(active, source)
        result = parser.upsert(item, source, None)

    assert result.action == "unchanged"
    assert not Course.objects.exists()
    assert not any(event[0] == "scope-enter" for event in adapter.events)
