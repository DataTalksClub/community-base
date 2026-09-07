import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils import timezone

from community_base.coursework.leaderboard_data import (
    LEADERBOARD_PAGE_SIZE,
    CurrentLeaderboardStudent,
    build_leaderboard_data,
    completed_project_submissions_prefetch,
    current_student_leaderboard_enrollment,
    current_student_page_number_for_leaderboard,
    get_leaderboard_data,
    invalidate_leaderboard_cache,
    leaderboard_cache_missing_current_student,
    leaderboard_page,
    serialize_leaderboard_enrollment,
)
from community_base.coursework.models import Project, ProjectState
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import (
    coursework_cohort,
    create_project_submission,
    enrollment_for,
)

pytestmark = pytest.mark.django_db


def make_project(cohort, slug, **values):
    values.setdefault("title", f"Project {slug}")
    values.setdefault("submission_due_date", timezone.now() + datetime.timedelta(days=7))
    values.setdefault("peer_review_due_date", timezone.now() + datetime.timedelta(days=14))
    return Project.objects.create(cohort=cohort, slug=slug, **values)


def make_completed_project(cohort, slug):
    return make_project(cohort, slug, state=ProjectState.COMPLETED.value)


def make_project_submission(project, enrollment, user, **values):
    submission = create_project_submission(project, enrollment, user)
    for field, value in values.items():
        setattr(submission, field, value)
    submission.save()
    return submission


def make_ranked_enrollment(cohort, email, **values):
    _user, enrollment = enrollment_for(cohort, email=email)
    for field, value in values.items():
        setattr(enrollment, field, value)
    enrollment.save()
    return enrollment


def anonymous_student():
    return CurrentLeaderboardStudent(enrollment=None, enrollment_id=None)


def prefetched_enrollment(enrollment):
    prefetch = completed_project_submissions_prefetch()
    return Enrollment.objects.prefetch_related(prefetch).get(pk=enrollment.pk)


def test_current_student_lookup_finds_active_enrollment(db):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="viewer@example.com")

    student = current_student_leaderboard_enrollment(cohort, user)

    assert student.enrollment_id == enrollment.id
    assert student.enrollment == enrollment


def test_current_student_lookup_ignores_unenrolled_rows(db):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="gone@example.com")
    enrollment.unenrolled_at = timezone.now()
    enrollment.save()

    student = current_student_leaderboard_enrollment(cohort, user)

    assert student.enrollment is None
    assert student.enrollment_id is None


def test_current_student_lookup_anonymous_user(db):
    cohort = coursework_cohort()

    student = current_student_leaderboard_enrollment(cohort, AnonymousUser())

    assert student.enrollment is None
    assert student.enrollment_id is None


def test_build_filters_hides_and_soft_deleted_and_orders_unranked_last(db):
    cohort = coursework_cohort()
    bronze = make_ranked_enrollment(cohort, "bronze@example.com", position_on_leaderboard=2)
    gold = make_ranked_enrollment(cohort, "gold@example.com", position_on_leaderboard=1)
    unranked = make_ranked_enrollment(cohort, "unranked@example.com", position_on_leaderboard=None)
    make_ranked_enrollment(
        cohort,
        "hidden@example.com",
        position_on_leaderboard=3,
        display_on_leaderboard=False,
    )
    make_ranked_enrollment(cohort, "unenrolled@example.com", position_on_leaderboard=4)
    Enrollment.objects.filter(user__email="unenrolled@example.com").update(
        unenrolled_at=timezone.now()
    )

    data = build_leaderboard_data(cohort, f"leaderboard:{cohort.id}")

    assert [row["id"] for row in data] == [gold.id, bronze.id, unranked.id]


def test_serialization_keeps_only_passed_projects_in_project_id_order(db):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="medals@example.com")
    first = make_completed_project(cohort, "p1")
    second = make_completed_project(cohort, "p2")
    open_project = make_project(cohort, "p3")
    make_project_submission(first, enrollment, user, passed=True)
    make_project_submission(second, enrollment, user, passed=False)
    make_project_submission(open_project, enrollment, user, passed=True)
    make_project_submission(
        first,
        enrollment,
        user,
        passed=True,
        volunteer_review_only=True,
    )

    row = serialize_leaderboard_enrollment(prefetched_enrollment(enrollment))

    assert row["id"] == enrollment.id
    assert row["display_name"] == enrollment.display_name
    assert row["total_score"] == enrollment.total_score
    assert row["position_on_leaderboard"] == enrollment.position_on_leaderboard
    # The completed prefetch excludes the volunteer placeholder and the
    # not-yet-completed project; the failed attempt keeps its attempt slot.
    assert row["passed_projects"] == [
        {
            "title": first.title,
            "slug": first.slug,
            "attempt": 1,
            "medal_index": 1,
        }
    ]


