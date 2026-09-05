from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.db import transaction
from django.utils import timezone

from community_base.jobs.dispatch import DispatchConflict, DispatchError, dispatch_after_commit
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler
from community_base.kernel.context import context_scope

COMPLETED = []


@register_handler("tests.dispatch.complete")
def complete_handler(context: JobContext, payload: JobPayload):
    COMPLETED.append((context.job_id, payload["record_id"]))


@pytest.fixture(autouse=True)
def clear_completions():
    COMPLETED.clear()


@pytest.mark.django_db(transaction=True)
def test_dispatch_requires_caller_transaction():
    with pytest.raises(DispatchError, match="active transaction"):
        dispatch_after_commit("tests.dispatch.complete", "outside", {"record_id": 1})


@pytest.mark.django_db(transaction=True)
def test_rollback_persists_no_intent_and_runs_no_handler():
    class Rollback(Exception):
        pass

    with pytest.raises(Rollback):
        with transaction.atomic():
            dispatch_after_commit("tests.dispatch.complete", "rollback", {"record_id": 1})
            raise Rollback

    assert not JobIntent.objects.exists()
    assert COMPLETED == []


@pytest.mark.django_db(transaction=True)
def test_commit_persists_hashed_intent_and_sync_backend_runs_once():
    raw_key = "commit-key"
    with transaction.atomic():
        first, first_created = dispatch_after_commit(
            "tests.dispatch.complete", raw_key, {"record_id": 1}
        )
        second, second_created = dispatch_after_commit(
            "tests.dispatch.complete", raw_key, {"record_id": 1}
        )

    first.refresh_from_db()
    assert first_created and not second_created
    assert first.id == second.id
    assert first.status == JobIntent.Status.SUCCEEDED
    assert raw_key not in repr(first.__dict__)
    assert COMPLETED == [(first.id, 1)]


@pytest.mark.django_db(transaction=True)
def test_same_key_with_different_payload_conflicts():
    with transaction.atomic():
        dispatch_after_commit("tests.dispatch.complete", "conflict", {"record_id": 1})

    with pytest.raises(DispatchConflict), transaction.atomic():
        dispatch_after_commit("tests.dispatch.complete", "conflict", {"record_id": 2})


@pytest.mark.django_db(transaction=True)
def test_future_intent_waits_for_due_runner():
    with transaction.atomic():
        intent, _ = dispatch_after_commit(
            "tests.dispatch.complete",
            "future",
            {"record_id": 1},
            available_at=timezone.now() + timedelta(hours=1),
        )

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.PENDING
    assert COMPLETED == []


@pytest.mark.django_db(transaction=True)
def test_dispatch_captures_safe_correlation_context():
    with context_scope(correlation_id="correlation-123"):
        with transaction.atomic():
            intent, _ = dispatch_after_commit(
                "tests.dispatch.complete",
                "context",
                {"record_id": 1},
                available_at=timezone.now() + timedelta(hours=1),
            )

    assert intent.correlation_id == "correlation-123"


@pytest.mark.django_db(transaction=True)
def test_backend_failure_leaves_intent_durable_and_does_not_log_exception_text():
    backend = Mock()
    backend.submit.side_effect = RuntimeError("credential-canary")
    with (
        patch("community_base.jobs.dispatch.get_backend", return_value=backend),
        patch("community_base.jobs.dispatch.logger.warning") as warning,
    ):
        with transaction.atomic():
            intent, _ = dispatch_after_commit(
                "tests.dispatch.complete", "backend-failure", {"record_id": 1}
            )

    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.PENDING
    assert "credential-canary" not in repr(warning.call_args_list)
