import shutil
import tempfile
from pathlib import Path

from django.test import TestCase

from community_base.curriculum.content_sync_parsers import (
    AislCourseParser,
    DtcCourseRepositoryParser,
)
from community_base.curriculum.models import (
    Cohort,
    CohortModule,
    Course,
    CurriculumImportRun,
    Module,
    Unit,
)
from community_base.curriculum.parsers_aisl import parse_aisl_course
from community_base.curriculum.parsers_dtc import parse_dtc_course_repository
from community_base.curriculum.source import CurriculumParseError
from community_base.events.models import Host
from tests.curriculum.utils import AISL_CONTENT, AISL_CONTENT_NESTED, DTC_REPO, checkout

COURSE_ID = "1a2b3c4d-0001-4000-8000-000000000001"
DTC_COURSE_ID = "9a2b3c4d-0001-4000-8000-000000000001"


class AislParserTests(TestCase):
    def test_parses_course_graph(self):
        with checkout(AISL_CONTENT) as active:
            parsed = parse_aisl_course(active, "courses/ai-hero/course.yaml")

        course = parsed.course
        assert course.slug == "ai-hero"
        assert course.title == "AI Hero Crash Course"
        assert course.required_level == 0
        assert course.default_unit_required_level == 5
        assert course.status == "published"
        assert "applied" in course.description
        assert course.instructors[0].name == "Ada Lovelace"

        (cohort,) = course.cohorts
        assert cohort.mode == "self_paced"
        assert cohort.curriculum_format == "modules"
        assert cohort.module_refs is None  # no placement rows: default to the full tree
        assert [module.slug for module in course.modules] == ["welcome", "retrieval"]

        welcome = course.modules[0]
        assert "# Welcome" in welcome.overview
        assert "Overview" in welcome.overview
        assert [unit.slug for unit in welcome.units] == ["setup", "exercise"]
        assert welcome.units[0].required_level == 0
        assert welcome.units[0].video_url.endswith("/abc")
        assert welcome.units[0].body.startswith("Body for")
        assert welcome.units[1].body.startswith("Do the homework.")
        assert course.modules[1].units[0].homework.startswith("Write a retrieval")


class DtcParserTests(TestCase):
    def test_parses_course_repository_graph(self):
        with checkout(DTC_REPO) as active:
            parsed = parse_dtc_course_repository(active)

        course = parsed.course
        assert course.slug == "ml-zoomcamp"
        assert course.visible is True
        assert course.description == "Learn machine learning by building four projects."
        assert course.hashtag == "mlzoomcamp"

        by_slug = {cohort.slug: cohort for cohort in course.cohorts}
        assert set(by_slug) == {"2026", "2025"}
        modules_cohort = by_slug["2026"]
        assert modules_cohort.curriculum_format == "modules"
        assert modules_cohort.module_refs == ("9a2b3c4d-0002-4000-8000-000000000001",)
        (core,) = [module for module in course.modules if module.slug == "core"]
        assert core.units[0].video_url == "https://youtu.be/xyz"
        assert by_slug["2025"].curriculum_format == "legacy"
        assert by_slug["2025"].module_refs == ()


