"""The importer applied to what the one course parser produces."""

import shutil
import tempfile
from pathlib import Path

from django.test import TestCase

from community_base.curriculum.content_sync_parsers import CourseParser
from community_base.curriculum.models import (
    Cohort,
    CohortModule,
    Course,
    CurriculumImportRun,
    Module,
    Unit,
)
from community_base.curriculum.parsers import PARSER_VERSION
from community_base.events.models import Host
from tests.curriculum.utils import AISL_CONTENT, AISL_ROOT, DTC_NESTED, DTC_REPO


class ImportTests(TestCase):
    def import_fixture(self, fixture):
        from tests.curriculum.utils import ParserHarness

        return ParserHarness().run_parser(CourseParser(), fixture)

    def test_every_course_collection_of_one_repository_is_imported(self):
        """A repository of two courses imports two, not the first one it sniffs."""

        _source, items, results, _drafted = self.import_fixture(AISL_CONTENT)

        assert [item.key for item in items] == ["courses/ai-hero", "courses/agents"]
        assert all(result.action == "created" for result in results)
        assert set(Course.objects.values_list("slug", flat=True)) == {"ai-hero", "agents"}

    def test_aisl_import_creates_rows(self):
        self.import_fixture(AISL_CONTENT)

        course = Course.objects.get(slug="ai-hero")
        assert course.source_content_id is not None
        assert course.status == "published"
        assert course.description_html  # rendered on save
        cohort = Cohort.objects.get(course=course, mode="self_paced")
        assert list(cohort.effective_modules()) == list(course.modules.filter(parent__isnull=True))
        assert course.modules.filter(parent__isnull=True).count() == 2
        assert course.total_units() == 3

    def test_aisl_import_links_instructor_host(self):
        self.import_fixture(AISL_CONTENT)

        host = Host.objects.get(name="Ada Lovelace")
        assert host.kind == "instructor"
        assert host.slug == "ada-lovelace"
        course = Course.objects.get(slug="ai-hero")
        assert list(course.ordered_instructors) == [host]

    def test_aisl_reimport_is_unchanged(self):
        self.import_fixture(AISL_CONTENT)
        _source, _items, results, _drafted = self.import_fixture(AISL_CONTENT)

        assert all(result.action == "unchanged" for result in results)
        assert Course.objects.filter(slug="ai-hero").count() == 1
        assert Unit.objects.filter(module__course__slug="ai-hero").count() == 3

    def test_root_level_repository_imports(self):
        """The `course.yaml` at a repository root the old adapter skipped."""

        self.import_fixture(AISL_ROOT)

        course = Course.objects.get(slug="python")
        assert course.required_level == 30
        assert Unit.objects.filter(module__course=course).count() == 4
        # The bonus module's two units are tracked but stay out of the denominator.
        assert course.total_units() == 2
        assert course.modules.get(slug="projects").is_bonus is True

    def test_dtc_import_creates_rows(self):
        self.import_fixture(DTC_REPO)

        course = Course.objects.get(slug="ml-zoomcamp")
        assert course.description == "Learn machine learning by building four projects."
        cohorts = {cohort.slug: cohort for cohort in course.cohorts.all()}
        assert set(cohorts) == {"2026", "2024"}
        assert cohorts["2026"].start_date is not None
        (placement,) = CohortModule.objects.filter(cohort=cohorts["2026"])
        module = placement.module
        assert module.slug == "core"
        assert module.units.count() == 2
        assert module.units.get(slug="lesson").video_url == "https://youtu.be/xyz"

    def test_an_archived_cohort_places_nothing_after_import(self):
        self.import_fixture(DTC_REPO)

        archived = Cohort.objects.get(course__slug="ml-zoomcamp", slug="2024")
        assert not CohortModule.objects.filter(cohort=archived).exists()

    def test_dtc_reimport_is_unchanged(self):
        self.import_fixture(DTC_REPO)
        _source, _items, results, _drafted = self.import_fixture(DTC_REPO)

        assert all(result.action == "unchanged" for result in results)
        assert Course.objects.filter(slug="ml-zoomcamp").count() == 1

    def test_removed_unit_is_deleted_on_reimport(self):
        self.import_fixture(DTC_REPO)

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-edit-") as tmp:
            edited = Path(tmp) / "repo"
            shutil.copytree(DTC_REPO, edited)
            (edited / "01-core" / "02-homework.md").unlink()
            (edited / "cohorts" / "2026" / "cohort.yaml").write_text(
                (edited / "cohorts" / "2026" / "cohort.yaml")
                .read_text()
                .replace("    unit: 9a2b3c4d-0003-4000-8000-000000000002\n", "")
            )
            from tests.curriculum.utils import ParserHarness

            ParserHarness().run_parser_with_source(
                CourseParser(), edited, slug="edit-source", repo="example/edit-source"
            )

        course = Course.objects.get(slug="ml-zoomcamp")
        module = course.modules.get(slug="core")
        assert list(module.units.values_list("slug", flat=True)) == ["lesson"]

    def test_removed_course_is_drafted(self):
        from tests.curriculum.utils import checkout as open_checkout
        from tests.curriculum.utils import make_source

        source = make_source(slug="vanish", repo="example/vanish")
        parser = CourseParser()
        with open_checkout(AISL_CONTENT) as active:
            items = list(parser.discover(active, source))
            for item in items:
                parser.upsert(item, source, None)
            parser.soft_delete_missing({item.key for item in items}, source)
        assert Course.objects.get(slug="ai-hero").status == "published"

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-empty-") as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with open_checkout(empty) as active:
                items = list(parser.discover(active, source))
                deleted = parser.soft_delete_missing({item.key for item in items}, source)

        assert items == []
        assert sorted(course.slug for course in deleted) == ["agents", "ai-hero"]
        assert Course.objects.get(slug="ai-hero").status == "draft"

    def test_import_run_is_recorded(self):
        self.import_fixture(DTC_REPO)

        run = CurriculumImportRun.objects.get(
            source_stable_id="ml-zoomcamp", state=CurriculumImportRun.State.SUCCEEDED
        )
        assert run.parser_version == PARSER_VERSION
        assert run.schema_version == 1
        assert run.repository_name == "fixture-source"
        assert run.repository_owner == "example"
        assert run.counts["created"] >= 5
        assert run.manifest_checksum
        assert run.finished_at is not None

    def test_commit_sha_of_the_checkout_is_carried(self):
        from tests.curriculum.utils import ParserHarness

        sha = "a" * 40
        ParserHarness().run_parser(CourseParser(), DTC_REPO, commit_sha=sha)

        assert CurriculumImportRun.objects.filter(commit_sha=sha).exists()


