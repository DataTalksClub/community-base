"""Leaderboard read model: filter, order, paginate, serialize and cache.

Ported from the DTC donor ``courses/views/course_leaderboard_data.py``. The
donor keeps this logic inside a view module; the package exposes it as a
service so views and member APIs share one implementation. View-only pieces
(template context with paginator objects) stay in the sites; ``leaderboard_page``
returns plain rows and pagination data.

Package adaptations (recorded for donor-data verification in A5.1):

- The donor ``Enrollment.course`` field points at the cohort model; the
  package names the parameter ``cohort`` explicitly.
- Package enrollments are soft-deleted through ``unenrolled_at``; the read
  model lists only active enrollments and the current-student lookup ignores
  unenrolled rows, matching the conditional unique constraint on active rows.
- The completed-projects prefetch uses the package ``project_submissions``
  related name instead of the donor's default reverse accessor.
"""

import logging
from dataclasses import dataclass

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Prefetch, Value
from django.db.models.functions import Coalesce

from community_base.coursework.models import ProjectState, ProjectSubmission
from community_base.curriculum.models import Enrollment

logger = logging.getLogger(__name__)

LEADERBOARD_PAGE_SIZE = 100
LEADERBOARD_CACHE_TTL_SECONDS = 3600


@dataclass(frozen=True)
class CurrentLeaderboardStudent:
    enrollment: Enrollment | None
    enrollment_id: int | None


def invalidate_leaderboard_cache(cohort_id: int) -> None:
    cache.delete(f"leaderboard:{cohort_id}")
    version_key = f"leaderboard_cache_version:{cohort_id}"
    current_version = cache.get(version_key, 1)
    next_version = current_version + 1
    cache.set(version_key, next_version, None)


def current_student_leaderboard_enrollment(cohort, user) -> CurrentLeaderboardStudent:
    if user.is_authenticated:
        try:
            enrollment = Enrollment.objects.get(
                user=user,
                cohort=cohort,
                unenrolled_at__isnull=True,
            )
            return CurrentLeaderboardStudent(
                enrollment=enrollment,
                enrollment_id=enrollment.id,
            )
        except Enrollment.DoesNotExist:
            pass

    return CurrentLeaderboardStudent(enrollment=None, enrollment_id=None)


def completed_project_submissions_prefetch():
    submissions = ProjectSubmission.objects.filter(
        project__state=ProjectState.COMPLETED.value,
        volunteer_review_only=False,
    )
    submissions = submissions.select_related("project")
    submissions = submissions.order_by("project__id")
    return Prefetch(
        "project_submissions",
        queryset=submissions,
        to_attr="completed_project_submissions",
    )


def serialize_leaderboard_enrollment(enrollment):
    passed_projects = []
    completed_submissions = enrollment.completed_project_submissions
    for index, submission in enumerate(completed_submissions, 1):
        if not submission.passed:
            continue
        passed_project = {
            "title": submission.project.title,
            "slug": submission.project.slug,
            "attempt": index,
            "medal_index": ((index - 1) % 5) + 1,
        }
        passed_projects.append(passed_project)

    return {
        "id": enrollment.id,
        "display_name": enrollment.display_name,
        "total_score": enrollment.total_score,
        "position_on_leaderboard": enrollment.position_on_leaderboard,
        "passed_projects": passed_projects,
    }


def build_leaderboard_data(cohort, cache_key):
    logger.info(f"Cache miss for leaderboard of cohort {cohort.slug}")
    enrollments = Enrollment.objects.filter(
        cohort=cohort,
        display_on_leaderboard=True,
        unenrolled_at__isnull=True,
    )
    enrollments = enrollments.select_related("user")
    completed_submissions = completed_project_submissions_prefetch()
    enrollments = enrollments.prefetch_related(completed_submissions)
    unranked_position = Value(999999)
    leaderboard_position = Coalesce(
        "position_on_leaderboard",
        unranked_position,
    )
    enrollments = enrollments.order_by(leaderboard_position, "id")
    enrollments_data = []
    for enrollment in enrollments:
        enrollment_data = serialize_leaderboard_enrollment(enrollment)
        enrollments_data.append(enrollment_data)
    cache.set(cache_key, enrollments_data, LEADERBOARD_CACHE_TTL_SECONDS)
    return enrollments_data


def leaderboard_cache_missing_current_student(
    enrollments_data,
    current_student: CurrentLeaderboardStudent,
):
    if current_student.enrollment_id is None:
        return False
    if not current_student.enrollment.display_on_leaderboard:
        return False

    for enrollment in enrollments_data:
        if enrollment["id"] == current_student.enrollment_id:
            return False

    return True


def get_leaderboard_data(
    cohort,
    current_student: CurrentLeaderboardStudent,
):
    cache_key = f"leaderboard:{cohort.id}"
    enrollments_data = cache.get(cache_key)

    if enrollments_data is None:
        return build_leaderboard_data(cohort, cache_key)

    logger.info(f"Cache hit for leaderboard of cohort {cohort.slug}")
    if leaderboard_cache_missing_current_student(
        enrollments_data,
        current_student,
    ):
        return build_leaderboard_data(cohort, cache_key)

    return enrollments_data


def current_student_page_number_for_leaderboard(
    enrollments_data,
    current_student: CurrentLeaderboardStudent,
):
    if (
        current_student.enrollment_id is None
        or not current_student.enrollment.display_on_leaderboard
    ):
        return None

    for index, enrollment in enumerate(enrollments_data):
        if enrollment["id"] == current_student.enrollment_id:
            return (index // LEADERBOARD_PAGE_SIZE) + 1

    return None


def leaderboard_page(enrollments_data, page_number):
    """Paginate serialized rows; keeps the donor's elided page range behavior."""
    paginator = Paginator(enrollments_data, LEADERBOARD_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    return {
        "rows": list(page_obj.object_list),
        "page_number": page_obj.number,
        "page_range": list(paginator.get_elided_page_range(page_obj.number)),
        "total": paginator.count,
    }
