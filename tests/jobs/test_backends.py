import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from django.core.exceptions import ImproperlyConfigured

from community_base.jobs.backends import django_q, get_backend


def test_backend_loader_selects_sync(settings):
    settings.COMMUNITY_BASE["JOBS_BACKEND"] = "sync"
    assert get_backend().__name__.endswith(".sync")


def test_backend_loader_rejects_unimplemented_relay(settings):
    settings.COMMUNITY_BASE["JOBS_BACKEND"] = "relay"
    with pytest.raises(ImproperlyConfigured, match="C1.1a"):
        get_backend()


def test_django_q_backend_submits_only_intent_identifier(monkeypatch):
    package = ModuleType("django_q")
    package.__path__ = []
    tasks = ModuleType("django_q.tasks")
    tasks.async_task = Mock(return_value="task-id")
    monkeypatch.setitem(sys.modules, "django_q", package)
    monkeypatch.setitem(sys.modules, "django_q.tasks", tasks)

    result = django_q.submit("00000000-0000-0000-0000-000000000001")

    assert result == "task-id"
    tasks.async_task.assert_called_once()
    assert tasks.async_task.call_args.args == (
        "community_base.jobs.runner.run_intent",
        "00000000-0000-0000-0000-000000000001",
    )
