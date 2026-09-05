from __future__ import annotations

import json

from community_base.jobs.backends import get_backend as get_jobs_backend
from community_base.mail.backends import get_backend as get_mail_backend
from community_base.mail.backends.memory import outbox
from community_base.testing import mail_outbox, signed_relay_request, sync_jobs


def test_sync_jobs_temporarily_selects_sync_backend(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "JOBS_BACKEND": "relay"}
    with sync_jobs():
        assert get_jobs_backend().__name__.endswith(".sync")
    assert get_jobs_backend().__name__.endswith(".relay")


def test_mail_outbox_is_empty_isolated_and_selects_memory(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "MAIL_BACKEND": "relay"}
    outbox.append(object())
    with mail_outbox() as messages:
        assert messages == []
        assert get_mail_backend().__name__.endswith(".memory")
        messages.append(object())
    assert outbox == []
    assert get_mail_backend().__name__.endswith(".relay")


def test_signed_relay_request_uses_canonical_json_and_task_headers():
    signed = signed_relay_request(
        {"second": 2, "first": 1},
        "test-secret",
        timestamp="1788600000",
        task_id="relay-task-1",
        correlation_id="relay-correlation-1",
    )
    assert signed.body == b'{"first":1,"second":2}'
    assert signed.headers == {
        "X-Relay-Timestamp": "1788600000",
        "X-Relay-Signature": (
            "sha256=488154f648555ffb25eaf147f4176415e167788bbd0ff589d6cb35f68038aec9"
        ),
        "X-Relay-Task-Id": "relay-task-1",
        "X-Relay-Correlation-Id": "relay-correlation-1",
    }
    assert json.loads(signed.django_kwargs()["data"]) == {"first": 1, "second": 2}
