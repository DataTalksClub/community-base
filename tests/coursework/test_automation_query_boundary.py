import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from community_base.config import service
from community_base.coursework import pooling, reminders
from community_base.coursework.automation import COURSEWORK_AUTOMATION_KEY
from community_base.coursework.models import (
    CriteriaResponse,
    PeerReview,
    PeerReviewBatch,
    PeerReviewState,
    Project,
)
from community_base.coursework.review import assign_peer_reviews_for_project
from community_base.jobs.registry import get_handler
from tests.coursework.test_models import coursework_cohort, enrollment_for, homework
from tests.coursework.test_peer_review import make_criteria, make_submissions
from tests.coursework.test_pooling import (
    pooled_cohort,
    pooled_project,
    submit_batch_of,
    waiting_submissions_without_batching,
)
from tests.coursework.test_projects import make_project
from tests.curriculum.test_models import make_cohort, make_course

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def reset_runtime_config():
    service.runtime.reset()
    yield
    service.runtime.reset()


class DeferredProjectSentinel:
    @property
    def uses_pooled_review(self):
        raise AssertionError("project state was read before the policy")


@pytest.mark.parametrize(
    ("module", "entrypoint", "args", "collaborator", "expected"),
    [
        (pooling, "try_form_batch", (DeferredProjectSentinel(),), None, None),
        (pooling, "form_pooled_batches", (object(),), "try_form_batch", []),
        (pooling, "try_score_batch", (object(),), "transaction", False),
        (
            pooling,
            "form_pooled_batches_job",
            (None, {}),
            "_projects_with_waiting_submissions",
            {"formed_batches": 0},
        ),
        (
            pooling,
            "expire_pooled_reviews",
            (None, {}),
            "_expired_pooled_reviews",
            {"expired": 0, "scored_batches": 0},
        ),
        (
            reminders,
            "send_homework_deadline_reminders",
            (None, {}),
            "_window",
            {"reminders": 0},
        ),
        (
            reminders,
            "send_project_submission_deadline_reminders",
            (None, {}),
            "_window",
            {"reminders": 0},
        ),
        (
            reminders,
            "send_peer_review_deadline_reminders",
            (None, {}),
            "_window",
            {"reminders": 0},
        ),
    ],
)
def test_each_entrypoint_reads_one_policy_before_its_first_collaborator(
    monkeypatch, module, entrypoint, args, collaborator, expected
):
    policy_lookup = Mock(return_value=SimpleNamespace(enabled=False))
    monkeypatch.setattr(module, "get_automation_policy", policy_lookup)
    if collaborator == "transaction":
        monkeypatch.setattr(module.transaction, "atomic", Mock(side_effect=AssertionError))
    elif collaborator is not None:
        monkeypatch.setattr(module, collaborator, Mock(side_effect=AssertionError))

    result = getattr(module, entrypoint)(*args)

    assert result == expected
    assert type(result) is type(expected)
    policy_lookup.assert_called_once_with()


def _formation_fixture():
    cohort = pooled_cohort(slug="guard-query-formation")
    project = pooled_project(cohort)
    waiting_submissions_without_batching(project, cohort, 3, prefix="guard-query-waiting")
    return Project.objects.only("id").get(pk=project.pk), project


def _resolved_batch_fixture():
    course = make_course(slug="guard-query-score-course")
    cohort = make_cohort(course, slug="guard-query-score", mode="self_paced")
    cohort.project_passing_score = 5
    cohort.save(update_fields=["project_passing_score"])
    project = pooled_project(cohort)
    criteria = make_criteria(project)
    submit_batch_of(project, cohort, 3, prefix="guard-query-score")
    batch = PeerReviewBatch.objects.get(project=project)
    PeerReview.objects.filter(batch=batch).update(
        state=PeerReviewState.SUBMITTED.value,
        submitted_at=timezone.now(),
    )
    for review in PeerReview.objects.filter(batch=batch):
        CriteriaResponse.objects.create(review=review, criteria=criteria, answer="2")
    return batch


def _overdue_batch_fixture():
    course = make_course(slug="guard-query-expiry-course")
    cohort = make_cohort(course, slug="guard-query-expiry", mode="self_paced")
    cohort.project_passing_score = 5
    cohort.save(update_fields=["project_passing_score"])
    project = pooled_project(cohort)
    submit_batch_of(project, cohort, 3, prefix="guard-query-expiry")
    batch = PeerReviewBatch.objects.get(project=project)
    PeerReviewBatch.objects.filter(pk=batch.pk).update(
        due_at=timezone.now() - datetime.timedelta(1)
    )


def _reminder_fixtures():
    cohort = coursework_cohort(slug="guard-query-reminders")
    homework(cohort, due_date=timezone.now() + datetime.timedelta(days=1))
    enrollment_for(cohort, email="guard-query-homework@example.com")
    make_project(
        cohort,
        slug="guard-query-project-due",
        submission_due_date=timezone.now() + datetime.timedelta(days=1),
    )

    review_cohort = coursework_cohort(slug="guard-query-review")
    review_project = make_project(
        review_cohort,
        slug="guard-query-review-project",
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_submissions(review_project, review_cohort, 3, prefix="guard-query-review")
    assign_peer_reviews_for_project(review_project)


def _guarded_calls(deferred_project, formation_project, resolved_batch):
    return (
        (lambda: pooling.try_form_batch(deferred_project), None),
        (lambda: pooling.form_pooled_batches(formation_project), []),
        (lambda: pooling.try_score_batch(resolved_batch), False),
        (lambda: get_handler("coursework.form_pooled_batches")(None, {}), {"formed_batches": 0}),
        (
            lambda: get_handler("coursework.expire_pooled_reviews")(None, {}),
            {"expired": 0, "scored_batches": 0},
        ),
        (
            lambda: get_handler("coursework.send_homework_deadline_reminders")(
                None, {"window_days": "invalid"}
            ),
            {"reminders": 0},
        ),
        (
            lambda: get_handler("coursework.send_project_submission_deadline_reminders")(
                None, {"window_days": "invalid"}
            ),
            {"reminders": 0},
        ),
        (
            lambda: get_handler("coursework.send_peer_review_deadline_reminders")(
                None, {"window_days": "invalid"}
            ),
            {"reminders": 0},
        ),
    )


def _assert_no_coursework_query(call, expected):
    with CaptureQueriesContext(connection) as captured:
        result = call()
    coursework_queries = []
    for query in captured:
        if "cb_coursework_" in query["sql"]:
            coursework_queries.append(query["sql"])
    assert result == expected
    assert type(result) is type(expected)
    assert coursework_queries == []


def test_false_mode_performs_no_coursework_query_across_all_eight_entries():
    deferred_project, formation_project = _formation_fixture()
    resolved_batch = _resolved_batch_fixture()
    _overdue_batch_fixture()
    _reminder_fixtures()
    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:query-boundary")

    for call, expected in _guarded_calls(deferred_project, formation_project, resolved_batch):
        _assert_no_coursework_query(call, expected)
