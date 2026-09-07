"""Leaderboard rollup: enrollment totals, ranking and cache invalidation.

Ported from the DTC donor ``courses/leaderboard.py``. The donor parameter is
named ``course`` but receives a ``Cohort`` row (the donor ``Enrollment.course``
field points at the cohort model); the package names the parameter ``cohort``
explicitly.

Package adaptation (recorded for donor-data verification in A5.1): the rollup
ranks only active enrollments (``unenrolled_at__isnull=True``). Soft-deleted
enrollments keep their last computed ``total_score`` and
``position_on_leaderboard`` and are excluded from every later recompute.
"""

import logging
from time import time

from django.core.cache import cache
from django.db.models import Sum

from community_base.coursework.models import ProjectSubmission, Submission
from community_base.curriculum.models import Enrollment

logger = logging.getLogger(__name__)


def _scores_by_enrollment(submissions):
    total_score_annotation = Sum("total_score")
    aggregated_scores = submissions.values("enrollment").annotate(
        total_score=total_score_annotation
    )
    scores_by_enrollment = {}
    for score in aggregated_scores:
        enrollment_id = score["enrollment"]
        scores_by_enrollment[enrollment_id] = score["total_score"]
    return scores_by_enrollment


def _enrollment_leaderboard_sort_key(enrollment):
    total_score = enrollment.total_score or 0
    return -total_score, enrollment.id


def _rank_enrollments(enrollments):
    enrollments = sorted(
        enrollments,
        key=_enrollment_leaderboard_sort_key,
    )
    for rank, enrollment in enumerate(enrollments, 1):
        enrollment.position_on_leaderboard = rank
    return enrollments


def _update_enrollment_totals(cohort):
    homework_submissions = Submission.objects.filter(homework__cohort=cohort)
    homework_scores = _scores_by_enrollment(homework_submissions)
    project_submissions = ProjectSubmission.objects.filter(
        project__cohort=cohort,
        volunteer_review_only=False,
    )
    project_scores = _scores_by_enrollment(project_submissions)
    enrollment_queryset = Enrollment.objects.filter(
        cohort=cohort,
        unenrolled_at__isnull=True,
    )
    enrollments = list(enrollment_queryset)

    for enrollment in enrollments:
        enrollment.total_score = homework_scores.get(enrollment.id, 0) + project_scores.get(
            enrollment.id, 0
        )

    enrollments = _rank_enrollments(enrollments)

    Enrollment.objects.bulk_update(
        enrollments,
        ["total_score", "position_on_leaderboard"],
    )


def _invalidate_leaderboard_caches(cohort):
    cache.delete(f"leaderboard:{cohort.id}")
    cache.delete(f"leaderboard_data:{cohort.id}")
    cache.delete(f"leaderboard_yaml:{cohort.id}")
    version_key = f"leaderboard_cache_version:{cohort.id}"
    cache.set(version_key, cache.get(version_key, 1) + 1, None)
    logger.info(f"Invalidated cache for leaderboard of cohort {cohort.id}")


def update_leaderboard(cohort):
    started_at = time()
    logger.info(f"Updating leaderboard for cohort {cohort.id}")
    _update_enrollment_totals(cohort)
    _invalidate_leaderboard_caches(cohort)
    duration = time() - started_at
    logger.info(f"Updated leaderboard in {duration:.2f} seconds")