class ImportTests(TestCase):
    def import_aisl(self):
        from tests.curriculum.utils import ParserHarness

        return ParserHarness().run_parser(AislCourseParser(), AISL_CONTENT)

    def import_dtc(self):
        from tests.curriculum.utils import ParserHarness

        return ParserHarness().run_parser(DtcCourseRepositoryParser(), DTC_REPO)

    def test_aisl_import_creates_rows(self):
        _source, _items, results, _drafted = self.import_aisl()

        course = Course.objects.get(slug="ai-hero")
        assert course.source_content_id is not None
        assert course.status == "published"
        assert course.description_html  # rendered on save
        cohort = Cohort.objects.get(course=course, mode="self_paced")
        assert list(cohort.effective_modules()) == list(course.modules.filter(parent__isnull=True))
        assert course.modules.filter(parent__isnull=True).count() == 2
        assert course.total_units() == 3
        assert results and results[0].action == "created"

    def test_aisl_import_links_instructor_host(self):
        self.import_aisl()

        host = Host.objects.get(name="Ada Lovelace")
        assert host.kind == "instructor"
        course = Course.objects.get(slug="ai-hero")
        assert list(course.ordered_instructors) == [host]

    def test_aisl_reimport_is_unchanged(self):
        self.import_aisl()
        _source, _items, results, _drafted = self.import_aisl()

        assert all(result.action == "unchanged" for result in results)
        assert Course.objects.filter(slug="ai-hero").count() == 1
        assert Unit.objects.filter(module__course__slug="ai-hero").count() == 3

    def test_dtc_import_creates_rows(self):
        self.import_dtc()

        course = Course.objects.get(slug="ml-zoomcamp")
        assert course.description == "Learn machine learning by building four projects."
        cohorts = {cohort.slug: cohort for cohort in course.cohorts.all()}
        assert set(cohorts) == {"2026", "2025"}
        assert cohorts["2026"].start_date is not None
        (placement,) = CohortModule.objects.filter(cohort=cohorts["2026"])
        module = placement.module
        assert module.slug == "core"
        assert module.units.count() == 2
        assert module.units.get(slug="lesson").video_url == "https://youtu.be/xyz"
        assert list(cohorts["2025"].effective_modules()) == list(
            course.modules.filter(parent__isnull=True)
        )

    def test_dtc_reimport_is_unchanged(self):
        self.import_dtc()
        _source, _items, results, _drafted = self.import_dtc()

        assert all(result.action == "unchanged" for result in results)
        assert Course.objects.filter(slug="ml-zoomcamp").count() == 1

    def test_removed_unit_is_deleted_on_reimport(self):
        self.import_dtc()

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-edit-") as tmp:
            edited = Path(tmp) / "repo"
            shutil.copytree(DTC_REPO, edited)
            (edited / "core" / "homework.md").unlink()
            module_yaml = edited / "core" / "module.yaml"
            module_yaml.write_text(
                module_yaml.read_text()
                .replace("  - content_id: 9a2b3c4d-0003-4000-8000-000000000002\n", "")
                .replace("    title: Homework intro\n    path: homework.md\n", "")
            )
            from tests.curriculum.utils import ParserHarness

            source_results = ParserHarness().run_parser_with_source(
                DtcCourseRepositoryParser(), edited, slug="edit-source"
            )

        del source_results
        course = Course.objects.get(slug="ml-zoomcamp")
        module = course.modules.get(slug="core")
        assert list(module.units.values_list("slug", flat=True)) == ["lesson"]

    def test_removed_course_is_drafted(self):
        from tests.curriculum.utils import checkout, make_source

        source = make_source(slug="vanish", repo="example/vanish")
        with checkout(AISL_CONTENT) as active:
            parser = AislCourseParser()
            items = list(parser.discover(active, source))
            for item in items:
                parser.upsert(item, source, None)
            parser.soft_delete_missing({item.key for item in items}, source)
        assert Course.objects.get(slug="ai-hero").status == "published"

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-empty-") as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with checkout(empty) as active:
                items = list(parser.discover(active, source))
                deleted = parser.soft_delete_missing({item.key for item in items}, source)

        assert items == []
        assert [course.slug for course in deleted] == ["ai-hero"]
        assert Course.objects.get(slug="ai-hero").status == "draft"

    def test_import_run_is_recorded(self):
        self.import_dtc()

        run = CurriculumImportRun.objects.get(
            source_stable_id="ml-zoomcamp", state=CurriculumImportRun.State.SUCCEEDED
        )
        assert run.parser_version == "dtc-course-repository-1"
        assert run.schema_version == 1
        assert run.repository_name == "fixture-source"
        assert run.repository_owner == "example"
        assert run.counts["created"] >= 5
        assert run.manifest_checksum
        assert run.finished_at is not None


