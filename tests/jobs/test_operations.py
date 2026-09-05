import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext, JobPayload, register_handler, schedule
from community_base.jobs.scheduling import desired_local_schedules, schedule_changes

COMPLETED = []


@register_handler("tests.operations.complete")
def complete_handler(context: JobContext, payload: JobPayload):
    COMPLETED.append(context.job_id)


schedule(
    "tests.operations.complete",
    "17 * * * *",
    {"record_id": 1},
    name="tests.operations.hourly",
)


def make_intent(*, available_at=None):
    return JobIntent.objects.create(
        handler="tests.operations.complete",
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        payload={"record_id": 1},
        payload_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        available_at=available_at or timezone.now(),
    )


@pytest.fixture(autouse=True)
def clear_completed():
    COMPLETED.clear()


@pytest.mark.django_db
def test_jobs_run_due_runs_only_due_intents(capsys):
    due = make_intent()
    future = make_intent(available_at=timezone.now() + timedelta(hours=1))
    call_command("jobs_run_due")
    due.refresh_from_db()
    future.refresh_from_db()
    assert due.status == JobIntent.Status.SUCCEEDED
    assert future.status == JobIntent.Status.PENDING
    assert COMPLETED == [due.id]
    assert "found=1 submitted=1" in capsys.readouterr().out


@pytest.mark.django_db
def test_jobs_sweep_reports_expired_leases(capsys):
    intent = make_intent()
    JobIntent.objects.filter(id=intent.id).update(
        status=JobIntent.Status.RUNNING,
        attempts=1,
        lease_token=uuid.uuid4(),
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )
    call_command("jobs_sweep")
    intent.refresh_from_db()
    assert intent.status == JobIntent.Status.FAILED
    assert "recovered=1 dead=0" in capsys.readouterr().out


def test_schedule_diff_identifies_create_update_and_unchanged():
    specs = {item.name: item for item in desired_local_schedules()}
    due = specs["community-base:jobs-run-due"]
    hourly = specs["community-base:tests.operations.hourly"]
    existing = {
        due.name: {
            "func": due.func,
            "cron": due.cron,
            "kwargs": due.kwargs,
            "repeats": -1,
        },
        hourly.name: {
            "func": hourly.func,
            "cron": "0 0 * * *",
            "kwargs": hourly.kwargs,
            "repeats": -1,
        },
    }
    assert schedule_changes(existing) == (
        ("unchanged", "community-base:jobs-run-due"),
        ("update", "community-base:tests.operations.hourly"),
    )
    assert schedule_changes({}) == (
        ("create", "community-base:jobs-run-due"),
        ("create", "community-base:tests.operations.hourly"),
    )


def test_sync_schedules_is_a_noop_for_sync_backend(capsys, settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "JOBS_BACKEND": "sync"}
    call_command("sync_schedules")
    assert "no persistent scheduler" in capsys.readouterr().out


@pytest.mark.django_db
def test_due_runner_submits_each_identifier_to_selected_backend():
    first = make_intent()
    second = make_intent()
    backend = Mock()
    with patch("community_base.jobs.operations.get_backend", return_value=backend):
        from community_base.jobs.operations import run_due

        assert run_due() == (2, 2)
    assert {call.args[0] for call in backend.submit.call_args_list} == {first.id, second.id}