def test_medal_index_wraps_every_five_projects(db):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="collector@example.com")
    for index in range(1, 8):
        project = make_completed_project(cohort, f"p{index}")
        make_project_submission(project, enrollment, user, passed=True)

    row = serialize_leaderboard_enrollment(prefetched_enrollment(enrollment))

    assert [entry["attempt"] for entry in row["passed_projects"]] == [1, 2, 3, 4, 5, 6, 7]
    assert [entry["medal_index"] for entry in row["passed_projects"]] == [1, 2, 3, 4, 5, 1, 2]


def test_get_leaderboard_data_serves_cached_payload_on_hit(db):
    cache.clear()
    cohort = coursework_cohort()
    make_ranked_enrollment(cohort, "cached@example.com", position_on_leaderboard=1)

    first = get_leaderboard_data(cohort, anonymous_student())
    cached = cache.get(f"leaderboard:{cohort.id}")
    make_ranked_enrollment(cohort, "late@example.com", position_on_leaderboard=2)
    second = get_leaderboard_data(cohort, anonymous_student())

    assert cached is not None
    assert len(cached) == 1
    assert first == second == cached  # cache hit: the late enrollment is invisible.


def test_get_leaderboard_data_rebuilds_when_visible_student_missing_from_cache(db):
    cache.clear()
    cohort = coursework_cohort()
    get_leaderboard_data(cohort, anonymous_student())
    _user, enrollment = enrollment_for(cohort, email="lateviewer@example.com")
    enrollment.position_on_leaderboard = 1
    enrollment.save()
    student = CurrentLeaderboardStudent(enrollment=enrollment, enrollment_id=enrollment.id)

    data = get_leaderboard_data(cohort, student)

    assert [row["id"] for row in data] == [enrollment.id]
    assert [row["id"] for row in cache.get(f"leaderboard:{cohort.id}")] == [enrollment.id]


def test_cache_missing_check_ignores_hidden_students(db):
    cohort = coursework_cohort()
    _user, hidden = enrollment_for(cohort, email="hider@example.com")
    hidden.display_on_leaderboard = False
    hidden.save()
    hidden_student = CurrentLeaderboardStudent(enrollment=hidden, enrollment_id=hidden.id)

    assert leaderboard_cache_missing_current_student([{"id": 999}], hidden_student) is False
    assert leaderboard_cache_missing_current_student([{"id": 999}], anonymous_student()) is False

    hidden.display_on_leaderboard = True
    visible_student = CurrentLeaderboardStudent(enrollment=hidden, enrollment_id=hidden.id)
    assert leaderboard_cache_missing_current_student([{"id": 999}], visible_student) is True


def test_current_student_page_number(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="paged@example.com")
    # Large row ids avoid colliding with the viewer's enrollment id.
    data = [{"id": 10000 + index} for index in range(LEADERBOARD_PAGE_SIZE + 5)]
    data.append({"id": enrollment.id})
    student = CurrentLeaderboardStudent(enrollment=enrollment, enrollment_id=enrollment.id)

    assert current_student_page_number_for_leaderboard(data, student) == 2
    assert current_student_page_number_for_leaderboard(data, anonymous_student()) is None

    enrollment.display_on_leaderboard = False
    assert current_student_page_number_for_leaderboard(data, student) is None


def test_leaderboard_page_paginates_serialized_rows(db):
    data = [{"id": index} for index in range(1, LEADERBOARD_PAGE_SIZE + 11)]

    page_one = leaderboard_page(data, 1)
    page_two = leaderboard_page(data, 2)

    assert page_one["total"] == LEADERBOARD_PAGE_SIZE + 10
    assert len(page_one["rows"]) == LEADERBOARD_PAGE_SIZE
    assert page_one["page_number"] == 1
    assert len(page_two["rows"]) == 10
    assert page_two["page_number"] == 2


def test_invalidate_leaderboard_cache_deletes_page_key_and_bumps_version(db):
    cache.clear()
    cohort = coursework_cohort()
    cache.set(f"leaderboard:{cohort.id}", ["stale"], 60)
    cache.set(f"leaderboard_cache_version:{cohort.id}", 7, None)

    invalidate_leaderboard_cache(cohort.id)

    assert cache.get(f"leaderboard:{cohort.id}") is None
    assert cache.get(f"leaderboard_cache_version:{cohort.id}") == 8
