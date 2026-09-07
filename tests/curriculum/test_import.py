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
    Course,
    CurriculumImportRun,
    Unit,
)
from community_base.curriculum.parsers_aisl import parse_aisl_course
from community_base.curriculum.parsers_dtc import parse_dtc_course_repository
from community_base.events.models import Host
from tests.curriculum.utils import AISL_CONTENT, DTC_REPO, checkout

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
        assert [module.slug for module in cohort.modules] == ["welcome", "retrieval"]

        welcome = cohort.modules[0]
        assert "# Welcome" in welcome.overview
        assert "Overview" in welcome.overview
        assert [unit.slug for unit in welcome.units] == ["setup", "exercise"]
        assert welcome.units[0].required_level == 0
        assert welcome.units[0].video_url.endswith("/abc")
        assert welcome.units[0].body.startswith("Body for")
        assert welcome.units[1].body.startswith("Do the homework.")
        assert cohort.modules[1].units[0].homework.startswith("Write a retrieval")


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
        assert modules_cohort.modules[0].slug == "core"
        assert modules_cohort.modules[0].units[0].video_url == "https://youtu.be/xyz"
        assert by_slug["2025"].curriculum_format == "legacy"
        assert by_slug["2025"].modules == ()


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
        assert cohort.modules.count() == 2
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
        assert Unit.objects.filter(module__cohort__course__slug="ai-hero").count() == 3

    def test_dtc_import_creates_rows(self):
        self.import_dtc()

        course = Course.objects.get(slug="ml-zoomcamp")
        assert course.description == "Learn machine learning by building four projects."
        cohorts = {cohort.slug: cohort for cohort in course.cohorts.all()}
        assert set(cohorts) == {"2026", "2025"}
        assert cohorts["2026"].start_date is not None
        module = cohorts["2026"].modules.get(slug="core")
        assert module.units.count() == 2
        assert module.units.get(slug="lesson").video_url == "https://youtu.be/xyz"

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
        module = course.cohorts.get(slug="2026").modules.get(slug="core")
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
