"""Leaderboard recompute, read model and learner leaderboard surfaces.

Ported from the donor ``courses/leaderboard.py``,
``courses/views/course_leaderboard*.py`` and
``courses/views/course_enrollment.py``. The donor's ``course`` is the package
``Cohort`` everywhere; enrollment display preferences, display-name defaults and
complaints travel with the leaderboard because the donor couples them.
"""

import logging
from dataclasses import dataclass

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Prefetch, Sum, Value, When
from django.db.models.functions import Coalesce

from community_base.coursework.hooks import hooks as coursework_hooks
from community_base.coursework.models import (
    HomeworkState,
    LeaderboardComplaint,
    ProjectState,
    ProjectSubmission,
    Submission,
)
from community_base.curriculum.models import Enrollment

logger = logging.getLogger(__name__)

LEADERBOARD_PAGE_SIZE = 100
LEADERBOARD_CACHE_TTL = 3600
UNRANKED_POSITION = 999999

ENROLLMENT_PREFERENCE_FIELDS = ("display_on_leaderboard", "display_public_profile")


def _homework_scores_by_enrollment(cohort):
    rows = (
        Submission.objects.filter(homework__cohort=cohort)
        .values("enrollment_id")
        .annotate(total_score=Sum("total_score"))
    )
    return {row["enrollment_id"]: row["total_score"] for row in rows}


def _project_scores_by_enrollment(cohort):
    rows = (
        ProjectSubmission.objects.filter(project__cohort=cohort, volunteer_review_only=False)
        .values("enrollment_id")
        .annotate(total_score=Sum("total_score"))
    )
    return {row["enrollment_id"]: row["total_score"] for row in rows}


def _enrollment_leaderboard_sort_key(enrollment):
    total_score = enrollment.total_score or 0
    return -total_score, enrollment.id


def _rank_enrollments(enrollments):
    ranked = sorted(enrollments, key=_enrollment_leaderboard_sort_key)
    for rank, enrollment in enumerate(ranked, 1):
        enrollment.position_on_leaderboard = rank


def _update_enrollment_totals(cohort):
    homework_scores = _homework_scores_by_enrollment(cohort)
    project_scores = _project_scores_by_enrollment(cohort)
    enrollments = list(Enrollment.objects.filter(cohort=cohort))
    for enrollment in enrollments:
        enrollment.total_score = (homework_scores.get(enrollment.id, 0) or 0) + (
            project_scores.get(enrollment.id, 0) or 0
        )
    _rank_enrollments(enrollments)
    Enrollment.objects.bulk_update(
        enrollments,
        ["total_score", "position_on_leaderboard"],
    )
    return enrollments


def _bump_leaderboard_cache_version(cohort_id):
    version_key = f"leaderboard_cache_version:{cohort_id}"
    current_version = cache.get(version_key, 1)
    cache.set(version_key, current_version + 1, None)


def invalidate_leaderboard_cache(cohort_id):
    """Drop the paginated read model and bump the site export version key."""

    cache.delete(f"leaderboard:{cohort_id}")
    _bump_leaderboard_cache_version(cohort_id)


def update_leaderboard(cohort):
    """Recompute totals and positions for one cohort, then invalidate caches."""

    _update_enrollment_totals(cohort)
    cache.delete(f"leaderboard:{cohort.id}")
    cache.delete(f"leaderboard_data:{cohort.id}")
    _bump_leaderboard_cache_version(cohort.id)
    logger.info("Updated leaderboard for cohort %s", cohort.id)


@dataclass(frozen=True)
class CurrentLeaderboardStudent:
    enrollment: Enrollment | None
    enrollment_id: int | None


def current_student_leaderboard_enrollment(cohort, user) -> CurrentLeaderboardStudent:
    if user.is_authenticated:
        enrollment = (
            Enrollment.objects.filter(cohort=cohort, user=user, unenrolled_at__isnull=True)
            .order_by("id")
            .first()
        )
        if enrollment is not None:
            return CurrentLeaderboardStudent(
                enrollment=enrollment,
                enrollment_id=enrollment.id,
            )
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
    for index, submission in enumerate(enrollment.completed_project_submissions, 1):
        if not submission.passed:
            continue
        passed_projects.append(
            {
                "title": submission.project.title,
                "slug": submission.project.slug,
                "attempt": index,
                "medal_index": ((index - 1) % 5) + 1,
            }
        )

    return {
        "id": enrollment.id,
        "display_name": enrollment.display_name,
        "total_score": enrollment.total_score,
        "position_on_leaderboard": enrollment.position_on_leaderboard,
        "passed_projects": passed_projects,
    }


def build_leaderboard_data(cohort, cache_key):
    enrollments = (
        Enrollment.objects.filter(cohort=cohort, display_on_leaderboard=True)
        .select_related("user")
        .prefetch_related(completed_project_submissions_prefetch())
        .order_by(
            Coalesce("position_on_leaderboard", Value(UNRANKED_POSITION)),
            "id",
        )
    )
    enrollments_data = [serialize_leaderboard_enrollment(enrollment) for enrollment in enrollments]
    cache.set(cache_key, enrollments_data, LEADERBOARD_CACHE_TTL)
    return enrollments_data


def leaderboard_cache_missing_current_student(enrollments_data, current_student):
    if current_student.enrollment_id is None:
        return False
    if not current_student.enrollment.display_on_leaderboard:
        return False
    return not any(row["id"] == current_student.enrollment_id for row in enrollments_data)


