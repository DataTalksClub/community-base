import datetime

import pytest
from django.db import transaction
from django.utils import timezone

from community_base.coursework.models import (
    PeerReview,
    PeerReviewBatch,
    ProjectState,
)
from community_base.coursework.reminders import (
    PEER_REVIEW_DEADLINE_PURPOSE,
    send_peer_review_deadline_reminders,
)
from community_base.coursework.review import assign_peer_reviews_for_project, submit_peer_review
from community_base.mail.models import EmailDelivery
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_peer_review import make_criteria, make_submissions
from tests.coursework.test_pooling import pooled_cohort, pooled_project, submit_batch_of
from tests.coursework.test_projects import make_project

# Pooled fixtures dispatch batch formation through transaction.on_commit (see test_pooling.py),
# so this file needs a real transaction, not pytest-django's default wrap-and-roll-back one --
# which also means every direct handler call below must open its own atomic block, exactly as
# the ingress runner does in production (community_base/jobs/ingress.py): mail.send() requires
# one active.
pytestmark = pytest.mark.django_db(transaction=True)


def call_reminder_handler(payload=None):
    with transaction.atomic():
        return send_peer_review_deadline_reminders(None, payload or {})


def test_deadline_mode_peer_review_reminder_is_unaffected_by_the_pooled_addition():
    cohort = coursework_cohort(slug="reminder-deadline")
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_criteria(project)
    make_submissions(project, cohort, 3)
    assign_peer_reviews_for_project(project)
    # Every review starts TO_REVIEW; assignment opens a 7-day window (PEER_REVIEW_WINDOW), so an
    # 8-day reminder window is needed to catch it -- unchanged expression, unchanged query.
    project.refresh_from_db()
    assert project.peer_review_due_date <= timezone.now() + datetime.timedelta(days=8)

    result = call_reminder_handler({"window_days": 8})

    assert result["reminders"] == 6  # 3 submissions x 2 reviews each
    assert EmailDelivery.objects.filter(purpose=PEER_REVIEW_DEADLINE_PURPOSE).count() == 6


def test_pooled_review_reminder_fires_inside_the_window_and_is_idempotent():
    cohort = pooled_cohort(slug="reminder-pool")
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    # Put the batch's due date inside the default 3-day reminder window but not yet expired.
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() + datetime.timedelta(days=1)
    )

    result = call_reminder_handler()

    assert result["reminders"] == 6  # 3 members x 2 reviews each, full round robin
    deliveries = EmailDelivery.objects.filter(purpose=PEER_REVIEW_DEADLINE_PURPOSE)
    assert deliveries.count() == 6

    # Idempotent: the same window queried again does not duplicate the deliveries.
    call_reminder_handler()
    assert EmailDelivery.objects.filter(purpose=PEER_REVIEW_DEADLINE_PURPOSE).count() == 6


def test_pooled_review_reminder_skips_a_scored_batch_and_reviews_outside_the_window():
    cohort = pooled_cohort(slug="reminder-pool-skip")
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3)
    batch = PeerReviewBatch.objects.get(project=project)
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() + datetime.timedelta(days=1)
    )
    for review in PeerReview.objects.filter(batch=batch):
        submit_peer_review(review, {criteria.id: "2"})
    batch.refresh_from_db()
    assert batch.scored_at is not None  # fully submitted -> scored already, nothing to remind

    result = call_reminder_handler()

    assert result["reminders"] == 0
    assert EmailDelivery.objects.filter(purpose=PEER_REVIEW_DEADLINE_PURPOSE).count() == 0


def test_pooled_project_state_is_never_read_as_peer_reviewing():
    """A pooled project sitting in COLLECTING_SUBMISSIONS must not be picked up by the
    deadline-mode project scan, which would misread it as a dated cohort in review."""

    cohort = pooled_cohort(slug="reminder-state-guard")
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 3)
    project.refresh_from_db()
    assert project.state == ProjectState.COLLECTING_SUBMISSIONS.value

    from community_base.coursework.reminders import projects_peer_reviewing_between

    now = timezone.now()
    horizon = now + datetime.timedelta(days=30)
    assert project not in list(projects_peer_reviewing_between(now, horizon))
