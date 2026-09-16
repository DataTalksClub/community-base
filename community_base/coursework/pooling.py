"""Pooled (self-paced) peer review: batch formation, batch-scoped scoring, expiry.

Deadline mode assigns and scores a whole project at once, on an operator's action
(``review.assign_peer_reviews_for_project`` / ``review.score_project``). A self-paced project has
no such moment: submissions arrive continuously, so this module assigns and scores one
``PeerReviewBatch`` at a time instead, formed as soon as enough submissions are waiting
(``Project.number_of_peers_to_evaluate + 1``).

See ``models.PeerReviewBatch`` for why the batch, not the individual submission, is the scoring
unit -- that reasoning is the one thing in this module that must not be "simplified" away.
"""

from django.db import transaction
from django.utils import timezone

from community_base.coursework import notifications
from community_base.coursework.hooks import hooks
from community_base.coursework.models import (
    PeerReview,
    PeerReviewBatch,
    PeerReviewState,
    Project,
    ProjectState,
    ProjectSubmission,
    SubmissionReviewState,
)
from community_base.coursework.review import (
    calculate_project_scoring,
    persist_scored_submissions,
    select_random_assignment,
)
from community_base.jobs.registry import JobContext, JobPayload, register_handler, schedule


def _batch_seed(project, batch) -> int:
    # Deterministic and distinct per batch: reusing review.ASSIGNMENT_SEED (a single global
    # constant) for every batch of a pooled project would repeat the same relative pairing
    # pattern every time, since select_random_assignment reseeds from scratch per call.
    return (project.id * 1_000_000) + batch.id


def _waiting_submissions(project, limit: int):
    return list(
        ProjectSubmission.objects.filter(
            project=project,
            volunteer_review_only=False,
            review_state=SubmissionReviewState.AWAITING_ASSIGNMENT.value,
        )
        .select_related("enrollment")
        .order_by("submitted_at", "id")[:limit]
    )


def try_form_batch(project) -> PeerReviewBatch | None:
    """Form and assign one pooled review batch if enough submissions are waiting.

    A no-op (returns ``None``) for a non-pooled project, a closed pooled project, or a pooled
    project without ``number_of_peers_to_evaluate + 1`` submissions yet waiting. Locks the
    project row for the duration so two learners submitting at the same moment cannot both form a
    batch from the same waiting submissions.
    """

    if not project.uses_pooled_review:
        return None

    batch_size = project.number_of_peers_to_evaluate + 1

    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=project.pk)
        if project.state == ProjectState.CLOSED.value:
            return None

        waiting = _waiting_submissions(project, batch_size)
        if len(waiting) < batch_size:
            return None

        batch = PeerReviewBatch.objects.create(
            project=project,
            due_at=timezone.now() + timezone.timedelta(days=project.pooled_review_window_days),
        )
        assignments = select_random_assignment(
            waiting, project.number_of_peers_to_evaluate, seed=_batch_seed(project, batch)
        )
        for assignment in assignments:
            assignment.batch = batch
        PeerReview.objects.bulk_create(assignments)

        waiting_ids = [submission.id for submission in waiting]
        ProjectSubmission.objects.filter(id__in=waiting_ids).update(
            review_state=SubmissionReviewState.IN_REVIEW.value
        )

    hooks.peer_reviews_assigned(project=project, review_count=len(assignments))
    notifications.send_review_assigned_notifications(assignments)
    for submission in waiting:
        notifications.send_pool_ready_notification(batch, submission)
    return batch


def _batch_member_ids(batch) -> set[int]:
    reviewee_ids = batch.reviews.values_list("submission_under_evaluation_id", flat=True)
    reviewer_ids = batch.reviews.values_list("reviewer_id", flat=True)
    return set(reviewee_ids) | set(reviewer_ids)


def _batch_fully_resolved(batch) -> bool:
    return not batch.reviews.filter(state=PeerReviewState.TO_REVIEW.value).exists()


def try_score_batch(batch: PeerReviewBatch) -> bool:
    """Score every submission in a pooled batch once every review in it is resolved.

    THE BATCH IS THE SCORING UNIT (``PeerReviewBatch``'s docstring). Idempotent and safe to call
    speculatively: returns ``False`` with no writes if the batch is already scored or is not yet
    fully resolved (every review ``SUBMITTED`` or ``EXPIRED``). Called from the happy path
    (``review.submit_peer_review``, every review lands before ``due_at``) and from the expiry
    sweep (``coursework.pooling.expire_pooled_reviews``, C5.2g) -- whichever observes "fully
    resolved" first scores it; the row lock below and the ``scored_at`` check serialize the race
    between them.
    """

    with transaction.atomic():
        batch = PeerReviewBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.scored_at is not None:
            return False
        if not _batch_fully_resolved(batch):
            return False

        batch_reviews = batch.reviews.select_related(
            "submission_under_evaluation",
            "submission_under_evaluation__enrollment",
            "reviewer",
        )
        calculation = calculate_project_scoring(batch.project, batch_reviews)
        persist_scored_submissions(calculation)

        member_ids = _batch_member_ids(batch)
        ProjectSubmission.objects.filter(id__in=member_ids).update(
            review_state=SubmissionReviewState.SCORED.value
        )

        batch.scored_at = timezone.now()
        batch.save(update_fields=["scored_at"])

    hooks.project_leaderboard_updater(project=batch.project)
    return True


def _expired_pooled_reviews():
    return PeerReview.objects.filter(
        state=PeerReviewState.TO_REVIEW.value,
        batch__isnull=False,
        batch__scored_at__isnull=True,
        batch__due_at__lt=timezone.now(),
    ).select_related("batch", "reviewer", "reviewer__student")


@register_handler("coursework.expire_pooled_reviews")
def expire_pooled_reviews(context: JobContext, payload: JobPayload):
    """Release both parties of a pooled review whose window has closed.

    Reviewer: their ``PeerReview`` moves ``TO_REVIEW`` -> ``EXPIRED`` (excluded from the
    reviewee's score from that point on) and they are told the window closed. Reviewee: never
    handled here directly -- ``try_score_batch`` scores their batch the moment every review in it
    is resolved, submitted or expired, which this function's state change is what makes true. No
    reassignment: see ``models.PeerReviewBatch`` and the C5.2g plan entry for why.
    """

    del context, payload
    expired = 0
    scored_batches = 0
    batch_ids: set[int] = set()

    for review in _expired_pooled_reviews():
        with transaction.atomic():
            updated = PeerReview.objects.filter(
                pk=review.pk, state=PeerReviewState.TO_REVIEW.value
            ).update(state=PeerReviewState.EXPIRED.value)
        if not updated:
            continue  # submitted or already expired by a concurrent run since the query above
        expired += 1
        batch_ids.add(review.batch_id)
        notifications.send_review_expired_notification(review)

    for batch in PeerReviewBatch.objects.filter(id__in=batch_ids):
        if try_score_batch(batch):
            scored_batches += 1

    return {"expired": expired, "scored_batches": scored_batches}


schedule(
    "coursework.expire_pooled_reviews",
    "*/15 * * * *",
    {},
    name="coursework.expire_pooled_reviews.every_15_minutes",
)
