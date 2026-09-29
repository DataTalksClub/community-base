"""Authored course-tree homework and explicit cohort assignment bindings."""

import shutil

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import include, path

from community_base.content_sync.check import check_repository
from community_base.content_sync.models import ContentSource, SyncStatus
from community_base.content_sync.orchestration import sync_content_source
from community_base.coursework.answer_resolution import resolve_correct_answer
from community_base.coursework.models import Homework, Question
from community_base.coursework.submissions import homework_form_context
from community_base.curriculum.models import Course, Unit
from community_base.curriculum.parsers import parse_course_repository
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.utils import DTC_REPO

UNIT_ID = "9a2b3c4d-0003-4000-8000-000000000009"
FIRST_ID = "9a2b3c4d-0006-4000-8000-000000000009"
SECOND_ID = "9a2b3c4d-0006-4000-8000-000000000010"
SOURCE = "01-core/03-quiz/homework.yaml"
COHORT = "cohorts/2026/cohort.yaml"
YAML = f"""content_id: {UNIT_ID}
title: Authored quiz
due_at: 2026-10-01T23:00:00+00:00
form:
  learning_in_public_cap: 4
questions:
  - content_id: {FIRST_ID}
    id: first
    type: multiple_choice
    prompt: Pick the second choice
    points: 2
    options:
      - {{id: a, label: Alpha}}
      - {{id: b, label: Beta}}
    correct: '2'
  - content_id: {SECOND_ID}
    id: second
    type: free_form
    prompt: Give the exact name
    points: 1
    answer_type: exact_string
    correct: 'Cargo'
"""

urlpatterns = [
    path("courses/", include("community_base.coursework.urls")),
    path("courses/", include("community_base.curriculum.urls")),
]


@pytest.fixture(autouse=True)
def course_parser():
    from community_base.content_sync import parsers
    from community_base.curriculum.apps import CONTENT_TYPE
    from community_base.curriculum.content_sync_parsers import CourseParser

    parsers._clear()
    parsers.register_parser(CONTENT_TYPE, CourseParser())
    yield
    parsers._clear()


def fixture(tmp_path, *, bound=True):
    root = tmp_path / "course"
    shutil.copytree(DTC_REPO, root)
    directory = root / "01-core/03-quiz"
    directory.mkdir()
    (directory / "homework.yaml").write_text(YAML)
    (directory / "homework.md").write_text("Read the quiz instructions.\n")
    if bound:
        with (root / COHORT).open("a") as stream:
            stream.write(f"  - module: core\n    unit: {UNIT_ID}\n")
    return root


def sync(root):
    source, _ = ContentSource.objects.get_or_create(
        slug="course-tree", defaults={"repo_name": "example/course", "webhook_secret": "fixture"}
    )
    return sync_content_source(source, repo_dir=str(root))


@pytest.mark.django_db
def test_explicit_binding_imports_source_alongside_legacy_and_keeps_answers_private(tmp_path):
    root = fixture(tmp_path)
    result = sync(root)

    assert result.status == SyncStatus.SUCCESS
    assert Homework.objects.count() == 2
    homework = Homework.objects.get(source_content_id=UNIT_ID)
    assert homework.unit_id == Unit.objects.get(source_content_id=UNIT_ID).pk
    assert homework.instructions_markdown == "Read the quiz instructions.\n"
    assert homework.due_date.isoformat() == "2026-10-01T23:00:00+00:00"
    assert homework.learning_in_public_cap == 4
    first, second = homework.questions.order_by("authored_position")
    assert (first.source_question_id, second.source_question_id) == ("first", "second")
    assert (first.correct_answer, second.correct_answer) == ("2", "Cargo")
    assert resolve_correct_answer(first) == "2"
    context = homework_form_context(homework, AnonymousUser())
    assert [row[0].pk for row in context["question_answers"]] == [first.pk, second.pk]
    assert "correct_answer" not in str(context["revealed_rows"])


@pytest.mark.django_db
def test_unbound_source_is_only_a_curriculum_unit(tmp_path):
    root = fixture(tmp_path, bound=False)
    assert sync(root).status == SyncStatus.SUCCESS
    assert Unit.objects.filter(source_content_id=UNIT_ID, kind="homework").exists()
    assert Homework.objects.count() == 1


@pytest.mark.django_db
def test_invalid_authored_answer_leaves_curriculum_and_coursework_unchanged(tmp_path):
    root = fixture(tmp_path)
    assert sync(root).status == SyncStatus.SUCCESS
    before = (
        Course.objects.count(),
        Unit.objects.count(),
        Homework.objects.count(),
        Question.objects.count(),
    )
    path = root / SOURCE
    path.write_text(path.read_text().replace("correct: '2'", "correct: '3'"))

    assert sync(root).status == SyncStatus.PARTIAL
    assert before == (
        Course.objects.count(),
        Unit.objects.count(),
        Homework.objects.count(),
        Question.objects.count(),
    )


def test_missing_companion_is_rejected_with_source_path(tmp_path):
    root = fixture(tmp_path)
    (root / "01-core/03-quiz/homework.md").unlink()
    with pytest.raises(CurriculumParseError, match="homework.md companion"):
        parse_course_repository(root)


def test_unbound_invalid_source_is_rejected_by_content_validator(tmp_path):
    root = fixture(tmp_path, bound=False)
    path = root / SOURCE
    path.write_text(path.read_text().replace("correct: '2'", "correct: '9'"))

    diagnostics = check_repository(root)

    assert any(
        item.path == SOURCE and item.pointer == "/questions/0/correct" for item in diagnostics
    )


def test_unsupported_custom_stepper_field_is_rejected_by_source_schema(tmp_path):
    root = fixture(tmp_path, bound=False)
    path = root / SOURCE
    path.write_text(
        path.read_text().replace(
            "form:\n",
            "stepper: true\nfinal_fields:\n  - {key: reflection, label: Reflection}\nform:\n",
        )
    )

    diagnostics = check_repository(root)

    assert any(item.path == SOURCE and item.pointer == "/final_fields" for item in diagnostics)


@pytest.mark.django_db
def test_unbound_invalid_source_is_rejected_before_curriculum_writes(tmp_path):
    root = fixture(tmp_path, bound=False)
    path = root / SOURCE
    path.write_text(path.read_text().replace("correct: '2'", "correct: '9'"))

    assert sync(root).status == SyncStatus.PARTIAL
    assert not Course.objects.exists()
    assert not Unit.objects.exists()


@pytest.mark.django_db
def test_duplicate_binding_is_rejected_before_writes(tmp_path):
    root = fixture(tmp_path)
    with (root / COHORT).open("a") as stream:
        stream.write(f"  - module: core\n    unit: {UNIT_ID}\n")

    assert sync(root).status == SyncStatus.PARTIAL
    assert not Course.objects.exists()
