from __future__ import annotations

import uuid
from unittest import mock

import pytest

from community_base.jobs.models import JobIntent
from community_base.jobs.registry import JobContext
from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.mail import relay_links
from community_base.mail.jobs import replay_unsubscribe
from community_base.mail.models import PendingUnsubscribe
from community_base.mail.unsubscribe import accept_unsubscribe_for_replay
from community_base.testing import FakeRelay, unreachable_relay

RELAY = "http://relay.website.internal:8000"
TOKEN = "kD3Yy8x-Ug2f_QwErTyUiOpAsDfGhJkLzXcVbNm1234"


def context():
    return JobContext(
        job_id=uuid.uuid4(),
        correlation_id=None,
        attempt=1,
        worker_id="test",
        lease_token=uuid.uuid4(),
    )


@pytest.fixture(autouse=True)
def configured_relay(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "JOBS_BACKEND": "relay",
        "RELAY_BASE_URL": RELAY,
        "SITE_URL": "http://testserver",
        "RELAY_API_KEY": "test-key",
    }


@pytest.mark.django_db(transaction=True)
def test_acceptance_is_idempotent_and_honours_newer_scope():
    first = accept_unsubscribe_for_replay(token=TOKEN, scope="client")
    second = accept_unsubscribe_for_replay(token=TOKEN, scope="global")
    assert first.pending_id == second.pending_id
    assert PendingUnsubscribe.objects.get().scope == "global"
    assert JobIntent.objects.filter(handler="cb_mail.unsubscribe_replay").count() == 1


@pytest.mark.django_db
def test_malformed_unsubscribe_is_never_durable():
    with pytest.raises(ValueError):
        accept_unsubscribe_for_replay(token="short", scope="client")
    assert not PendingUnsubscribe.objects.exists()


@pytest.mark.django_db
def test_replay_applies_then_deletes_identifying_row():
    pending = PendingUnsubscribe.objects.create(
        unsubscribe_token=TOKEN,
        token_fingerprint=relay_links.token_fingerprint(TOKEN),
        scope="client",
    )
    relay_client = FakeRelay(200)
    with mock.patch.object(relay_links, "_pool", return_value=relay_client):
        replay_unsubscribe(context(), {"pending_unsubscribe_id": str(pending.id)})
    assert not PendingUnsubscribe.objects.exists()
    assert relay_client.calls[-1].data == {"scope": "client"}


@pytest.mark.django_db
def test_unavailable_replay_remains_pending_and_retries():
    pending = PendingUnsubscribe.objects.create(
        unsubscribe_token=TOKEN,
        token_fingerprint=relay_links.token_fingerprint(TOKEN),
        scope="client",
    )
    with (
        mock.patch.object(relay_links, "_pool", return_value=unreachable_relay()),
        pytest.raises(RetryableJobError),
    ):
        replay_unsubscribe(context(), {"pending_unsubscribe_id": str(pending.id)})
    pending.refresh_from_db()
    assert pending.attempt_count == 1
    assert pending.last_outcome == "unavailable"


@pytest.mark.django_db
def test_invalid_replay_payload_fails_permanently():
    with pytest.raises(PermanentJobError):
        replay_unsubscribe(context(), {"pending_unsubscribe_id": "nope"})


@pytest.mark.django_db
def test_rejected_replay_is_settled_and_never_retried():
    pending = PendingUnsubscribe.objects.create(
        unsubscribe_token=TOKEN,
        token_fingerprint=relay_links.token_fingerprint(TOKEN),
        scope="client",
    )
    with mock.patch.object(relay_links, "_pool", return_value=FakeRelay(404)):
        replay_unsubscribe(context(), {"pending_unsubscribe_id": str(pending.id)})
    pending.refresh_from_db()
    assert pending.status == PendingUnsubscribe.Status.REJECTED
    relay_client = FakeRelay(200)
    with mock.patch.object(relay_links, "_pool", return_value=relay_client):
        replay_unsubscribe(context(), {"pending_unsubscribe_id": str(pending.id)})
    assert not relay_client.called


@pytest.mark.django_db
def test_unconfigured_replay_fails_permanently(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_BASE_URL": ""}
    pending = PendingUnsubscribe.objects.create(
        unsubscribe_token=TOKEN,
        token_fingerprint=relay_links.token_fingerprint(TOKEN),
        scope="client",
    )
    with pytest.raises(PermanentJobError, match="relay_bridge_not_configured"):
        replay_unsubscribe(context(), {"pending_unsubscribe_id": str(pending.id)})