class AislNestedParserTests(TestCase):
    """Nested module directories (community-base#252): ``01-module/01-submodule/01-unit.md``."""

    def test_parses_nested_tree_with_numeric_prefixes_stripped(self):
        with checkout(AISL_CONTENT_NESTED) as active:
            parsed = parse_aisl_course(active, "courses/nested-course/course.yaml")

        modules = parsed.course.modules
        assert [module.slug for module in modules] == ["week-one", "week-two"]

        week_one = modules[0]
        assert week_one.available_after_days == 7
        assert week_one.units == ()  # a module with children has no direct units
        assert [child.slug for child in week_one.children] == ["topic-a", "topic-b"]
        topic_a, topic_b = week_one.children
        assert [unit.slug for unit in topic_a.units] == ["section-overview"]
        assert [unit.slug for unit in topic_b.units] == ["section-overview"]
        assert topic_a.units[0].title == "Section Overview"
        assert topic_a.units[0].body.startswith("Overview for topic A")
        assert topic_b.units[0].body.startswith("Overview for topic B")

        week_two = modules[1]
        assert week_two.children == ()
        event, extra = week_two.units
        assert event.kind == "event"
        assert event.session_position == 1
        assert extra.is_bonus is True
        assert event.is_bonus is False

    def test_rejects_module_with_both_children_and_units(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-mixed-") as tmp:
            edited = Path(tmp) / "repo"
            shutil.copytree(AISL_CONTENT_NESTED, edited)
            stray = edited / "courses" / "nested-course" / "01-week-one" / "99-stray-unit.md"
            stray.write_text(
                "---\ncontent_id: 2b3c4d5e-000a-4000-8000-000000000001\n"
                "title: Stray\n---\nShould not be allowed here.\n"
            )
            with checkout(edited) as active, self.assertRaises(CurriculumParseError) as caught:
                parse_aisl_course(active, "courses/nested-course/course.yaml")

        assert "01-week-one" in str(caught.exception)

    def test_rejects_three_levels_deep(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-deep-") as tmp:
            edited = Path(tmp) / "repo"
            shutil.copytree(AISL_CONTENT_NESTED, edited)
            deep_dir = (
                edited / "courses" / "nested-course" / "01-week-one" / "01-topic-a" / "01-too-deep"
            )
            deep_dir.mkdir()
            (deep_dir / "module.yaml").write_text(
                "content_id: 2b3c4d5e-000b-4000-8000-000000000001\ntitle: Too deep\n"
            )
            with checkout(edited) as active, self.assertRaises(CurriculumParseError):
                parse_aisl_course(active, "courses/nested-course/course.yaml")


class NestedImportTests(TestCase):
    """Full import of a nested tree, including the exact sibling-slug-collision case."""

    def import_nested(self):
        from tests.curriculum.utils import ParserHarness

        return ParserHarness().run_parser(AislCourseParser(), AISL_CONTENT_NESTED)

    def test_two_submodules_each_with_section_overview_sync_cleanly(self):
        """The exact case that produced 26 collisions on the flattened site content."""

        _source, _items, results, _drafted = self.import_nested()

        assert results and results[0].action == "created"
        course = Course.objects.get(slug="nested-course")
        week_one = course.modules.get(slug="week-one")
        topic_a = Module.objects.get(course=course, parent=week_one, slug="topic-a")
        topic_b = Module.objects.get(course=course, parent=week_one, slug="topic-b")

        overview_a = topic_a.units.get(slug="section-overview")
        overview_b = topic_b.units.get(slug="section-overview")
        assert overview_a.pk != overview_b.pk
        assert overview_a.title == overview_b.title == "Section Overview"
        assert Unit.objects.filter(slug="section-overview").count() == 2

    def test_nested_import_sets_kind_and_bonus(self):
        self.import_nested()

        course = Course.objects.get(slug="nested-course")
        week_two = course.modules.get(slug="week-two")
        assert week_two.units.get(slug="session").kind == "event"
        assert week_two.units.get(slug="session").session_position == 1
        assert week_two.units.get(slug="extra").is_bonus is True

    def test_nested_reimport_is_unchanged(self):
        self.import_nested()
        _source, _items, results, _drafted = self.import_nested()

        assert all(result.action == "unchanged" for result in results)
        assert Course.objects.filter(slug="nested-course").count() == 1
        assert Unit.objects.filter(slug="section-overview").count() == 2

    def test_nested_import_self_paced_cohort_shows_full_tree(self):
        self.import_nested()

        course = Course.objects.get(slug="nested-course")
        cohort = Cohort.objects.get(course=course, mode="self_paced")
        assert not CohortModule.objects.filter(cohort=cohort).exists()
        assert list(cohort.effective_modules()) == list(
            course.modules.filter(parent__isnull=True).order_by("sort_order", "pk")
        )


class BackwardCompatibilityTests(TestCase):
    """Every existing (two-level, unnested) course behaves identically after this change."""

    def test_existing_flat_course_has_no_parent_and_default_kind(self):
        from tests.curriculum.utils import ParserHarness

        ParserHarness().run_parser(AislCourseParser(), AISL_CONTENT)

        course = Course.objects.get(slug="ai-hero")
        for module in course.modules.all():
            assert module.parent_id is None
            assert module.is_bonus is False
            assert module.available_after_days is None
        for unit in Unit.objects.filter(module__course=course):
            assert unit.kind == "lesson" or (unit.kind == "homework" and unit.homework)
            assert unit.is_bonus is False
            assert unit.session_position is None

        cohort = Cohort.objects.get(course=course, mode="self_paced")
        assert not CohortModule.objects.filter(cohort=cohort).exists()
        assert list(cohort.effective_modules()) == list(
            course.modules.filter(parent__isnull=True).order_by("sort_order", "pk")
        )
        assert course.total_units() == course._countable_units().count()
