"""Opt-in authored stepper fields use the existing coursework submission owner."""

from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from community_base.accounts.models import User
from community_base.content_sync.models import SyncStatus
from community_base.coursework.models import Homework
from community_base.coursework.question_order import ordered_questions
from community_base.homework_steps.coursework import CourseworkAdapter, coursework_assignment
from community_base.homework_steps.state import calculate_homework_state
from tests.coursework.test_course_tree import SOURCE, UNIT_ID, fixture, sync
from tests.coursework.test_course_tree import course_parser as course_parser


@pytest.fixture(autouse=True)
def registered_parser(course_parser):
    yield


@pytest.mark.django_db
def test_authored_stepper_round_trips_existing_submission_fields_and_legacy_parity(tmp_path):
    root = _stepper_source(tmp_path)
    homework = Homework.objects.get(source_content_id=UNIT_ID)
    homework.state = "OP"
    homework.save(update_fields=["state"])
    user = User.objects.create_user(email="stepper@example.invalid")
    _check_legacy_parity(user)
    assignment = coursework_assignment(homework, user)
    _check_stepper_descriptors(assignment)
    submission, answers = _submit_stepper(homework, user, assignment)
    _check_accepted_snapshot(homework, user, answers)
    path = root / SOURCE
    path.write_text(path.read_text().replace("stepper: true", "stepper: false"))
    assert sync(root).status == SyncStatus.SUCCESS
    homework.refresh_from_db()
    assert homework.stepper_enabled is False
    assert coursework_assignment(homework, user).final_fields == ()
    assert Homework.objects.get(pk=homework.pk).submissions.get(pk=submission.pk)


def _stepper_source(tmp_path):
    root = fixture(tmp_path)
    path = root / SOURCE
    path.write_text(
        path.read_text()
        .replace("form:\n", "stepper: true\nform:\n")
        .replace("    id: first\n", "    id: first\n    step_label: Check your understanding\n")
    )
    assert sync(root).status == SyncStatus.SUCCESS
    return root


def _check_legacy_parity(user):
    legacy = Homework.objects.get(slug="core")
    assignment = coursework_assignment(legacy, user)
    assert legacy.stepper_enabled is False
    assert assignment.final_fields == ()
    assert [item.key for item in assignment.questions] == [
        item.source_question_id for item in ordered_questions(legacy)
    ]


def _check_stepper_descriptors(assignment):
    assert [item.step_label for item in assignment.questions] == [
        "Check your understanding",
        "",
        "Learning in Public",
    ]
    assert [field.key for field in assignment.final_fields] == [
        "homework_link",
        "time_spent_lectures",
        "time_spent_homework",
    ]


def _submit_stepper(homework, user, assignment):
    answers = {
        "first": "b",
        "second": "Cargo",
        "learning-in-public": "https://example.com/progress",
    }
    final_fields = {
        "homework_link": "https://example.com/work",
        "time_spent_lectures": "1.50",
        "time_spent_homework": "2.25",
    }
    submission = CourseworkAdapter(homework).submit(
        SimpleNamespace(user=user), assignment, answers, final_fields
    )
    assert submission.homework_link == "https://example.com/work"
    assert submission.time_spent_lectures == 1.5
    assert submission.time_spent_homework == 2.25
    assert submission.learning_in_public_links == ["https://example.com/progress"]
    assert submission.total_score == 4
    return submission, answers


def _check_accepted_snapshot(homework, user, answers):
    accepted = coursework_assignment(homework, user)
    assert accepted.accepted_submission.answers == answers
    assert accepted.accepted_submission.final_fields == {
        "homework_link": "https://example.com/work",
        "time_spent_lectures": "1.5",
        "time_spent_homework": "2.25",
    }
    state = calculate_homework_state(accepted)
    assert state.has_pending_changes is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field_values", "public_answer"),
    [
        ({"homework_link": "bad", "time_spent_lectures": "", "time_spent_homework": ""}, ""),
        (
            {"homework_link": "https://example.com/work", "time_spent_lectures": "-1"},
            "",
        ),
        (
            {"homework_link": "https://example.com/work"},
            "https://example.com/a\nhttps://example.com/b\nhttps://example.com/c\n"
            "https://example.com/d\nhttps://example.com/e",
        ),
    ],
)
def test_stepper_rejects_invalid_final_values_without_submission(
    tmp_path, field_values, public_answer
):
    root = fixture(tmp_path)
    path = root / SOURCE
    path.write_text(path.read_text().replace("form:\n", "stepper: true\nform:\n"))
    assert sync(root).status == SyncStatus.SUCCESS
    homework = Homework.objects.get(source_content_id=UNIT_ID)
    homework.state = "OP"
    homework.save(update_fields=["state"])
    user = User.objects.create_user(email="invalid-stepper@example.invalid")
    assignment = coursework_assignment(homework, user)
    with pytest.raises(ValidationError):
        CourseworkAdapter(homework).submit(
            SimpleNamespace(user=user),
            assignment,
            {"learning-in-public": public_answer},
            field_values,
        )
    assert not homework.submissions.exists()


@pytest.mark.django_db
def test_authored_stepper_rejects_reserved_public_question_key_even_unbound(tmp_path):
    root = fixture(tmp_path, bound=False)
    path = root / SOURCE
    path.write_text(
        path.read_text()
        .replace("form:\n", "stepper: true\nform:\n")
        .replace("id: first", "id: learning-in-public")
    )
    assert sync(root).status == SyncStatus.PARTIAL
    assert Homework.objects.count() == 0
