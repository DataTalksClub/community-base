"""Wrapped statistics calculation and read surfaces.

Ported from the donor ``courses/wrapped_statistics/`` package (activity,
metrics, persistence, calculator). The donor's ``course`` argument is the
package ``Cohort`` and donor ``Enrollment.student`` is ``Enrollment.user``;
the donor ``cohort_year`` JSON key becomes ``cohort_slug`` because the shared
``Cohort`` carries no year field. Statistics are pre-calculated per year so
the Wrapped pages never run the aggregation live.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from operator import itemgetter

from django.db.models import Count, Q, Sum
from django.utils import timezone

from community_base.coursework.models import (
    Enrollment,
    PeerReview,
    ProjectSubmission,
    Submission,
    UserWrappedStatistics,
    WrappedStatistics,
)

logger = logging.getLogger(__name__)

LEADERBOARD_SIZE = 100
HOURS_CAP = 100.0


def wrapped_year_window(year):
    year_start = timezone.make_aware(datetime(year, 1, 1))
    year_end = timezone.make_aware(datetime(year + 1, 1, 1) - timedelta(seconds=1))
    return year_start, year_end


def wrapped_activity_querysets(year_start, year_end):
    homework_submissions = Submission.objects.filter(
        submitted_at__gte=year_start,
        submitted_at__lte=year_end,
    ).select_related("homework__cohort__course", "enrollment", "student")
    project_submissions = ProjectSubmission.objects.filter(
        submitted_at__gte=year_start,
        submitted_at__lte=year_end,
    ).select_related("project__cohort__course", "enrollment", "student")
    return homework_submissions, project_submissions


def wrapped_enrollments(homework_submissions, project_submissions):
    enrollment_ids = {
        submission.enrollment_id
        for submission in (*homework_submissions, *project_submissions)
        if submission.enrollment_id
    }
    return Enrollment.objects.filter(id__in=enrollment_ids).select_related(
        "cohort__course",
        "user",
    )


def wrapped_students_with_activity(homework_submissions, project_submissions):
    return {submission.student for submission in (*homework_submissions, *project_submissions)}


@dataclass(frozen=True)
class WrappedActivity:
    year_start: datetime
    year_end: datetime
    homework_submissions: list
    project_submissions: list
    students_with_activity: set
    enrollments: object


def wrapped_activity_context(year):
    year_start, year_end = wrapped_year_window(year)
    homework_submissions, project_submissions = wrapped_activity_querysets(year_start, year_end)
    homework_list = list(homework_submissions)
    project_list = list(project_submissions)
    return WrappedActivity(
        year_start=year_start,
        year_end=year_end,
        homework_submissions=homework_list,
        project_submissions=project_list,
        students_with_activity=wrapped_students_with_activity(homework_list, project_list),
        enrollments=wrapped_enrollments(homework_list, project_list),
    )


def wrapped_peer_review_counts(students_with_activity, year_start, year_end):
    peer_reviews = (
        PeerReview.objects.filter(
            reviewer__student__in=students_with_activity,
            submitted_at__gte=year_start,
            submitted_at__lte=year_end,
        )
        .values("reviewer__student")
        .annotate(count=Count("id"))
    )
    return {row["reviewer__student"]: row["count"] for row in peer_reviews}


def wrapped_course_stats(enrollments):
    """Per-cohort enrollment counts, most popular first."""
    cohorts = {enrollment.cohort for enrollment in enrollments}
    course_stats_list = []
    for cohort in cohorts:
        course_stats_list.append(
            {
                "title": cohort.course.title,
                "slug": cohort.slug,
                "course_slug": cohort.course.slug,
                "cohort_slug": cohort.slug,
                "enrollment_count": enrollments.filter(cohort=cohort).count(),
            }
        )
    course_stats_list.sort(key=itemgetter("enrollment_count"), reverse=True)
    return course_stats_list


def wrapped_leaderboard_scores(enrollments):
    """Each student's score summed across cohorts, keyed by user id."""
    scores_by_user = {}
    for enrollment in enrollments:
        entry = scores_by_user.get(enrollment.user_id)
        if entry is None:
            entry = {
                "student_id": enrollment.user_id,
                "display_name": enrollment.display_name,
                "total_score": 0,
            }
            scores_by_user[enrollment.user_id] = entry
        entry["total_score"] += enrollment.total_score or 0
    return scores_by_user


