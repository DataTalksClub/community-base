from __future__ import annotations

import pytest
from django.db import transaction

from community_base.jobs.models import JobIntent
from community_base.mail.backends.memory import outbox
from community_base.mail.models import EmailDelivery
from community_base.mail.service import MailConflict, MailError, send
from community_base.testing import mail_outbox


@pytest.fixture(autouse=True)
def clear_outbox():
    with mail_outbox():
        yield


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


def _set_template_version_resolver(settings, resolver):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_TEMPLATE_VERSION_RESOLVER": resolver,
    }


@pytest.mark.django_db(transaction=True)
def test_policy_bump_replays_accepted_delivery_at_recorded_version(settings):
    versions = {"welcome": 1}
    _set_template_version_resolver(settings, lambda key: versions[key])
    with transaction.atomic():
        original = send("welcome", "person@example.com", {}, "welcome:versioned")
    EmailDelivery.objects.filter(pk=original.pk).update(
        external_message_id="relay-original",
    )
    original.refresh_from_db()
    assert original.state == EmailDelivery.State.PROVIDER_ACCEPTED
    assert original.external_message_id == "relay-original"

    versions["welcome"] = 2
    with transaction.atomic():
        replay = send("welcome", "person@example.com", {}, "welcome:versioned")

    assert replay.pk == original.pk
    assert replay.template_version == 1
    assert replay.state == EmailDelivery.State.PROVIDER_ACCEPTED
    assert replay.external_message_id == original.external_message_id
    assert EmailDelivery.objects.count() == 1
    assert JobIntent.objects.count() == 1
    assert len(outbox) == 1


@pytest.mark.django_db(transaction=True)
def test_policy_bump_still_rejects_changed_idempotent_work(settings):
    versions = {"welcome": 1}
    _set_template_version_resolver(settings, lambda key: versions[key])
    with transaction.atomic():
        send("welcome", "person@example.com", {"name": "Ada"}, "welcome:changed")

    versions["welcome"] = 2
    with transaction.atomic():
        with pytest.raises(MailConflict, match="idempotency key conflicts"):
            send("welcome", "person@example.com", {"name": "Grace"}, "welcome:changed")
    assert EmailDelivery.objects.count() == 1
    assert JobIntent.objects.count() == 1
    assert len(outbox) == 1


@pytest.mark.django_db(transaction=True)
def test_new_key_uses_version_from_current_policy(settings):
    versions = {"welcome": 1}
    _set_template_version_resolver(settings, lambda key: versions[key])
    with transaction.atomic():
        first = send("welcome", "first@example.com", {}, "welcome:first")
    versions["welcome"] = 2
    with transaction.atomic():
        second = send("welcome", "second@example.com", {}, "welcome:second")

    assert first.template_version == 1
    assert second.template_version == 2


def _failing_version_resolver(_key):
    raise RuntimeError("resolver unavailable")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("resolver", [lambda _key: 0, _failing_version_resolver])
def test_broken_resolver_does_not_break_exact_existing_replay(settings, resolver):
    _set_template_version_resolver(settings, lambda _key: 1)
    with transaction.atomic():
        original = send("welcome", "person@example.com", {}, "welcome:resolver-down")

    _set_template_version_resolver(settings, resolver)
    with transaction.atomic():
        replay = send("welcome", "person@example.com", {}, "welcome:resolver-down")

    assert replay.pk == original.pk
    assert replay.template_version == 1
    assert JobIntent.objects.count() == 1
    assert len(outbox) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("version", [True, False, 0, -1, "2", None])
def test_template_version_resolver_fails_closed_on_invalid_values(settings, version):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_TEMPLATE_VERSION_RESOLVER": lambda _key: version,
    }

    with transaction.atomic():
        with pytest.raises(MailError, match="invalid version"):
            send("welcome", "person@example.com", {}, f"welcome:invalid:{version}")

    assert not EmailDelivery.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_template_version_defaults_to_one_without_resolver():
    with transaction.atomic():
        delivery = send("welcome", "person@example.com", {}, "welcome:default-version")

    assert delivery.template_version == 1


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
