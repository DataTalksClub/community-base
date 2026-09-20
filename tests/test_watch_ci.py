"""Offline tests for the on-call CI watcher (`scripts/watch-ci.py`)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "watch-ci.py"
_spec = importlib.util.spec_from_file_location("watch_ci", MODULE_PATH)
assert _spec and _spec.loader
watch_ci = importlib.util.module_from_spec(_spec)
sys.modules["watch_ci"] = watch_ci
_spec.loader.exec_module(watch_ci)

REQUIRED = watch_ci.PR_REQUIRED_CHECKS


def job(name, *, status="completed", conclusion="success", url=""):
    return {"name": name, "status": status, "conclusion": conclusion, "detailsUrl": url}


def pr_payload(checks, *, branch="c7.12a"):
    return {"headRefName": branch, "statusCheckRollup": checks}


class FakeGh:
    def __init__(self, *, views=None, log_failed=""):
        self._views = list(views or [])
        self._view_index = 0
        self._log_failed = log_failed
        self.calls: list[list[str]] = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if "pr" in args and "view" in args:
            payload = self._views[min(self._view_index, len(self._views) - 1)]
            self._view_index += 1
            return json.dumps(payload)
        if "run" in args and "view" in args and "--log-failed" in args:
            return self._log_failed
        raise AssertionError(f"unexpected gh args: {args}")


def make_watcher(runner, **kwargs):
    defaults = dict(
        runner=runner,
        clock=watch_ci.VirtualClock(),
        pr_number="289",
        interval=15.0,
        no_progress_timeout=900.0,
        max_wall_clock=5400.0,
        gh_retry_budget=5,
    )
    defaults.update(kwargs)
    return watch_ci.CIWatcher(**defaults)


def all_required_success():
    return [job(name) for name in REQUIRED]


def test_green_when_every_required_pr_check_succeeds():
    gh = FakeGh(views=[pr_payload(all_required_success())])
    verdict = make_watcher(gh).watch()

    assert verdict.result == watch_ci.GREEN
    assert verdict.exit_code == 0
    assert verdict.failing_jobs == []


def test_failed_dtc_consumer_job_is_not_green():
    checks = all_required_success()
    checks[2] = job(
        REQUIRED[2],
        conclusion="failure",
        url="https://github.com/DataTalksClub/community-base/actions/runs/35527665633",
    )
    gh = FakeGh(
        views=[pr_payload(checks)],
        log_failed="AssertionError: Gate B hash mismatch\n",
    )
    verdict = make_watcher(gh).watch()

    assert verdict.result == watch_ci.FAILED
    assert verdict.exit_code == 1
    assert REQUIRED[2] in verdict.failing_jobs
    assert verdict.signature is not None
    assert "AssertionError" in verdict.signature


def test_empty_rollup_keeps_watching_until_hang():
    gh = FakeGh(views=[pr_payload([])])
    watcher = make_watcher(gh, interval=15.0, no_progress_timeout=60.0, max_wall_clock=100000.0)
    verdict = watcher.watch()

    assert verdict.result == watch_ci.HANG
    assert verdict.exit_code == 2
