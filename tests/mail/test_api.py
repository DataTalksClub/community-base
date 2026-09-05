from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model

from community_base.api.models import APIKey
from community_base.mail.callbacks import apply_callback
from community_base.mail.models import EmailDelivery


@pytest.fixture
def delivery(db):
    return EmailDelivery.objects.create(
        idempotency_key=f"api:{uuid.uuid4()}",
        purpose="welcome",
        category="transactional",
        template_key="welcome",
        recipient_email="person@example.com",
        context_hash="abcdef" * 10 + "abcd",
        context_data={"private_name": "Secret Person"},
    )


@pytest.fixture
def scoped_keys(db):
    user = get_user_model().objects.create_user(username="mail-api", is_staff=True)
    _, read_key = APIKey.create_for_user(
        user=user,
        name="Mail reader",
        scopes=["mail.read"],
        kind=APIKey.Kind.STAFF,
    )
    _, write_key = APIKey.create_for_user(
        user=user,
        name="Mail writer",
        scopes=["mail.write"],
        kind=APIKey.Kind.STAFF,
    )
    return read_key, write_key


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.django_db
def test_delivery_api_enforces_scopes_and_redacts_private_data(client, scoped_keys, delivery):
    read_key, write_key = scoped_keys
    denied = client.get("/api/v1/mail/deliveries", headers=bearer(write_key))
    listed = client.get("/api/v1/mail/deliveries", headers=bearer(read_key))
    detailed = client.get(
        f"/api/v1/mail/deliveries/{delivery.id}",
        headers=bearer(read_key),
    )

    assert denied.status_code == 403
    assert listed.status_code == 200
    assert detailed.status_code == 200
    assert listed.json()["deliveries"][0]["recipient"] == "p***@example.com"
    assert detailed.json()["context_hash"] == "sha256:abcdefabcdef"
    combined = listed.content + detailed.content
    assert b"person@example.com" not in combined
    assert b"Secret Person" not in combined


@pytest.mark.django_db
def test_delivery_api_filters_and_includes_callback_history(client, scoped_keys, delivery):
    read_key, _ = scoped_keys
    apply_callback(event_id="api:event", delivery_id=delivery.id, state="delivered")
    response = client.get(
        f"/api/v1/mail/deliveries?state=delivered&purpose={delivery.purpose}",
        headers=bearer(read_key),
    )
    detail = client.get(
        f"/api/v1/mail/deliveries/{delivery.id}",
        headers=bearer(read_key),
    )

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    assert detail.json()["callbacks"][0]["event_id"] == "api:event"


@pytest.mark.django_db(transaction=True)
def test_resend_creates_new_audited_delivery_never_reuses_original(client, scoped_keys, delivery):
    _, write_key = scoped_keys
    response = client.post(
        f"/api/v1/mail/deliveries/{delivery.id}/resend",
        headers=bearer(write_key),
    )

    assert response.status_code == 201
    replacement = EmailDelivery.objects.exclude(pk=delivery.pk).get()
    assert replacement.related_object_type == "cb_mail.emaildelivery"
    assert replacement.related_object_id == str(delivery.id)
    assert replacement.idempotency_key.startswith(f"resend:{delivery.id}:")
    assert replacement.context_data == delivery.context_data
    assert replacement.job_id is not None


@pytest.mark.django_db
def test_delivery_api_returns_standard_not_found(client, scoped_keys):
    read_key, _ = scoped_keys
    response = client.get(
        f"/api/v1/mail/deliveries/{uuid.uuid4()}",
        headers=bearer(read_key),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "mail_delivery_not_found"
