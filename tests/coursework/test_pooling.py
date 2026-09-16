import datetime

import pytest
from django.utils import timezone

from community_base.coursework.leaderboard import completed_project_submissions_prefetch
from community_base.coursework.models import (
    PeerReview,
    PeerReviewBatch,
    PeerReviewState,
    ProjectState,
    ProjectStatistics,
    SubmissionReviewState,
)
from community_base.coursework.pooling import expire_pooled_reviews, try_score_batch
from community_base.coursework.projects import submit_project
from community_base.coursework.review import (
    review_accepts_submission,
    submit_peer_review,
)
from community_base.coursework.statistics import calculate_project_statistics
from community_base.mail.models import EmailDelivery
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_peer_review import make_criteria
from tests.coursework.test_projects import lip_links, make_project

# C5.2f wires batch formation through transaction.on_commit (submit_project); on_commit callbacks
# only fire with real transaction commit/rollback semantics, not pytest-django's default
# wrap-and-roll-back test transaction (community/test_services.py sets this same marker for the
# same reason).
pytestmark = pytest.mark.django_db(transaction=True)


def pooled_cohort(slug="pool", **values):
    return coursework_cohort(slug=slug, mode="self_paced", **values)


def pooled_project(cohort, **values):
    values.setdefault("number_of_peers_to_evaluate", 2)
    return make_project(cohort, **values)


def submit(project, cohort, email):
    _user, enrollment = enrollment_for(cohort, email=email)
    submission, _created = submit_project(
        project,
        enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
        learning_in_public_links=lip_links(2),
        faq_contribution_url="https://example.com/faq",
    )
    return submission


def submit_batch_of(project, cohort, count, prefix="pool-learner"):
    return [submit(project, cohort, f"{prefix}{index}@example.com") for index in range(count)]


def test_uses_pooled_review_derives_from_cohort_mode():
    dated = make_project(coursework_cohort(slug="dated"))
    assert dated.uses_pooled_review is False

    pooled = pooled_project(pooled_cohort())
    assert pooled.uses_pooled_review is True


def test_try_form_batch_waits_for_n_plus_one():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 2)  # n=2 to review, need 3 waiting

    assert PeerReviewBatch.objects.filter(project=project).count() == 0

    third = submit(project, cohort, "third@example.com")

    assert PeerReviewBatch.objects.filter(project=project).count() == 1
    third.refresh_from_db()
    assert third.review_state == SubmissionReviewState.IN_REVIEW.value
    # Project.state never moves for a pooled project; it stays the permanent "open" value.
    project.refresh_from_db()
    assert project.state == ProjectState.COLLECTING_SUBMISSIONS.value


def test_batch_is_a_full_round_robin_graph():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    submissions = submit_batch_of(project, cohort, 3)

    batch = PeerReviewBatch.objects.get(project=project)
    reviews = PeerReview.objects.filter(batch=batch)
    assert reviews.count() == 6  # 3 members x 2 reviews each

    ids = {submission.id for submission in submissions}
    for submission_id in ids:
        targets = set(
            reviews.filter(reviewer_id=submission_id).values_list(
                "submission_under_evaluation_id", flat=True
            )
        )
        assert targets == ids - {submission_id}
        incoming = set(
            reviews.filter(submission_under_evaluation_id=submission_id).values_list(
                "reviewer_id", flat=True
            )
        )
        assert incoming == ids - {submission_id}

    window = batch.due_at - batch.formed_at
    expected = datetime.timedelta(days=project.pooled_review_window_days)
    assert abs(window - expected) < datetime.timedelta(seconds=5)


def test_batch_scores_once_every_review_is_submitted_and_never_touches_project_state():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submissions = submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)

    reviews = list(PeerReview.objects.filter(batch=batch))
    for review in reviews[:-1]:
        submit_peer_review(review, {criteria.id: "2"})
    batch.refresh_from_db()
    assert batch.scored_at is None  # not fully resolved yet -- must not score early

    submit_peer_review(reviews[-1], {criteria.id: "2"})

    batch.refresh_from_db()
    assert batch.scored_at is not None
    project.refresh_from_db()
    # Never PEER_REVIEWING/COMPLETED for a pooled project.
    assert project.state == ProjectState.COLLECTING_SUBMISSIONS.value

    for submission in submissions:
        submission.refresh_from_db()
        assert submission.review_state == SubmissionReviewState.SCORED.value
        assert submission.reviewed_enough_peers is True
        assert submission.passed is True