def wrapped_leaderboard(enrollments):
    """Top-100 leaderboard entries, best score first."""
    top_scores = sorted(
        wrapped_leaderboard_scores(enrollments).values(),
        key=itemgetter("total_score"),
        reverse=True,
    )[:LEADERBOARD_SIZE]
    return [
        {
            "rank": rank,
            "display_name": entry["display_name"],
            "total_score": entry["total_score"],
            "student_id": entry["student_id"],
        }
        for rank, entry in enumerate(top_scores, start=1)
    ]


def capped_hours(value):
    return min(value or 0, HOURS_CAP)


def wrapped_homework_hours(submission):
    return capped_hours(submission.time_spent_lectures) + capped_hours(
        submission.time_spent_homework
    )


def wrapped_total_hours(homework_submissions, project_submissions):
    homework_hours = sum(wrapped_homework_hours(submission) for submission in homework_submissions)
    project_hours = sum(capped_hours(submission.time_spent) for submission in project_submissions)
    return round(homework_hours + project_hours, 1)


def wrapped_learning_in_public_count(homework_submissions, project_submissions):
    homework_links = sum(
        len(submission.learning_in_public_links or []) for submission in homework_submissions
    )
    project_links = sum(
        len(submission.learning_in_public_links or []) for submission in project_submissions
    )
    return homework_links + project_links


def has_faq_contribution(submission):
    return bool((submission.faq_contribution_url or "").strip())


def wrapped_faq_count(homework_submissions, project_submissions):
    return sum(
        1
        for submission in (*homework_submissions, *project_submissions)
        if has_faq_contribution(submission)
    )


def wrapped_courses(enrollments):
    return [
        {
            "title": enrollment.cohort.course.title,
            "score": enrollment.total_score,
            "slug": enrollment.cohort.slug,
            "course_slug": enrollment.cohort.course.slug,
            "cohort_slug": enrollment.cohort.slug,
            "enrollment_id": enrollment.id,
        }
        for enrollment in enrollments
    ]


def wrapped_certificates_count(enrollments):
    return sum(1 for enrollment in enrollments if (enrollment.certificate_url or "").strip())


def wrapped_total_points(enrollments):
    return sum(enrollment.total_score or 0 for enrollment in enrollments)


def wrapped_rank(student_id, leaderboard_data):
    for entry in leaderboard_data:
        if entry["student_id"] == student_id:
            return entry["rank"]
    return None


def wrapped_display_name(enrollments):
    """The pseudonym from an enrollment, or blank for enrollment-less students.

    Display names are generated pseudonyms, safe to persist and render; the
    account identifier is the email address and never reaches Wrapped copy.
    """
    return enrollments[0].display_name if enrollments else ""


def persist_wrapped_platform_statistics(stats, activity):
    stats.total_participants = len(activity.students_with_activity)
    stats.total_enrollments = activity.enrollments.count()
    stats.total_hours = wrapped_total_hours(
        activity.homework_submissions,
        activity.project_submissions,
    )
    no_certificate_url = Q(certificate_url__isnull=True) | Q(certificate_url="")
    stats.total_certificates = activity.enrollments.exclude(no_certificate_url).count()
    stats.total_points = (
        activity.enrollments.aggregate(total_score=Sum("total_score"))["total_score"] or 0
    )
    stats.course_stats = wrapped_course_stats(activity.enrollments)
    leaderboard_data = wrapped_leaderboard(activity.enrollments)
    stats.leaderboard = leaderboard_data
    stats.save()
    return leaderboard_data


