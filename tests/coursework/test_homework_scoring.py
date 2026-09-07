import datetime

import pytest
from django.utils import timezone

from community_base.coursework.models import (
    Answer,
    AnswerTypes,
    HomeworkStatistics,
    QuestionTypes,
    Submission,
)
from community_base.coursework.scoring import HomeworkScoringStatus, score_homework_submissions
from tests.coursework.test_models import coursework_cohort, enrollment_for, homework, question

pytestmark = pytest.mark.django_db


def make_scoreable_homework(cohort, **values):
    values.setdefault("due_date", timezone.now() - datetime.timedelta(days=1))
    hw = homework(cohort, **values)
    return question(
        hw,
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=AnswerTypes.EXACT_STRING.value,
        correct_answer="x",
    )


def make_submission(cohort, hw, q, email, answer_text="x"):
    user, enrollment = enrollment_for(cohort, email=email)
    submission = Submission.objects.create(homework=hw, student=user, enrollment=enrollment)
    answer = Answer.objects.create(submission=submission, question=q, answer_text=answer_text)
    return submission, answer


def hook_settings(seen):
    return {
        "COURSEWORK_HOMEWORK_LEADERBOARD_UPDATER": lambda **event: seen.append(
            ("leaderboard", event)
        ),
        "COURSEWORK_HOMEWORK_SCORED": lambda **event: seen.append(("scored", event)),
        "COURSEWORK_HOMEWORK_SCORING_FAILED": lambda **event: seen.append(("failed", event)),
    }


def test_score_homework_submissions_scores_persists_and_marks_scored(db, settings):
    seen = []
    settings.COMMUNITY_BASE = hook_settings(seen)
    cohort = coursework_cohort()
    q = make_scoreable_homework(cohort)
    submission, answer = make_submission(cohort, q.homework, q, "scorer@example.com")

    status, message = score_homework_submissions(q.homework_id)

    assert status is HomeworkScoringStatus.OK
    assert message == f"Homework {q.homework_id} is scored"
    submission.refresh_from_db()
    answer.refresh_from_db()
    assert submission.questions_score == 1
    assert submission.total_score == 1
    assert answer.is_correct is True
    q.homework.refresh_from_db()
    assert q.homework.is_scored() is True
    cohort.refresh_from_db()
    assert cohort.first_homework_scored is True
    assert HomeworkStatistics.objects.filter(homework=q.homework).exists()
    assert [name for name, _event in seen] == ["leaderboard", "scored"]
    assert seen[0][1]["cohort"] == cohort


def test_score_homework_submissions_refuses_future_due_date(db, settings):
    seen = []
    settings.COMMUNITY_BASE = hook_settings(seen)
    cohort = coursework_cohort()
    q = make_scoreable_homework(cohort, due_date=timezone.now() + datetime.timedelta(days=2))
    _submission, answer = make_submission(cohort, q.homework, q, "future@example.com")

    status, message = score_homework_submissions(q.homework_id)

    assert status is HomeworkScoringStatus.FAIL
    assert message == (
        f"The due date for {q.homework_id} is in the future. Update the due date to score."
    )
    q.homework.refresh_from_db()
    assert q.homework.state == "OP"
    cohort.refresh_from_db()
    assert cohort.first_homework_scored is False
    assert [name for name, _event in seen] == ["failed"]
    assert seen[0][1]["reason"] == message
    assert seen[0][1]["homework"] == q.homework
    answer.refresh_from_db()
    assert answer.is_correct is False


def test_score_homework_submissions_refuses_closed_homework(db, settings):
    seen = []
    settings.COMMUNITY_BASE = hook_settings(seen)
    cohort = coursework_cohort()
    q = make_scoreable_homework(cohort, state="CL")
    make_submission(cohort, q.homework, q, "closed@example.com")

    status, message = score_homework_submissions(q.homework_id)

    assert status is HomeworkScoringStatus.FAIL
    assert message == f"Homework {q.homework_id} is closed. Update the state to OPEN to score."
    assert [name for name, _event in seen] == ["failed"]


def test_score_homework_submissions_refuses_rescoring_without_force(db, settings):
    seen = []
    settings.COMMUNITY_BASE = hook_settings(seen)
    cohort = coursework_cohort()
    q = make_scoreable_homework(cohort)
    make_submission(cohort, q.homework, q, "already@example.com")

    first_status, _message = score_homework_submissions(q.homework_id)
    seen.clear()
    second_status, message = score_homework_submissions(q.homework_id)

    assert first_status is HomeworkScoringStatus.OK
    assert second_status is HomeworkScoringStatus.FAIL
    assert message == f"Homework {q.homework_id} is already scored."
    assert [name for name, _event in seen] == ["failed"]


def test_score_homework_submissions_force_rescores(db, settings):
    seen = []
    settings.COMMUNITY_BASE = hook_settings(seen)
    cohort = coursework_cohort()
    q = make_scoreable_homework(cohort)
    submission, _answer = make_submission(cohort, q.homework, q, "forced@example.com")

    first_status, _message = score_homework_submissions(q.homework_id)
    second_status, _message = score_homework_submissions(q.homework_id, force=True)

    assert first_status is HomeworkScoringStatus.OK
    assert second_status is HomeworkScoringStatus.OK
    submission.refresh_from_db()
    assert submission.total_score == 1
    q.homework.refresh_from_db()
    assert q.homework.is_scored() is True


def test_score_homework_submissions_marks_wrong_answers_incorrect(db, settings):
    settings.COMMUNITY_BASE = hook_settings([])
    cohort = coursework_cohort()
    q = make_scoreable_homework(cohort)
    submission, answer = make_submission(
        cohort, q.homework, q, "wrong@example.com", answer_text="not-x"
    )

    status, _message = score_homework_submissions(q.homework_id)

    assert status is HomeworkScoringStatus.OK
    submission.refresh_from_db()
    answer.refresh_from_db()
    assert answer.is_correct is False
    assert submission.questions_score == 0
    assert submission.total_score == 0