def test_late_submission_rejected_once_batch_is_scored():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    reviews = list(PeerReview.objects.filter(batch=batch))
    for review in reviews:
        submit_peer_review(review, {criteria.id: "2"})

    batch.refresh_from_db()
    assert batch.scored_at is not None

    from community_base.coursework.review import ReviewWindowClosedError

    reviews[0].refresh_from_db()  # drop the stale cached batch fetched before scoring
    with pytest.raises(ReviewWindowClosedError):
        submit_peer_review(reviews[0], {criteria.id: "1"})


def test_try_score_batch_is_idempotent():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    for review in PeerReview.objects.filter(batch=batch):
        submit_peer_review(review, {criteria.id: "2"})

    batch.refresh_from_db()
    assert try_score_batch(batch) is False  # already scored by the happy path above


def test_try_score_batch_no_op_while_reviews_are_outstanding():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)

    assert try_score_batch(batch) is False
    batch.refresh_from_db()
    assert batch.scored_at is None


def test_try_form_batch_is_a_no_op_for_a_closed_pooled_project():
    cohort = pooled_cohort()
    project = pooled_project(cohort, state=ProjectState.CLOSED.value)
    submit_batch_of(project, cohort, 3)

    assert PeerReviewBatch.objects.filter(project=project).count() == 0


def test_review_accepts_submission_matches_batch_scored_state():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    reviews = list(PeerReview.objects.filter(batch=batch))

    assert review_accepts_submission(reviews[0], project) is True

    for review in reviews:
        submit_peer_review(review, {criteria.id: "2"})

    reviews[0].refresh_from_db()
    assert review_accepts_submission(reviews[0], project) is False


def test_volunteer_review_stays_open_regardless_of_batch_state():
    from community_base.accounts.models import User
    from community_base.coursework.review import add_volunteer_peer_review

    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submissions = submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    for review in PeerReview.objects.filter(batch=batch):
        submit_peer_review(review, {criteria.id: "2"})
    batch.refresh_from_db()
    assert batch.scored_at is not None

    volunteer = User.objects.create_user(email="volunteer@example.com")
    optional_review, _created = add_volunteer_peer_review(project, volunteer, submissions[0])

    assert optional_review.batch_id is None
    assert review_accepts_submission(optional_review, project) is True


def test_pooled_project_statistics_are_live_before_every_batch_is_scored():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)

    # Pooled mode never requires Project.state == COMPLETED (it never reaches it); calling this
    # before any batch has scored is valid and simply reflects nothing scored yet.
    stats = calculate_project_statistics(project)
    assert stats.total_submissions == 0

    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    for review in PeerReview.objects.filter(batch=batch):
        submit_peer_review(review, {criteria.id: "2"})

    stats = calculate_project_statistics(project, force=True)
    assert stats.total_submissions == 3

    # A second, still-waiting learner must not appear in the live statistic yet.
    submit(project, cohort, "waiting@example.com")
    stats = calculate_project_statistics(project, force=True)
    assert stats.total_submissions == 3
    assert ProjectStatistics.objects.filter(project=project).count() == 1


def test_pooled_scored_submissions_appear_in_the_leaderboard_prefetch():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    for review in PeerReview.objects.filter(batch=batch):
        submit_peer_review(review, {criteria.id: "2"})

    prefetch = completed_project_submissions_prefetch()
    scored_ids = set(prefetch.queryset.values_list("id", flat=True))
    batch_member_ids = set(
        PeerReview.objects.filter(batch=batch).values_list(
            "submission_under_evaluation_id", flat=True
        )
    )
    assert batch_member_ids <= scored_ids


# --- C5.2g: notifications and expiry -----------------------------------------------------


