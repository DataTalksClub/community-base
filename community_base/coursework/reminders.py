"""Deadline reminders for coursework, delivered through the mail app.

The donor's Datamailer-shaped reminder pipeline is deliberately not ported:
Relay owns sending (decision D4), so the package registers job handlers that
query due items and create mail deliveries with stable idempotency keys.
"""

from django.utils import timezone

from community_base.coursework.models import (
    Homework,
    HomeworkState,
    PeerReview,
    PeerReviewState,
    Project,
    ProjectState,
    ProjectSubmission,
    Submission,
)
from community_base.jobs.registry import JobContext, JobPayload, register_handler
from community_base.mail import send

HOMEWORK_DEADLINE_PURPOSE = "coursework.homework_deadline"
PROJECT_SUBMISSION_DEADLINE_PURPOSE = "coursework.project_submission_deadline"
PEER_REVIEW_DEADLINE_PURPOSE = "coursework.peer_review_deadline"

DEFAULT_WINDOW_DAYS = 3


def _window(payload):
    days = payload.get("window_days", DEFAULT_WINDOW_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise ValueError("window_days must be an integer between 1 and 30")
    now = timezone.now()
    return now, now + timezone.timedelta(days=days)


def homeworks_due_between(now, horizon):
    return (
        Homework.objects.filter(state=HomeworkState.OPEN.value, due_date__gt=now)
        .filter(due_date__lte=horizon)
        .select_related("cohort__course")
    )


def projects_collecting_between(now, horizon):
    return Project.objects.filter(
        state=ProjectState.COLLECTING_SUBMISSIONS.value,
        submission_due_date__gt=now,
        submission_due_date__lte=horizon,
    ).select_related("cohort__course")


def projects_peer_reviewing_between(now, horizon):
    return Project.objects.filter(
        state=ProjectState.PEER_REVIEWING.value,
        peer_review_due_date__gt=now,
        peer_review_due_date__lte=horizon,
    ).select_related("cohort__course")


def _active_enrollments_without(cohort, submitted_enrollment_ids):
    return (
        cohort.enrollments.filter(unenrolled_at__isnull=True)
        .exclude(id__in=submitted_enrollment_ids)
        .select_related("user")
    )


@register_handler("coursework.send_homework_deadline_reminders")
def send_homework_deadline_reminders(context: JobContext, payload: JobPayload):
    del context
    now, horizon = _window(payload)
    sent = 0
    for homework in homeworks_due_between(now, horizon):
        submitted = Submission.objects.filter(homework=homework).values_list(
            "enrollment_id", flat=True
        )
        for enrollment in _active_enrollments_without(homework.cohort, submitted):
            send(
                HOMEWORK_DEADLINE_PURPOSE,
                enrollment.user.email,
                {
                    "course_slug": homework.cohort.course.slug,
                    "cohort_slug": homework.cohort.slug,
                    "homework_slug": homework.slug,
                    "homework_title": homework.title,
                    "due_date": homework.due_date.isoformat(),
                },
                f"coursework.homework_deadline:{homework.pk}:{enrollment.pk}:"
                f"{homework.due_date.date().isoformat()}",
                category="coursework",
                user=enrollment.user,
            )
            sent += 1
    return {"reminders": sent}


@register_handler("coursework.send_project_submission_deadline_reminders")
def send_project_submission_deadline_reminders(context: JobContext, payload: JobPayload):
    del context
    now, horizon = _window(payload)
    sent = 0
    for project in projects_collecting_between(now, horizon):
        submitted = ProjectSubmission.objects.filter(project=project).values_list(
            "enrollment_id", flat=True
        )
        for enrollment in _active_enrollments_without(project.cohort, submitted):
            send(
                PROJECT_SUBMISSION_DEADLINE_PURPOSE,
                enrollment.user.email,
                {
                    "course_slug": project.cohort.course.slug,
                    "cohort_slug": project.cohort.slug,
                    "project_slug": project.slug,
                    "project_title": project.title,
                    "due_date": project.submission_due_date.isoformat(),
                },
                f"coursework.project_deadline:{project.pk}:{enrollment.pk}:"
                f"{project.submission_due_date.date().isoformat()}",
                category="coursework",
                user=enrollment.user,
            )
            sent += 1
    return {"reminders": sent}


@register_handler("coursework.send_peer_review_deadline_reminders")
def send_peer_review_deadline_reminders(context: JobContext, payload: JobPayload):
    del context
    now, horizon = _window(payload)
    sent = 0
    for project in projects_peer_reviewing_between(now, horizon):
        pending_reviews = PeerReview.objects.filter(
            submission_under_evaluation__project=project,
            state=PeerReviewState.TO_REVIEW.value,
        ).select_related("reviewer__student")
        for review in pending_reviews:
            student = review.reviewer.student
            send(
                PEER_REVIEW_DEADLINE_PURPOSE,
                student.email,
                {
                    "course_slug": project.cohort.course.slug,
                    "cohort_slug": project.cohort.slug,
                    "project_slug": project.slug,
                    "project_title": project.title,
                    "due_date": project.peer_review_due_date.isoformat(),
                },
                f"coursework.peer_review_deadline:{review.pk}:"
                f"{project.peer_review_due_date.date().isoformat()}",
                category="coursework",
                user=student,
            )
            sent += 1
    return {"reminders": sent}
