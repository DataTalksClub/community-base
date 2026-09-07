import datetime

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    Answer,
    AnswerTypes,
    QuestionTypes,
    Submission,
)
from community_base.coursework.question_stats import homework_question_stats
from community_base.coursework.reminders import (
    HOMEWORK_DEADLINE_PURPOSE,
    send_homework_deadline_reminders,
)
from community_base.coursework.scoring import update_score
from community_base.coursework.statistics import (
    calculate_homework_statistics,
    calculate_raw_homework_statistics,
)
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import coursework_cohort, homework, question

pytestmark = pytest.mark.django_db


def make_submission(cohort, hw, email="learner@example.com", **submission_values):
    user = User.objects.create_user(email=email)
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    return Submission.objects.create(
        homework=hw, student=user, enrollment=enrollment, **submission_values
    )


def test_update_score_sums_questions_and_rewards(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    q1 = question(
        hw,
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=AnswerTypes.EXACT_STRING.value,
        correct_answer="x",
        scores_for_correct_answer=2,
    )
    q2 = question(
        hw,
        text="Second",
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=AnswerTypes.EXACT_STRING.value,
        correct_answer="y",
    )
    user = User.objects.create_user(email="scorer@example.com")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    submission = Submission.objects.create(homework=hw, student=user, enrollment=enrollment)
    answers = [
        Answer.objects.create(submission=submission, question=q1, answer_text="x"),
        Answer.objects.create(submission=submission, question=q2, answer_text="wrong"),
    ]

    update_score(submission, answers)

    assert submission.questions_score == 2
    assert submission.total_score == 2
    assert answers[0].is_correct is True
    assert answers[1].is_correct is False


def test_learning_in_public_disabled_zeroes_score(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    user = User.objects.create_user(email="quiet@example.com")
    enrollment = Enrollment.objects.create(
        user=user, cohort=cohort, disable_learning_in_public=True
    )
    submission = Submission.objects.create(
        homework=hw,
        student=user,
        enrollment=enrollment,
        learning_in_public_links=["https://example.com/post"],
    )

    update_score(submission, [])

    assert submission.learning_in_public_score == 0
    assert submission.total_score == 0


def test_faq_and_learning_in_public_scores(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    user = User.objects.create_user(email="public@example.com")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    submission = Submission.objects.create(
        homework=hw,
        student=user,
        enrollment=enrollment,
        learning_in_public_links=["https://a.example", "https://b.example"],
        faq_contribution_url="https://github.com/example/pull/1",
    )

    update_score(submission, [])

    assert submission.learning_in_public_score == 2
    assert submission.faq_score == 1
    assert submission.total_score == 3


def test_homework_statistics_requires_scored_state(db):
    cohort = coursework_cohort()
    hw = homework(cohort)

    with pytest.raises(ValueError):
        calculate_homework_statistics(hw)


def test_homework_statistics_compute_distribution(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    scores = [0, 5, 10]
    for index, score in enumerate(scores):
        user = User.objects.create_user(email=f"stat{index}@example.com")
        enrollment = Enrollment.objects.create(user=user, cohort=cohort)
        Submission.objects.create(
            homework=hw, student=user, enrollment=enrollment, total_score=score
        )
    hw.state = "SC"
    hw.save()

    stats = calculate_homework_statistics(hw, force=True)

    assert stats.total_submissions == 3
    assert stats.min_total_score == 0
    assert stats.max_total_score == 10
    assert stats.avg_total_score == 5
    raw = calculate_raw_homework_statistics(hw)
    assert raw["total_score"]["median"] == 5


def test_homework_question_stats_counts(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    q = question(
        hw,
        question_type=QuestionTypes.MULTIPLE_CHOICE.value,
        possible_answers="A\nB",
        correct_answer="1",
    )
    user = User.objects.create_user(email="qstat@example.com")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    submission = Submission.objects.create(homework=hw, student=user, enrollment=enrollment)
    Answer.objects.create(submission=submission, question=q, answer_text="1", is_correct=True)

    stats = homework_question_stats(hw)

    assert len(stats) == 1
    stat = stats[0]
    assert stat.total == 1
    assert stat.correct == 1
    assert stat.pct_correct == 100.0
    assert stat.choice_options[0].is_correct is True
    assert stat.choice_options[0].count == 1
    assert stat.choice_options[1].count == 0


def test_homework_deadline_reminder_handler_sends_and_is_idempotent(db, settings):
    from community_base.mail.models import EmailDelivery

    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_BACKEND": "memory",
    }
    cohort = coursework_cohort()
    homework(cohort, due_date=timezone.now() + datetime.timedelta(days=2))
    user = User.objects.create_user(email="reminder@example.com")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)

    first = send_homework_deadline_reminders(None, {})
    second = send_homework_deadline_reminders(None, {})

    assert first == {"reminders": 1}
    assert second == {"reminders": 1}
    deliveries = EmailDelivery.objects.filter(purpose=HOMEWORK_DEADLINE_PURPOSE)
    assert deliveries.count() == 1
    assert deliveries.get().recipient_email == user.email
    assert deliveries.get().idempotency_key.startswith("coursework.homework_deadline:")
    assert enrollment.id
