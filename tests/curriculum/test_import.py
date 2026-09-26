"""The importer applied to what the one course parser produces."""

import shutil
import tempfile
from dataclasses import replace
from hashlib import md5
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from community_base.coursework.models import Homework, Submission
from community_base.curriculum.content_sync_parsers import CourseParser
from community_base.curriculum.models import (
    Cohort,
    CohortModule,
    Course,
    CurriculumImportRun,
    Enrollment,
    Module,
    Unit,
    UnitProgress,
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
        assert course.modules.get(slug="welcome").syllabus_section == "Getting started"
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

    def test_tree_import_reparents_unit_without_replacing_learner_or_homework_state(self):
        from tests.curriculum.utils import ParserHarness, checkout

        ParserHarness().run_parser(CourseParser(), DTC_NESTED)
        course = Course.objects.get(slug="nested-course")
        cohort = Cohort.objects.get(course=course, slug="2026")
        old_module = course.modules.get(slug="week-two")
        unit = old_module.units.get(slug="session")
        original_pk = unit.pk

        user = get_user_model().objects.create_user(email="tree-move@example.com")
        progress = UnitProgress.objects.create(user=user, unit=unit, completed_at=timezone.now())
        enrollment = Enrollment.objects.create(user=user, cohort=cohort)
        homework = Homework.objects.create(
            cohort=cohort,
            unit=unit,
            slug="session-follow-up",
            title="Session follow-up",
            due_date=timezone.now(),
        )
        submission = Submission.objects.create(
            homework=homework,
            student=user,
            enrollment=enrollment,
            problems_comments="Keep this submission attached to the moved unit.",
        )

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-move-") as tmp:
            edited = Path(tmp) / "repo"
            shutil.copytree(DTC_NESTED, edited)
            old_path = edited / "02-week-two" / "01-session.md"
            new_path = edited / "01-week-one" / "03-session.md"
            new_path.write_text(old_path.read_text())
            old_path.unlink()

            from community_base.curriculum.importing import apply_curriculum_tree
            from community_base.curriculum.parsers import parse_course_tree
            from community_base.curriculum.source import ModuleGraph, UnitGraph

            def find_unit_body_hash(module):
                for item in module.items:
                    if isinstance(item, UnitGraph) and item.content_id == str(
                        unit.source_content_id
                    ):
                        return item.content_hash
                    if isinstance(item, ModuleGraph):
                        found = find_unit_body_hash(item)
                        if found is not None:
                            return found
                return None

            def rewrite_unit_body(module):
                items = []
                for item in module.items:
                    if isinstance(item, ModuleGraph):
                        item = rewrite_unit_body(item)
                    elif item.content_id == str(unit.source_content_id):
                        item = replace(item, body="Rewritten source links.")
                    items.append(item)
                return replace(module, items=tuple(items))

            with checkout(edited, commit_sha="a" * 40) as active:
                tree = parse_course_tree(active)
                original_body_hash = next(
                    body_hash
                    for module in tree.modules
                    if (body_hash := find_unit_body_hash(module)) is not None
                )
                tree = replace(
                    tree,
                    modules=tuple(rewrite_unit_body(module) for module in tree.modules),
                )
                apply_curriculum_tree(
                    course,
                    tree,
                    commit="a" * 40,
                    checkout=active,
                )

        unit.refresh_from_db()
        progress.refresh_from_db()
        homework.refresh_from_db()
        submission.refresh_from_db()
        assert unit.pk == original_pk
        assert unit.module.slug == "week-one"
        assert unit.slug == "session"
        assert unit.body == "Rewritten source links."
        assert (
            unit.content_hash == original_body_hash == md5(b"Join the live session.\n").hexdigest()
        )
        assert progress.unit_id == original_pk
        assert homework.unit_id == original_pk
        assert submission.homework_id == homework.pk

    def test_tree_import_persists_reparent_when_unit_content_is_unchanged(self):
        from tests.curriculum.utils import ParserHarness, checkout

        ParserHarness().run_parser(CourseParser(), DTC_NESTED)
        course = Course.objects.get(slug="nested-course")
        unit = course.modules.get(slug="week-two").units.get(slug="session")

        with tempfile.TemporaryDirectory(prefix="cb-curriculum-move-clean-") as tmp:
            edited = Path(tmp) / "repo"
            shutil.copytree(DTC_NESTED, edited)
            old_path = edited / "02-week-two" / "01-session.md"
            new_path = edited / "01-week-one" / "03-session.md"
            new_path.write_text(old_path.read_text())
            old_path.unlink()

            from community_base.curriculum.importing import apply_curriculum_tree
            from community_base.curriculum.parsers import parse_course_tree

            with checkout(edited, commit_sha="b" * 40) as active:
                counts = apply_curriculum_tree(
                    course,
                    parse_course_tree(active),
                    commit="b" * 40,
                    checkout=active,
                )

        unit.refresh_from_db()
        assert unit.module.slug == "week-one"
        assert unit.source_path == "01-week-one/03-session.md"
        assert counts["updated"] == 1


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
        assert course.total_units() == len(course._countable_units())