def get_leaderboard_data(cohort, current_student):
    cache_key = f"leaderboard:{cohort.id}"
    enrollments_data = cache.get(cache_key)
    if enrollments_data is None:
        return build_leaderboard_data(cohort, cache_key)
    if leaderboard_cache_missing_current_student(enrollments_data, current_student):
        return build_leaderboard_data(cohort, cache_key)
    return enrollments_data


def current_student_page_number_for_leaderboard(enrollments_data, current_student):
    if current_student.enrollment_id is None:
        return None
    if not current_student.enrollment.display_on_leaderboard:
        return None
    for index, row in enumerate(enrollments_data):
        if row["id"] == current_student.enrollment_id:
            return (index // LEADERBOARD_PAGE_SIZE) + 1
    return None


def leaderboard_context(cohort, user, page_number):
    """Context for the public leaderboard page."""

    current_student = current_student_leaderboard_enrollment(cohort, user)
    enrollments_data = get_leaderboard_data(cohort, current_student)
    paginator = Paginator(enrollments_data, LEADERBOARD_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    page_range = paginator.get_elided_page_range(page_obj.number)
    return {
        "cohort": cohort,
        "page_obj": page_obj,
        "page_range": page_range,
        "current_student_enrollment": current_student.enrollment,
        "current_student_enrollment_id": current_student.enrollment_id,
        "current_student_page_number": current_student_page_number_for_leaderboard(
            enrollments_data,
            current_student,
        ),
    }


def leaderboard_score_breakdown_context(enrollment, user):
    """Per-enrollment score breakdown honouring the profile visibility rules."""

    is_own_record = user.is_authenticated and user.id == enrollment.user_id
    public_profile = None
    if enrollment.display_public_profile:
        public_profile = enrollment.user
    show_public_profile_settings_link = is_own_record and public_profile is None
    return {
        "enrollment": enrollment,
        "public_profile": public_profile,
        "show_public_profile_settings_link": show_public_profile_settings_link,
        "submissions": leaderboard_homework_submissions(enrollment),
        "project_submissions": ProjectSubmission.objects.filter(
            enrollment=enrollment,
            volunteer_review_only=False,
        )
        .select_related("project")
        .order_by("project__id"),
    }


def leaderboard_homework_submissions(enrollment):
    submissions = Submission.objects.filter(enrollment=enrollment).select_related("homework")
    return submissions.order_by(leaderboard_homework_state_order(), "homework__id")


def leaderboard_homework_state_order():
    return Case(
        When(homework__state=HomeworkState.SCORED.value, then=Value(0)),
        When(homework__state=HomeworkState.OPEN.value, then=Value(1)),
        When(homework__state=HomeworkState.CLOSED.value, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )


def _preference_enabled(value) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def set_enrollment_preference(cohort, user, field, value):
    """Toggle one enrollment display preference; returns (enrollment, enabled, changed).

    Raises ``ValueError`` for a field outside ``ENROLLMENT_PREFERENCE_FIELDS``
    (donor parity: the view turns that into a 400) and ``Enrollment.DoesNotExist``
    when the user has no active enrollment in the cohort.
    """

    if field not in ENROLLMENT_PREFERENCE_FIELDS:
        raise ValueError(f"Unknown enrollment preference field: {field}")
    enrollment = Enrollment.objects.get(cohort=cohort, user=user, unenrolled_at__isnull=True)
    enabled = _preference_enabled(value)
    previous = getattr(enrollment, field)
    setattr(enrollment, field, enabled)
    enrollment.save(update_fields=[field])
    changed = previous != enabled
    if changed:
        if field == "display_on_leaderboard":
            invalidate_leaderboard_cache(cohort.id)
        coursework_hooks.enrollment_preferences_updated(
            enrollment=enrollment,
            field=field,
            value=enabled,
        )
    return enrollment, enabled, changed


def ensure_display_name(enrollment, generator=None):
    """Fill a blank leaderboard name in place; returns the display name.

    The donor generates ``"<adjective> <famous person>"`` from site word lists;
    the word lists stay site-side, so the package default generator is a plain
    fallback and sites override ``COURSEWORK_DISPLAY_NAME_GENERATOR``.
    """

    if enrollment.display_name:
        return enrollment.display_name
    generate = generator or coursework_hooks.display_name_generator
    enrollment.display_name = generate(enrollment)
    return enrollment.display_name


def ensure_enrollment(cohort, user, *, source="manual"):
    """Return the user's active enrollment, creating it when missing.

    Donor parity: enrollments created through coursework get a generated
    display name. The active-only uniqueness constraint means a previously
    unenrolled user simply gets a fresh active row (open question 7).
    """

    enrollment = (
        Enrollment.objects.filter(cohort=cohort, user=user, unenrolled_at__isnull=True)
        .order_by("id")
        .first()
    )
    if enrollment is not None:
        return enrollment, False
    enrollment = Enrollment(cohort=cohort, user=user, source=source)
    ensure_display_name(enrollment)
    enrollment.save()
    coursework_hooks.enrollment_preferences_updated(
        enrollment=enrollment,
        field="created",
        value=True,
    )
    return enrollment, True


def file_leaderboard_complaint(enrollment, reporter, *, issue_type, description):
    """Persist a leaderboard complaint the way the donor form view does."""

    complaint = LeaderboardComplaint(issue_type=issue_type, description=description)
    complaint.enrollment = enrollment
    complaint.reporter = reporter
    complaint.full_clean()
    complaint.save()
    return complaint
