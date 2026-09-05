from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.mail.callbacks import apply_callback
from community_base.mail.models import EmailDelivery


@pytest.fixture
def delivery(db):
    return EmailDelivery.objects.create(
        idempotency_key=f"studio:{uuid.uuid4()}",
        purpose="welcome",
        template_key="welcome",
        recipient_email="person@example.com",
        context_hash="abcdef" * 10 + "abcd",
        context_data={"private_name": "Secret Person"},
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(email="mail-staff@example.com", is_staff=True)


@pytest.mark.django_db
def test_mail_studio_requires_staff(client):
    user = get_user_model().objects.create_user(email="mail-member@example.com")
    client.force_login(user)
    assert client.get(reverse("community_base_mail_deliveries")).status_code == 403


@pytest.mark.django_db
def test_mail_studio_filters_and_never_renders_raw_context_or_address(client, staff_user, delivery):
    client.force_login(staff_user)
    response = client.get(
        reverse("community_base_mail_deliveries"),
        {"state": "pending", "purpose": "welcome"},
    )
    assert response.status_code == 200
    assert b"welcome" in response.content
    assert b"p***@example.com" in response.content
    assert b"person@example.com" not in response.content
    assert b"Secret Person" not in response.content
    assert "no-cache" in response.headers["Cache-Control"]


@pytest.mark.django_db
def test_mail_studio_detail_has_redacted_hash_and_callback_history(client, staff_user, delivery):
    apply_callback(event_id="studio:event", delivery_id=delivery.id, state="delivered")
    client.force_login(staff_user)
    response = client.get(reverse("community_base_mail_delivery", args=(delivery.id,)))
    assert response.status_code == 200
    assert b"sha256:abcdefabcdef" in response.content
    assert b"studio:event" in response.content
    assert b"person@example.com" not in response.content
    assert b"Secret Person" not in response.content