def build_user_wrapped_stat(
    student,
    homework_submissions,
    project_submissions,
    enrollments,
    peer_reviews_count,
    leaderboard_data,
):
    return UserWrappedStatistics(
        user=student,
        total_points=wrapped_total_points(enrollments),
        total_hours=wrapped_total_hours(homework_submissions, project_submissions),
        homework_count=len(homework_submissions),
        project_count=len(project_submissions),
        peer_reviews_given=peer_reviews_count,
        learning_in_public_count=wrapped_learning_in_public_count(
            homework_submissions, project_submissions
        ),
        faq_contributions_count=wrapped_faq_count(homework_submissions, project_submissions),
        certificates_earned=wrapped_certificates_count(enrollments),
        courses=wrapped_courses(enrollments),
        rank=wrapped_rank(student.id, leaderboard_data),
        display_name=wrapped_display_name(enrollments),
    )


def build_user_wrapped_stats(activity, peer_review_counts, leaderboard_data):
    homework_by_student = defaultdict(list)
    for submission in activity.homework_submissions:
        homework_by_student[submission.student].append(submission)
    project_by_student = defaultdict(list)
    for submission in activity.project_submissions:
        project_by_student[submission.student].append(submission)
    enrollments_by_student = defaultdict(list)
    for enrollment in activity.enrollments:
        enrollments_by_student[enrollment.user].append(enrollment)

    return [
        build_user_wrapped_stat(
            student=student,
            homework_submissions=homework_by_student.get(student, []),
            project_submissions=project_by_student.get(student, []),
            enrollments=enrollments_by_student.get(student, []),
            peer_reviews_count=peer_review_counts.get(student.id, 0),
            leaderboard_data=leaderboard_data,
        )
        for student in activity.students_with_activity
    ]


def replace_user_wrapped_statistics(stats, user_stats_objects):
    for user_stat in user_stats_objects:
        user_stat.wrapped = stats
    UserWrappedStatistics.objects.filter(wrapped=stats).delete()
    UserWrappedStatistics.objects.bulk_create(user_stats_objects, batch_size=500)


def calculate_wrapped_statistics(year=2025, force=False):
    """Calculate and persist platform and per-user Wrapped rows for ``year``.

    Re-running without ``force`` is a no-op returning the existing row.
    """
    stats, created = WrappedStatistics.objects.get_or_create(year=year)
    if not force and not created:
        logger.info("Wrapped statistics for %s already exist.", year)
        return stats

    activity = wrapped_activity_context(year)
    leaderboard_data = persist_wrapped_platform_statistics(stats, activity)
    peer_review_counts = wrapped_peer_review_counts(
        activity.students_with_activity, activity.year_start, activity.year_end
    )
    user_stats_objects = build_user_wrapped_stats(activity, peer_review_counts, leaderboard_data)
    replace_user_wrapped_statistics(stats, user_stats_objects)
    logger.info(
        "Wrapped statistics for %s calculated; processed %s users.",
        year,
        len(user_stats_objects),
    )
    return stats


def visible_wrapped():
    return WrappedStatistics.objects.filter(is_visible=True).order_by("-year")


def get_user_wrapped(wrapped, user):
    return UserWrappedStatistics.objects.filter(wrapped=wrapped, user=user).first()


@dataclass(frozen=True)
class WrappedReadModel:
    stats: WrappedStatistics
    user_stats: object = None
    leaderboard: list = field(default_factory=list)


def wrapped_read_model(wrapped, user=None):
    """Read model for the Wrapped pages: stats, optional user row, leaderboard."""
    user_stats = get_user_wrapped(wrapped, user) if user is not None else None
    return WrappedReadModel(
        stats=wrapped,
        user_stats=user_stats,
        leaderboard=wrapped.leaderboard,
    )
