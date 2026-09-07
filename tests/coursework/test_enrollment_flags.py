import pytest
from django.core.cache import cache
from django.utils import timezone

from community_base.coursework.enrollment_flags import set_learning_in_public_disabled
from community_base.coursework.models import Project, ProjectSubmission, Submission
from tests.coursework.test_models import (
    coursework_cohort,
    create_project_submission,
    enrollment_for,
    homework,
)

pytestmark = pytest.mark.django_db


def make_project(cohort):
    return Project.objects.create(
        cohort=cohort,
        slug="final",
        title="Final",
        submission_due_date=timezone.now(),
        peer_review_due_date=timezone.now(),
    )


def make_scored_rows(cohort):
    hw = homework(cohort)
    project = make_project(cohort)
    user, enrollment = enrollment_for(cohort, email="quiet@example.com")
    submission = Submission.objects.create(
        homework=hw,
        student=user,
        enrollment=enrollment,
        questions_score=4,
        faq_score=1,
        learning_in_public_score=3,
        total_score=8,
    )
    project_submission = create_project_submission(project, enrollment, user)
    project_submission.project_score = 6
    project_submission.project_faq_score = 2
    project_submission.peer_review_score = 3
    project_submission.project_learning_in_public_score = 2
    project_submission.peer_review_learning_in_public_score = 1
    project_submission.total_score = 14
    project_submission.save()
    return enrollment, submission, project_submission


def test_disabling_zeroes_learning_in_public_scores_and_refreshes(db):
    cohort = coursework_cohort()
    enrollment, submission, project_submission = make_scored_rows(cohort)
    cache.set(f"leaderboard:{cohort.id}", ["stale"], 60)

    set_learning_in_public_disabled(enrollment, True)

    enrollment.refresh_from_db()
    submission.refresh_from_db()
    project_submission.refresh_from_db()
    assert enrollment.disable_learning_in_public is True
    assert submission.learning_in_public_score == 0
    assert submission.total_score == 5  # questions_score + faq_score.
    assert project_submission.project_learning_in_public_score == 0
    assert project_submission.peer_review_learning_in_public_score == 0
    assert project_submission.total_score == 11  # project + faq + peer review.
    assert enrollment.total_score == 16  # leaderboard refreshed in the same transaction.
    assert enrollment.position_on_leaderboard == 1
    assert cache.get(f"leaderboard:{cohort.id}") is None


def test_disabling_keeps_rows_without_learning_in_public_score(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    user, enrollment = enrollment_for(cohort, email="nolip@example.com")
    submission = Submission.objects.create(
        homework=hw,
        student=user,
        enrollment=enrollment,
        questions_score=2,
        faq_score=1,
        learning_in_public_score=0,
        total_score=3,
    )

    set_learning_in_public_disabled(enrollment, True)

    submission.refresh_from_db()
    assert submission.total_score == 3
    assert submission.questions_score == 2
    assert submission.faq_score == 1


def test_enabling_saves_flag_without_zeroing(db):
    cohort = coursework_cohort()
    enrollment, submission, project_submission = make_scored_rows(cohort)

    set_learning_in_public_disabled(enrollment, False)

    enrollment.refresh_from_db()
    submission.refresh_from_db()
    project_submission.refresh_from_db()
    assert enrollment.disable_learning_in_public is False
    assert submission.learning_in_public_score == 3
    assert submission.total_score == 8
    assert project_submission.project_learning_in_public_score == 2
    assert project_submission.peer_review_learning_in_public_score == 1
    assert project_submission.total_score == 14
    assert enrollment.total_score == 22


def test_zeroing_ignores_other_enrollments(db):
    cohort = coursework_cohort()
    enrollment, submission, _project_submission = make_scored_rows(cohort)
    other_hw = homework(cohort, slug="hw2", title="Homework 2")
    other_user, other_enrollment = enrollment_for(cohort, email="other@example.com")
    other_submission = Submission.objects.create(
        homework=other_hw,
        student=other_user,
        enrollment=other_enrollment,
        questions_score=1,
        faq_score=0,
        learning_in_public_score=4,
        total_score=5,
    )

    set_learning_in_public_disabled(enrollment, True)

    other_submission.refresh_from_db()
    other_enrollment.refresh_from_db()
    assert other_submission.learning_in_public_score == 4
    assert other_submission.total_score == 5
    assert other_enrollment.total_score == 5
    assert other_enrollment.position_on_leaderboard == 2
    enrollment.refresh_from_db()
    assert enrollment.total_score == 16
    assert enrollment.position_on_leaderboard == 1
    assert ProjectSubmission.objects.filter(enrollment=enrollment).exists()
