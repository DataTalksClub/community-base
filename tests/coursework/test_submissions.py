import pytest

from community_base.accounts.models import User
from community_base.coursework.models import Answer, Submission
from community_base.coursework.submissions import submit_homework
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import (
    coursework_cohort,
    enrollment_for,
)
from tests.coursework.test_models import (
    homework as make_homework,
)
from tests.coursework.test_models import (
    question as make_question,
)

pytestmark = pytest.mark.django_db


def any_answer_question(hw, text="What is 2+2?"):
    return make_question(hw, text=text, answer_type="ANY")


def test_submit_homework_creates_enrollment_submission_and_answers(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_HOMEWORK_SUBMITTED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    first = any_answer_question(hw)
    second = any_answer_question(hw, text="Introduce yourself")
    user = User.objects.create_user(email="submitter@example.com")

    submission = submit_homework(
        hw,
        user,
        answers_by_question_id={first.id: "4", str(second.id): "hello"},
    )

    assert submission is not None
    assert submission.enrollment.user == user
    assert Enrollment.objects.count() == 1
    assert submission.submitted_at is not None
    assert Answer.objects.count() == 2
    assert all(answer.is_correct for answer in submission.answers.all())
    assert submission.total_score == 2
    assert seen == [{"submission": submission}]


def test_closed_homework_fires_rejected_and_saves_nothing(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_HOMEWORK_SUBMISSION_REJECTED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    hw = make_homework(cohort, state="CL")
    question = any_answer_question(hw)
    _user, enrollment = enrollment_for(cohort, email="closed@example.com")

    submission = submit_homework(hw, enrollment.user, answers_by_question_id={question.id: "4"})

    assert submission is None
    assert seen == [{"homework": hw, "enrollment": enrollment, "reason": "closed"}]
    assert Submission.objects.count() == 0
    assert Answer.objects.count() == 0
    assert Enrollment.objects.count() == 1


def test_resubmission_updates_the_same_row_and_answers():
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    question = any_answer_question(hw)
    user = User.objects.create_user(email="resubmit@example.com")

    first = submit_homework(hw, user, answers_by_question_id={question.id: "first"})
    second = submit_homework(hw, user, answers_by_question_id={question.id: "second"})

    assert second.pk == first.pk
    assert Submission.objects.count() == 1
    assert Answer.objects.count() == 1
    answer = second.answers.get()
    assert answer.answer_text == "second"
    assert second.submitted_at >= first.submitted_at


def test_submit_homework_ignores_questions_outside_the_homework():
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    other = make_homework(cohort, slug="hw2", title="Homework 2")
    foreign_question = any_answer_question(other)
    user = User.objects.create_user(email="foreign@example.com")

    submission = submit_homework(
        hw, user, answers_by_question_id={foreign_question.id: "hello there"}
    )

    assert submission is not None
    assert submission.answers.count() == 0
    assert Answer.objects.count() == 0
    assert submission.total_score == 0
