import datetime

import pytest
from django.utils import timezone

from community_base.config import service
from community_base.coursework.automation import COURSEWORK_AUTOMATION_KEY
from community_base.coursework.models import (
    CriteriaResponse,
    PeerReview,
    PeerReviewBatch,
    PeerReviewState,
    ProjectEvaluationScore,
    ProjectSubmission,
    SubmissionReviewState,
)
from community_base.coursework.notifications import (
    POOL_READY_PURPOSE,
    REVIEW_RECEIVED_PURPOSE,
    REVIEW_WINDOW_EXPIRED_PURPOSE,
)
from community_base.coursework.pooling import (
    form_pooled_batches,
    form_pooled_batches_job,
    try_form_batch,
    try_score_batch,
)
from community_base.coursework.project_submission_flow import process_project_submission
from community_base.coursework.review import submit_peer_review
from community_base.jobs.registry import get_handler
from community_base.mail.models import EmailDelivery
from tests.coursework.project_form_support import learner, post_request, valid_data
from tests.coursework.test_peer_review import make_criteria
from tests.coursework.test_pooling import (
    pooled_cohort,
    pooled_project,
    submit_batch_of,
    waiting_submissions_without_batching,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def reset_runtime_config():
    service.runtime.reset()
    yield
    service.runtime.reset()


def disable_automation():
    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:pooling-guard")


def test_false_mode_blocks_all_formation_paths_and_can_resume():
    cohort = pooled_cohort(slug="guard-formation")
    project = pooled_project(cohort)
    waiting_submissions_without_batching(project, cohort, 6, prefix="guard-formation")
    disable_automation()

    assert try_form_batch(project) is None
    assert form_pooled_batches(project) == []
    assert form_pooled_batches_job(None, {}) == {"formed_batches": 0}
    assert get_handler("coursework.form_pooled_batches")(None, {}) == {"formed_batches": 0}
    assert PeerReviewBatch.objects.count() == 0
    assert PeerReview.objects.count() == 0
    assert (
        project.submissions.filter(
            review_state=SubmissionReviewState.AWAITING_ASSIGNMENT.value
        ).count()
        == 6
    )
    assert EmailDelivery.objects.filter(purpose=POOL_READY_PURPOSE).count() == 0

    service.set(COURSEWORK_AUTOMATION_KEY, True, "test:pooling-guard")
    assert form_pooled_batches_job(None, {}) == {"formed_batches": 2}
    assert PeerReviewBatch.objects.filter(project=project).count() == 2


def test_submission_flow_keeps_intentional_hook_while_formation_is_disabled(
    settings, django_capture_on_commit_callbacks
):
    submitted = []
    assigned = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_PROJECT_SUBMITTED": lambda **event: submitted.append(event),
        "COURSEWORK_PEER_REVIEWS_ASSIGNED": lambda **event: assigned.append(event),
    }
    cohort = pooled_cohort(slug="guard-submission")
    project = pooled_project(cohort)
    waiting_submissions_without_batching(project, cohort, 2, prefix="guard-submission")
    user, enrollment = learner(cohort, email="guard-submission-final@example.com")
    disable_automation()

    with django_capture_on_commit_callbacks(execute=True):
        outcome = process_project_submission(post_request(user, valid_data()), project, enrollment)

    assert outcome.action == "saved"
    assert ProjectSubmission.objects.filter(pk=outcome.submission.pk).exists()
    assert submitted == [{"submission": outcome.submission, "created": True}]
    assert assigned == []
    assert PeerReviewBatch.objects.count() == 0
    assert PeerReview.objects.count() == 0
    assert EmailDelivery.objects.filter(purpose=POOL_READY_PURPOSE).count() == 0


def test_false_mode_blocks_scoring_of_a_fully_resolved_batch(settings):
    leaderboard = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER": lambda **event: leaderboard.append(event),
    }
    cohort = pooled_cohort(slug="guard-score")
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submissions = submit_batch_of(project, cohort, 3, prefix="guard-score")
    batch = PeerReviewBatch.objects.get(project=project)
    reviews = list(PeerReview.objects.filter(batch=batch))
    for review in reviews[:-1]:
        submit_peer_review(review, {criteria.id: "2"})
    last = reviews[-1]
    CriteriaResponse.objects.create(review=last, criteria=criteria, answer="2")
    last.state = PeerReviewState.SUBMITTED.value
    last.submitted_at = timezone.now()
    last.save(update_fields=["state", "submitted_at"])
    disable_automation()

    assert try_score_batch(batch) is False
    batch.refresh_from_db()
    assert batch.scored_at is None
    assert ProjectEvaluationScore.objects.count() == 0
    assert leaderboard == []
    for submission in submissions:
        submission.refresh_from_db()
        assert submission.review_state == SubmissionReviewState.IN_REVIEW.value


def test_review_submission_survives_guard_without_triggering_scoring(settings):
    leaderboard = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER": lambda **event: leaderboard.append(event),
    }
    cohort = pooled_cohort(slug="guard-review")
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3, prefix="guard-review")
    batch = PeerReviewBatch.objects.get(project=project)
    reviews = list(PeerReview.objects.filter(batch=batch))
    for review in reviews[:-1]:
        submit_peer_review(review, {criteria.id: "2"})
    before = EmailDelivery.objects.filter(purpose=REVIEW_RECEIVED_PURPOSE).count()
    disable_automation()

    submitted = submit_peer_review(reviews[-1], {criteria.id: "2"})

    assert submitted.state == PeerReviewState.SUBMITTED.value
    assert EmailDelivery.objects.filter(purpose=REVIEW_RECEIVED_PURPOSE).count() == before + 1
    batch.refresh_from_db()
    assert batch.scored_at is None
    assert ProjectEvaluationScore.objects.count() == 0
    assert leaderboard == []


def test_false_mode_blocks_expiry_and_its_follow_on_effects(settings):
    leaderboard = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER": lambda **event: leaderboard.append(event),
    }
    cohort = pooled_cohort(slug="guard-expiry")
    project = pooled_project(cohort)
    submissions = submit_batch_of(project, cohort, 3, prefix="guard-expiry")
    batch = PeerReviewBatch.objects.get(project=project)
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() - datetime.timedelta(minutes=1)
    )
    disable_automation()
    result = get_handler("coursework.expire_pooled_reviews")(None, {})

    assert result == {"expired": 0, "scored_batches": 0}
    assert (
        not PeerReview.objects.filter(batch=batch)
        .exclude(state=PeerReviewState.TO_REVIEW.value)
        .exists()
    )
    assert EmailDelivery.objects.filter(purpose=REVIEW_WINDOW_EXPIRED_PURPOSE).count() == 0
    assert ProjectEvaluationScore.objects.count() == 0
    assert leaderboard == []
    batch.refresh_from_db()
    assert batch.scored_at is None
    for submission in submissions:
        submission.refresh_from_db()
        assert submission.review_state == SubmissionReviewState.IN_REVIEW.value
