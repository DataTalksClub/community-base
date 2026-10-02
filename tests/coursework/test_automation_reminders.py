import datetime

import pytest
from django.db import transaction
from django.utils import timezone

from community_base.config import service
from community_base.coursework.automation import COURSEWORK_AUTOMATION_KEY
from community_base.coursework.models import PeerReviewBatch
from community_base.coursework.reminders import (
    HOMEWORK_DEADLINE_PURPOSE,
    PEER_REVIEW_DEADLINE_PURPOSE,
    PROJECT_SUBMISSION_DEADLINE_PURPOSE,
)
from community_base.coursework.review import assign_peer_reviews_for_project
from community_base.jobs.registry import get_handler
from community_base.mail.models import EmailDelivery
from tests.coursework.test_models import coursework_cohort, enrollment_for, homework
from tests.coursework.test_peer_review import make_submissions
from tests.coursework.test_pooling import pooled_cohort, pooled_project, submit_batch_of
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db(transaction=True)

HANDLERS = (
    "coursework.send_homework_deadline_reminders",
    "coursework.send_project_submission_deadline_reminders",
    "coursework.send_peer_review_deadline_reminders",
)
REMINDER_PURPOSES = (
    HOMEWORK_DEADLINE_PURPOSE,
    PROJECT_SUBMISSION_DEADLINE_PURPOSE,
    PEER_REVIEW_DEADLINE_PURPOSE,
)


@pytest.fixture(autouse=True)
def reset_runtime_config():
    service.runtime.reset()
    yield
    service.runtime.reset()


def disable_automation():
    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:reminder-guard")


def call_handler(name, payload=None):
    with transaction.atomic():
        return get_handler(name)(None, payload or {})


def _homework_fixture():
    cohort = coursework_cohort(slug="guard-homework-reminder")
    homework(cohort, due_date=timezone.now() + datetime.timedelta(days=1))
    enrollment_for(cohort, email="guard-homework-reminder@example.com")


def _project_fixture():
    cohort = coursework_cohort(slug="guard-project-reminder")
    make_project(
        cohort,
        slug="guard-project-reminder",
        submission_due_date=timezone.now() + datetime.timedelta(days=1),
    )
    enrollment_for(cohort, email="guard-project-reminder@example.com")


def _peer_review_fixtures():
    cohort = coursework_cohort(slug="guard-deadline-review")
    project = make_project(
        cohort,
        slug="guard-deadline-review",
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_submissions(project, cohort, 3, prefix="guard-deadline-review")
    assign_peer_reviews_for_project(project)

    pooled = pooled_cohort(slug="guard-pooled-review")
    pooled_project_row = pooled_project(pooled, slug="guard-pooled-review")
    submit_batch_of(pooled_project_row, pooled, 3, prefix="guard-pooled-review")
    batch = PeerReviewBatch.objects.get(project=pooled_project_row)
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() + datetime.timedelta(days=1)
    )


@pytest.mark.parametrize(
    ("handler", "purpose"),
    [
        ("coursework.send_homework_deadline_reminders", HOMEWORK_DEADLINE_PURPOSE),
        (
            "coursework.send_project_submission_deadline_reminders",
            PROJECT_SUBMISSION_DEADLINE_PURPOSE,
        ),
        ("coursework.send_peer_review_deadline_reminders", PEER_REVIEW_DEADLINE_PURPOSE),
    ],
)
def test_false_mode_returns_zero_before_invalid_window_parsing(handler, purpose):
    disable_automation()

    result = get_handler(handler)(None, {"window_days": "invalid"})

    assert result == {"reminders": 0}
    assert EmailDelivery.objects.filter(purpose=purpose).count() == 0


def test_disabled_eligible_rows_stay_pending_then_resume_without_new_rows():
    _homework_fixture()
    _project_fixture()
    _peer_review_fixtures()
    disable_automation()

    for handler in HANDLERS:
        assert call_handler(handler, {"window_days": 8}) == {"reminders": 0}
    assert EmailDelivery.objects.filter(purpose__in=REMINDER_PURPOSES).count() == 0

    service.set(COURSEWORK_AUTOMATION_KEY, True, "test:reminder-guard")
    results = []
    for handler in HANDLERS:
        results.append(call_handler(handler, {"window_days": 8}))

    assert results[0]["reminders"] == 1
    assert results[1]["reminders"] == 1
    assert results[2]["reminders"] == 12
    assert EmailDelivery.objects.filter(purpose=HOMEWORK_DEADLINE_PURPOSE).count() == 1
    assert EmailDelivery.objects.filter(purpose=PROJECT_SUBMISSION_DEADLINE_PURPOSE).count() == 1
    assert EmailDelivery.objects.filter(purpose=PEER_REVIEW_DEADLINE_PURPOSE).count() == 12
