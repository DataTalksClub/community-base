import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from community_base.coursework.display_names import ensure_display_name
from community_base.coursework.leaderboard import update_leaderboard
from community_base.coursework.models import Project, Submission
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import (
    coursework_cohort,
    create_project_submission,
    enrollment_for,
    homework,
)

pytestmark = pytest.mark.django_db


def make_project(cohort, slug="final", **values):
    values.setdefault("submission_due_date", timezone.now() + datetime.timedelta(days=7))
    values.setdefault("peer_review_due_date", timezone.now() + datetime.timedelta(days=14))
    return Project.objects.create(cohort=cohort, slug=slug, title="Final", **values)


def make_homework_submission(cohort, hw, email, total_score):
    user, enrollment = enrollment_for(cohort, email=email)
    Submission.objects.create(
        homework=hw, student=user, enrollment=enrollment, total_score=total_score
    )
    return enrollment


def make_project_submission(project, enrollment, user, **values):
    submission = create_project_submission(project, enrollment, user)
    for field, value in values.items():
        setattr(submission, field, value)
    submission.save()
    return submission


def test_update_leaderboard_sums_homework_and_project_scores(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    project = make_project(cohort)

    user_a, enrollment_a = enrollment_for(cohort, email="a@example.com")
    Submission.objects.create(homework=hw, student=user_a, enrollment=enrollment_a, total_score=4)
    make_project_submission(project, enrollment_a, user_a, total_score=6)

    user_b, enrollment_b = enrollment_for(cohort, email="b@example.com")
    Submission.objects.create(homework=hw, student=user_b, enrollment=enrollment_b, total_score=3)
    make_project_submission(
        project, enrollment_b, user_b, total_score=100, volunteer_review_only=True
    )

    update_leaderboard(cohort)

    enrollment_a.refresh_from_db()
    enrollment_b.refresh_from_db()
    assert enrollment_a.total_score == 10
    assert enrollment_b.total_score == 3  # volunteer placeholder excluded from rollup.
    assert enrollment_a.position_on_leaderboard == 1
    assert enrollment_b.position_on_leaderboard == 2


def test_enrollments_without_submissions_score_zero(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    make_homework_submission(cohort, hw, "scored@example.com", 5)
    _user, empty_enrollment = enrollment_for(cohort, email="empty@example.com")

    update_leaderboard(cohort)

    empty_enrollment.refresh_from_db()
    assert empty_enrollment.total_score == 0
    assert empty_enrollment.position_on_leaderboard == 2


def test_ranking_tie_breaks_on_enrollment_id(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    make_homework_submission(cohort, hw, "first@example.com", 5)
    make_homework_submission(cohort, hw, "second@example.com", 5)

    update_leaderboard(cohort)

    enrollments = Enrollment.objects.filter(cohort=cohort).order_by("id")
    positions = list(enrollments.values_list("position_on_leaderboard", flat=True))
    assert positions == [1, 2]


def test_hidden_enrollment_is_still_ranked(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    user, hidden = enrollment_for(cohort, email="hidden@example.com")
    hidden.display_on_leaderboard = False
    hidden.save()
    Submission.objects.create(homework=hw, student=user, enrollment=hidden, total_score=9)
    make_homework_submission(cohort, hw, "shown@example.com", 1)

    update_leaderboard(cohort)

    hidden.refresh_from_db()
    shown = Enrollment.objects.get(user__email="shown@example.com")
    assert hidden.position_on_leaderboard == 1
    assert shown.position_on_leaderboard == 2


def test_soft_deleted_enrollment_keeps_last_values_and_is_excluded(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    user, gone = enrollment_for(cohort, email="gone@example.com")
    Submission.objects.create(homework=hw, student=user, enrollment=gone, total_score=5)
    update_leaderboard(cohort)
    gone.refresh_from_db()
    assert gone.total_score == 5
    assert gone.position_on_leaderboard == 1

    gone.unenrolled_at = timezone.now()
    gone.save()
    make_homework_submission(cohort, hw, "staying@example.com", 1)

    update_leaderboard(cohort)

    gone.refresh_from_db()
    staying = Enrollment.objects.get(user__email="staying@example.com")
    assert gone.total_score == 5
    assert gone.position_on_leaderboard == 1
    assert staying.total_score == 1
    assert staying.position_on_leaderboard == 1


def test_update_leaderboard_invalidates_caches_and_bumps_version(db):
    cache.clear()
    cohort = coursework_cohort()
    cache.set(f"leaderboard:{cohort.id}", ["stale"], 60)
    cache.set(f"leaderboard_data:{cohort.id}", ["stale"], 60)
    cache.set(f"leaderboard_yaml:{cohort.id}", "stale", 60)
    cache.set(f"leaderboard_cache_version:{cohort.id}", 3, None)

    update_leaderboard(cohort)

    assert cache.get(f"leaderboard:{cohort.id}") is None
    assert cache.get(f"leaderboard_data:{cohort.id}") is None
    assert cache.get(f"leaderboard_yaml:{cohort.id}") is None
    assert cache.get(f"leaderboard_cache_version:{cohort.id}") == 4


def test_update_leaderboard_bumps_version_from_default(db):
    cache.clear()
    cohort = coursework_cohort()

    update_leaderboard(cohort)

    assert cache.get(f"leaderboard_cache_version:{cohort.id}") == 2


def test_ensure_display_name_generates_only_for_blank_names(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="named@example.com")

    calls = []

    def generator(*, enrollment):
        calls.append(enrollment)
        return "brave torvalds"

    result = ensure_display_name(enrollment, generator=generator)

    assert result == "brave torvalds"
    assert enrollment.display_name == "brave torvalds"
    enrollment.refresh_from_db()
    assert enrollment.display_name == "brave torvalds"

    result_again = ensure_display_name(enrollment, generator=generator)

    assert result_again == "brave torvalds"
    assert calls == [enrollment]  # already set: generator is never consulted.


def test_ensure_display_name_leaves_blank_when_generator_returns_nothing(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="blank@example.com")

    result = ensure_display_name(enrollment, generator=lambda enrollment: None)

    assert result == ""
    enrollment.refresh_from_db()
    assert enrollment.display_name == ""


def test_ensure_display_name_uses_configured_hook_generator(db, settings):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="hooked@example.com")
    settings.COMMUNITY_BASE = {
        "COURSEWORK_ENROLLMENT_DISPLAY_NAME_GENERATOR": lambda enrollment: "swift lovelace",
    }

    result = ensure_display_name(enrollment)

    assert result == "swift lovelace"
    enrollment.refresh_from_db()
    assert enrollment.display_name == "swift lovelace"


def test_ensure_display_name_default_hook_keeps_name_blank(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="discard@example.com")

    assert ensure_display_name(enrollment) == ""
