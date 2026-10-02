import datetime
import uuid

import pytest
from django.utils import timezone

from community_base.config import service
from community_base.coursework.automation import COURSEWORK_AUTOMATION_KEY
from community_base.coursework.models import PeerReview, PeerReviewBatch, PeerReviewState
from community_base.coursework.notifications import (
    POOL_READY_PURPOSE,
    REVIEW_WINDOW_EXPIRED_PURPOSE,
)
from community_base.jobs.models import JobIntent
from community_base.jobs.operations import run_due
from community_base.jobs.runner import sweep_expired_jobs
from community_base.jobs.scheduling import dispatch_registered_schedule
from community_base.mail.models import EmailDelivery
from community_base.testing import signed_relay_request
from tests.coursework.test_pooling import (
    pooled_cohort,
    pooled_project,
    submit_batch_of,
    waiting_submissions_without_batching,
)

pytestmark = pytest.mark.django_db(transaction=True)

SECRET = "test-relay-webhook-secret"
FORMATION_SCHEDULE = "coursework.form_pooled_batches.every_15_minutes"
EXPIRY_SCHEDULE = "coursework.expire_pooled_reviews.every_15_minutes"


@pytest.fixture(autouse=True)
def reset_runtime_config():
    service.runtime.reset()
    yield
    service.runtime.reset()


def disable_automation():
    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:transport-guard")


def formation_fixture(slug):
    cohort = pooled_cohort(slug=slug)
    project = pooled_project(cohort)
    waiting_submissions_without_batching(project, cohort, 3, prefix=slug)
    return project


def make_intent(handler):
    return JobIntent.objects.create(
        handler=handler,
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        payload={},
        payload_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        available_at=timezone.now(),
    )


def observe_hooks(settings):
    events = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_PEER_REVIEWS_ASSIGNED": lambda **event: events.append(event),
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER": lambda **event: events.append(event),
    }
    return events


def assert_no_formation_effect(project, events):
    assert PeerReviewBatch.objects.filter(project=project).count() == 0
    assert EmailDelivery.objects.filter(purpose=POOL_READY_PURPOSE).count() == 0
    assert events == []


def assert_no_expiry_effect(batch, events):
    assert (
        not PeerReview.objects.filter(batch=batch)
        .exclude(state=PeerReviewState.TO_REVIEW.value)
        .exists()
    )
    assert EmailDelivery.objects.filter(purpose=REVIEW_WINDOW_EXPIRED_PURPOSE).count() == 0
    assert events == []


def test_local_registered_schedule_completes_without_forming_a_batch(settings):
    project = formation_fixture("guard-local-schedule")
    events = observe_hooks(settings)
    disable_automation()

    intent_id = dispatch_registered_schedule(schedule_name=FORMATION_SCHEDULE)

    intent = JobIntent.objects.get(pk=intent_id)
    assert intent.handler == "coursework.form_pooled_batches"
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert_no_formation_effect(project, events)


def test_signed_relay_schedule_completes_without_expiring_reviews(client, settings):
    cohort = pooled_cohort(slug="guard-relay-schedule")
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 3, prefix="guard-relay-schedule")
    batch = PeerReviewBatch.objects.get(project=project)
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() - datetime.timedelta(minutes=1)
    )
    events = observe_hooks(settings)
    disable_automation()
    signed = signed_relay_request(
        {"schedule_name": EXPIRY_SCHEDULE},
        SECRET,
        task_id=str(uuid.uuid4()),
        correlation_id="guard-relay-schedule",
    )

    response = client.post("/internal/jobs/run", **signed.django_kwargs())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "result": "succeeded"}
    intent = JobIntent.objects.get(handler="coursework.expire_pooled_reviews")
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert_no_expiry_effect(batch, events)


def test_due_runner_completes_guarded_intent_without_domain_effect(settings):
    project = formation_fixture("guard-due-runner")
    events = observe_hooks(settings)
    intent = make_intent("coursework.form_pooled_batches")
    disable_automation()

    assert run_due() == (1, 1)

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert_no_formation_effect(project, events)


def test_recovered_lease_retries_guarded_handler_without_domain_effect(settings):
    project = formation_fixture("guard-lease-recovery")
    events = observe_hooks(settings)
    intent = make_intent("coursework.form_pooled_batches")
    JobIntent.objects.filter(pk=intent.pk).update(
        status=JobIntent.Status.RUNNING,
        attempts=1,
        lease_token=uuid.uuid4(),
        lease_expires_at=timezone.now() - datetime.timedelta(seconds=1),
    )
    disable_automation()

    assert sweep_expired_jobs() == (1, 0)
    JobIntent.objects.filter(pk=intent.pk).update(available_at=timezone.now())
    assert run_due() == (1, 1)

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.SUCCEEDED
    assert_no_formation_effect(project, events)