def test_batch_formation_notifies_assignment_and_pool_ready():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    submissions = submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)

    assigned = EmailDelivery.objects.filter(purpose="coursework.review_assigned")
    pool_ready = EmailDelivery.objects.filter(purpose="coursework.pool_ready")
    # One reviewer email per batch member (grouped), not one per PeerReview row (6 rows, 3
    # members) -- and one pool-ready email per member.
    assert assigned.count() == 3
    assert pool_ready.count() == 3
    member_emails = {submission.student.email for submission in submissions}
    assert set(assigned.values_list("recipient_email", flat=True)) == member_emails
    assert set(pool_ready.values_list("recipient_email", flat=True)) == member_emails
    for delivery in assigned:
        assert delivery.context_data["review_count"] == 2
        assert delivery.context_data["due_date"] is not None
    for delivery in pool_ready:
        assert delivery.context_data["due_date"] == batch.due_at.isoformat()


def test_review_submission_notifies_the_reviewee():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submissions = submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    review = PeerReview.objects.filter(batch=batch).first()

    submit_peer_review(review, {criteria.id: "2"})

    reviewee_email = review.submission_under_evaluation.student.email
    deliveries = EmailDelivery.objects.filter(
        purpose="coursework.review_received", recipient_email=reviewee_email
    )
    assert deliveries.count() == 1
    del submissions  # fixture-only; silences an unused-variable lint on the batch setup helper


def test_expire_pooled_reviews_releases_reviewee_and_notifies_reviewer():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    reviews = list(PeerReview.objects.filter(batch=batch))

    # Everyone submits their reviews except one -- the reviewee waiting on that one review
    # would otherwise stall indefinitely.
    late_review = reviews[0]
    for review in reviews[1:]:
        submit_peer_review(review, {criteria.id: "2"})

    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() - datetime.timedelta(minutes=1)
    )

    result = expire_pooled_reviews(None, {})

    assert result["expired"] == 1
    assert result["scored_batches"] == 1

    late_review.refresh_from_db()
    assert late_review.state == PeerReviewState.EXPIRED.value

    reviewer_email = late_review.reviewer.student.email
    expired_notices = EmailDelivery.objects.filter(
        purpose="coursework.review_window_expired", recipient_email=reviewer_email
    )
    assert expired_notices.count() == 1

    batch.refresh_from_db()
    assert batch.scored_at is not None
    late_review.submission_under_evaluation.refresh_from_db()
    scored = SubmissionReviewState.SCORED.value
    assert late_review.submission_under_evaluation.review_state == scored


def test_expire_pooled_reviews_is_idempotent():
    cohort = pooled_cohort()
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() - datetime.timedelta(minutes=1)
    )

    first = expire_pooled_reviews(None, {})
    assert first["expired"] == 6  # nobody submitted; every review in the batch expires

    second = expire_pooled_reviews(None, {})
    assert second["expired"] == 0
    assert second["scored_batches"] == 0  # already scored by the first run

    expired_notices = EmailDelivery.objects.filter(purpose="coursework.review_window_expired")
    assert expired_notices.count() == 6  # not doubled by the second run


def test_expire_pooled_reviews_ignores_deadline_mode_reviews():
    """Guard: deadline-mode reviews have no batch and must never be swept here."""
    from community_base.coursework.review import assign_peer_reviews_for_project
    from tests.coursework.test_peer_review import close_review_window
    from tests.coursework.test_projects import make_project as make_dated_project

    dated_cohort = coursework_cohort(slug="dated-expiry")
    project = make_dated_project(
        dated_cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    submit_batch_of(project, dated_cohort, 3)
    assign_peer_reviews_for_project(project)
    close_review_window(project)

    result = expire_pooled_reviews(None, {})

    assert result["expired"] == 0
    assert PeerReview.objects.filter(state=PeerReviewState.EXPIRED.value).count() == 0


def test_expire_pooled_reviews_handler_and_schedule_are_registered():
    from community_base.jobs.registry import registered_handler_names, registered_schedules

    names = registered_handler_names()
    schedules = {item.handler: item.cron for item in registered_schedules()}
    assert "coursework.expire_pooled_reviews" in names
    assert schedules["coursework.expire_pooled_reviews"] == "*/15 * * * *"