class NestedImportTests(TestCase):
    """Two module levels, including the exact sibling-slug-collision case."""

    def import_nested(self):
        from tests.curriculum.utils import ParserHarness

        return ParserHarness().run_parser(CourseParser(), DTC_NESTED)

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

    def test_a_cohort_placement_is_a_subset_of_the_course_tree(self):
        self.import_nested()

        course = Course.objects.get(slug="nested-course")
        cohort = Cohort.objects.get(course=course, slug="2026")
        assert [module.slug for module in cohort.effective_modules()] == ["week-two"]
        assert [module.slug for module in course.modules.filter(parent__isnull=True)] == [
            "week-one",
            "week-two",
        ]


class DefaultTreeTests(TestCase):
    """A cohort that places nothing shows the course's own tree."""

    def test_self_paced_cohort_shows_the_full_tree(self):
        from tests.curriculum.utils import ParserHarness

        ParserHarness().run_parser(CourseParser(), AISL_CONTENT)

        course = Course.objects.get(slug="ai-hero")
        cohort = Cohort.objects.get(course=course, mode="self_paced")
        assert not CohortModule.objects.filter(cohort=cohort).exists()
        assert list(cohort.effective_modules()) == list(
            course.modules.filter(parent__isnull=True).order_by("sort_order", "pk")
        )
        for module in course.modules.all():
            assert module.parent_id is None
        assert course.total_units() == course._countable_units().count()
