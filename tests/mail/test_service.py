from __future__ import annotations

import pytest
from django.db import transaction

from community_base.jobs.models import JobIntent
from community_base.mail.backends.memory import outbox
from community_base.mail.models import EmailDelivery
from community_base.mail.service import MailConflict, MailError, send


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()
    yield
    outbox.clear()


@pytest.mark.django_db(transaction=True)
def test_send_requires_the_callers_transaction():
    with pytest.raises(MailError, match="active transaction"):
        send("welcome", "person@example.com", {"name": "Person"}, "welcome:1")


@pytest.mark.django_db(transaction=True)
def test_commit_persists_delivery_and_job_then_runs_memory_backend():
    with transaction.atomic():
        delivery = send(
            "welcome",
            "person@example.com",
            {"name": "Person"},
            "welcome:1",
            category="transactional",
        )
        assert delivery.state == EmailDelivery.State.PENDING
        assert delivery.job is not None
        assert outbox == []

    delivery.refresh_from_db()
    delivery.job.refresh_from_db()
    assert delivery.state == EmailDelivery.State.PROVIDER_ACCEPTED
    assert delivery.job.status == JobIntent.Status.SUCCEEDED
    assert len(outbox) == 1
    assert outbox[0].delivery_id == delivery.id
    assert dict(outbox[0].context) == {"name": "Person"}
    assert delivery.context_data == {"name": "Person"}


@pytest.mark.django_db(transaction=True)
def test_rollback_persists_nothing_and_sends_nothing():
    with pytest.raises(RuntimeError, match="rollback"):
        with transaction.atomic():
            send("welcome", "person@example.com", {}, "welcome:rollback")
            raise RuntimeError("rollback")

    assert not EmailDelivery.objects.exists()
    assert not JobIntent.objects.exists()
    assert outbox == []


@pytest.mark.django_db(transaction=True)
def test_exact_replay_returns_original_and_changed_work_conflicts():
    with transaction.atomic():
        original = send("welcome", "person@example.com", {"version": 1}, "welcome:replay")
        replay = send("welcome", "person@example.com", {"version": 1}, "welcome:replay")
        assert replay.pk == original.pk
        with pytest.raises(MailConflict):
            send("welcome", "person@example.com", {"version": 2}, "welcome:replay")

    assert EmailDelivery.objects.count() == 1
    assert JobIntent.objects.count() == 1
    assert len(outbox) == 1


@pytest.mark.django_db(transaction=True)
def test_preference_suppression_records_no_job_or_send(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_PREFERENCE_RESOLVER": lambda **kwargs: "marketing_opt_out",
    }
    with transaction.atomic():
        delivery = send(
            "newsletter",
            "person@example.com",
            {},
            "newsletter:1",
            category="promotional",
        )

    delivery.refresh_from_db()
    assert delivery.state == EmailDelivery.State.SUPPRESSED
    assert delivery.reason_code == "marketing_opt_out"
    assert delivery.job is None
    assert outbox == []


@pytest.mark.django_db(transaction=True)
def test_job_payload_contains_only_the_delivery_identifier():
    with transaction.atomic():
        delivery = send("welcome", "person@example.com", {}, "welcome:payload")

    assert delivery.job.payload == {"delivery_id": str(delivery.id)}
    assert "person@example.com" not in str(delivery.job.payload)
