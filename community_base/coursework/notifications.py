"""Event-driven peer-review mail: assignment, pool-ready, review-received, window-expired.

Distinct from ``reminders.py``, which scans for items approaching a deadline on a schedule.
These fire once, at the moment of the event, from the code that causes it (assignment,
submission, expiry) -- reused as plain function calls, not durable job handlers. Each wraps its
own ``mail.send()`` call in ``transaction.atomic()`` so it is safe to call from any context
(``mail.send`` requires an active transaction); nested inside an already-open transaction this is
just a savepoint.

Every purpose uses ``mail.send``'s own idempotency key, the same durable-outbox mechanism
``reminders.py`` already relies on -- no parallel send mechanism.
"""

from collections import defaultdict

from django.db import transaction

from community_base.coursework.models import PeerReview, PeerReviewBatch, ProjectSubmission
from community_base.mail import send

REVIEW_ASSIGNED_PURPOSE = "coursework.review_assigned"
POOL_READY_PURPOSE = "coursework.pool_ready"
REVIEW_RECEIVED_PURPOSE = "coursework.review_received"
REVIEW_WINDOW_EXPIRED_PURPOSE = "coursework.review_window_expired"


def _project_context(project) -> dict:
    return {
        "course_slug": project.cohort.course.slug,
        "cohort_slug": project.cohort.slug,
        "project_slug": project.slug,
        "project_title": project.title,
    }


def _review_due_at(review: PeerReview):
    if review.batch_id is not None:
        return review.batch.due_at
    return review.submission_under_evaluation.project.peer_review_due_date


def send_review_assigned_notifications(reviews: list[PeerReview]) -> int:
    """One email per reviewer per assignment event, not one per review row.

    ``reviews`` is the full list a single event created (a deadline-mode
    ``assign_peer_reviews_for_project`` call, or one pooled batch) -- grouping here means a
    learner assigned several reviews at once gets one email listing the count, not a burst.
    """

    by_reviewer: dict[int, list[PeerReview]] = defaultdict(list)
    for review in reviews:
        by_reviewer[review.reviewer_id].append(review)

    sent = 0
    for reviewer_id, reviewer_reviews in by_reviewer.items():
        first = reviewer_reviews[0]
        reviewer_submission = first.reviewer
        project = first.submission_under_evaluation.project
        due_at = _review_due_at(first)
        # Deterministic across the group regardless of dict ordering: sorted by id.
        sorted_ids = sorted(review.id for review in reviewer_reviews)
        group_key = "-".join(str(review_id) for review_id in sorted_ids)
        with transaction.atomic():
            send(
                REVIEW_ASSIGNED_PURPOSE,
                reviewer_submission.student.email,
                {
                    **_project_context(project),
                    "review_count": len(reviewer_reviews),
                    "due_date": due_at.isoformat() if due_at else None,
                },
                f"{REVIEW_ASSIGNED_PURPOSE}:{reviewer_id}:{group_key}",
                category="coursework",
                user=reviewer_submission.student,
            )
        sent += 1
    return sent


def send_pool_ready_notification(batch: PeerReviewBatch, submission: ProjectSubmission) -> None:
    project = batch.project
    with transaction.atomic():
        send(
            POOL_READY_PURPOSE,
            submission.student.email,
            {
                **_project_context(project),
                "due_date": batch.due_at.isoformat(),
            },
            f"{POOL_READY_PURPOSE}:{submission.id}:{batch.id}",
            category="coursework",
            user=submission.student,
        )


def send_review_received_notification(review: PeerReview) -> None:
    submission = review.submission_under_evaluation
    project = submission.project
    with transaction.atomic():
        send(
            REVIEW_RECEIVED_PURPOSE,
            submission.student.email,
            {
                **_project_context(project),
            },
            f"{REVIEW_RECEIVED_PURPOSE}:{review.id}",
            category="coursework",
            user=submission.student,
        )


def send_review_expired_notification(review: PeerReview) -> None:
    reviewer_submission = review.reviewer
    project = reviewer_submission.project
    with transaction.atomic():
        send(
            REVIEW_WINDOW_EXPIRED_PURPOSE,
            reviewer_submission.student.email,
            {
                **_project_context(project),
            },
            f"{REVIEW_WINDOW_EXPIRED_PURPOSE}:{review.id}",
            category="coursework",
            user=reviewer_submission.student,
        )
