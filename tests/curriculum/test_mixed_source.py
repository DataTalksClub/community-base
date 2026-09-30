"""A course module can interleave direct units and child modules."""

import shutil

import pytest

from community_base.content_sync.check import check_repository
from community_base.curriculum.content_sync_parsers import CourseParser
from community_base.curriculum.models import Course, Module, Unit
from community_base.curriculum.parsers import parse_course_repository
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.utils import DTC_NESTED


def mixed_course(tmp_path):
    root = tmp_path / "mixed-course"
    shutil.copytree(DTC_NESTED, root)
    week = root / "01-week-one"
    (week / "02-topic-b").rename(week / "03-topic-b")
    (week / "02-direct.md").write_text(
        "---\n"
        "content_id: 2b3c4d5e-000b-4000-8000-000000000001\n"
        "title: Direct lesson\n"
        "---\n"
        "A direct lesson between the two topics.\n"
    )
    return root


def mixed_homework_course(tmp_path):
    root = mixed_course(tmp_path)
    directory = root / "01-week-one" / "04-quiz"
    directory.mkdir()
    (directory / "homework.yaml").write_text(
        "content_id: 2b3c4d5e-000c-4000-8000-000000000001\n"
        "title: Authored quiz\n"
        "due_at: 2026-10-01T23:00:00+00:00\n"
        "questions:\n"
        "  - content_id: 2b3c4d5e-000d-4000-8000-000000000001\n"
        "    id: first\n"
        "    type: multiple_choice\n"
        "    prompt: Pick the second choice\n"
        "    points: 2\n"
        "    options:\n"
        "      - {id: a, label: Alpha}\n"
        "      - {id: b, label: Beta}\n"
        "    correct: '2'\n"
    )
    (directory / "homework.md").write_text("Read the authored quiz instructions.\n")
    cohort = root / "cohorts" / "2026" / "cohort.yaml"
    cohort.write_text(
        cohort.read_text().replace("  - week-two\n", "  - week-one\n  - week-two\n")
        + "homework:\n"
        + "  - module: week-one\n"
        + "    unit: 2b3c4d5e-000c-4000-8000-000000000001\n"
    )
    return root


def test_mixed_siblings_parse_in_authored_order(tmp_path):
    parsed = parse_course_repository(mixed_course(tmp_path))

    week = parsed.course.modules[0]
    assert [unit.slug for unit in week.units] == ["direct"]
    assert [child.slug for child in week.children] == ["topic-a", "topic-b"]
    assert [(type(node).__name__, node.slug) for node in week.siblings] == [
        ("ModuleGraph", "topic-a"),
        ("UnitGraph", "direct"),
        ("ModuleGraph", "topic-b"),
    ]


def test_mixed_yaml_homework_keeps_its_level_and_source_order(tmp_path):
    root = mixed_homework_course(tmp_path)
    assert check_repository(root) == []

    week = parse_course_repository(root).course.modules[0]
    assert [(type(node).__name__, node.slug) for node in week.siblings] == [
        ("ModuleGraph", "topic-a"),
        ("UnitGraph", "direct"),
        ("ModuleGraph", "topic-b"),
        ("UnitGraph", "quiz"),
    ]
    assert [node.source_sibling_position for node in week.siblings] == [0, 1, 2, 3]
    assert week.units[-1].kind == "homework"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("01-direct.md", "mixed sibling order"),
        ("direct.md", "needs authored order"),
        ("02-topic-a.md", "duplicate sibling slug"),
    ],
)
def test_mixed_siblings_reject_ambiguous_order_or_slug(tmp_path, name, message):
    root = mixed_course(tmp_path)
    week = root / "01-week-one"
    (week / "02-direct.md").rename(week / name)

    with pytest.raises(CurriculumParseError, match=message):
        parse_course_repository(root)


@pytest.mark.django_db
def test_mixed_import_persists_source_order_separately_from_public_order(tmp_path):
    from community_base.coursework.models import Homework
    from tests.curriculum.utils import ParserHarness

    root = mixed_homework_course(tmp_path)
    ParserHarness().run_parser(CourseParser(), root)

    course = Course.objects.get(slug="nested-course")
    week = Module.objects.get(course=course, slug="week-one")
    direct = Unit.objects.get(module=week, slug="direct")
    quiz = Unit.objects.get(module=week, slug="quiz")
    assert direct.source_sibling_position == 1
    assert quiz.source_sibling_position == 3
    children = week.children.order_by("source_sibling_position")
    assert list(children.values_list("source_sibling_position", flat=True)) == [0, 2]
    assert direct.sort_order == 2
    assert quiz.sort_order == 4
    homework = Homework.objects.get(unit=quiz)
    assert homework.instructions_markdown == "Read the authored quiz instructions.\n"


@pytest.mark.django_db
def test_mixed_replay_and_move_preserve_unit_identity_and_progress(tmp_path):
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from community_base.curriculum.models import UnitProgress
    from tests.curriculum.utils import ParserHarness

    root = mixed_homework_course(tmp_path)
    harness = ParserHarness()
    harness.run_parser(CourseParser(), root)
    direct = Unit.objects.get(slug="direct")
    progress = UnitProgress.objects.create(
        user=get_user_model().objects.create(), unit=direct, completed_at=timezone.now()
    )
    harness.run_parser(CourseParser(), root)
    assert Unit.objects.get(slug="direct").pk == direct.pk

    (root / "01-week-one" / "02-direct.md").rename(
        root / "01-week-one" / "01-topic-a" / "02-direct.md"
    )
    harness.run_parser(CourseParser(), root)

    direct.refresh_from_db()
    assert direct.module.slug == "topic-a"
    assert direct.source_sibling_position is None
    assert UnitProgress.objects.get(pk=progress.pk).unit_id == direct.pk


@pytest.mark.django_db
def test_mixed_yaml_homework_move_preserves_unit_and_assignment_identity(tmp_path):
    from community_base.coursework.models import Homework, Question
    from tests.curriculum.utils import ParserHarness

    root = mixed_homework_course(tmp_path)
    harness = ParserHarness()
    harness.run_parser(CourseParser(), root)
    quiz = Unit.objects.get(slug="quiz")
    homework = Homework.objects.get(unit=quiz)
    question = Question.objects.get(homework=homework)

    (root / "01-week-one" / "04-quiz").rename(root / "01-week-one" / "01-topic-a" / "02-quiz")
    harness.run_parser(CourseParser(), root)

    quiz.refresh_from_db()
    homework.refresh_from_db()
    assert quiz.module.slug == "topic-a"
    assert quiz.source_sibling_position is None
    assert homework.unit_id == quiz.pk
    assert Question.objects.get(homework=homework).pk == question.pk
