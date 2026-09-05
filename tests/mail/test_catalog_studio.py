from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.mail.relay import RelayMailClient
from community_base.testing import FakeRelay


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(username="catalog-staff", is_staff=True)


@pytest.fixture
def relay_client():
    transport = FakeRelay()
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    client.put_template("welcome", {"name": "Welcome"})
    return client


@pytest.mark.django_db
def test_catalog_studio_lists_templates_and_requires_staff(client, staff_user, relay_client):
    url = reverse("community_base_mail_templates")
    assert client.get(url).status_code == 302
    client.force_login(staff_user)
    with patch("community_base.mail.catalog_studio.configured_client", return_value=relay_client):
        response = client.get(url)
    assert response.status_code == 200
    assert b"welcome" in response.content


@pytest.mark.django_db
def test_catalog_studio_publishes_previews_and_test_sends(client, staff_user, relay_client):
    client.force_login(staff_user)
    url = reverse("community_base_mail_template", args=("welcome",))
    with patch("community_base.mail.catalog_studio.configured_client", return_value=relay_client):
        published = client.post(url, {"action": "publish", "context": "{}"})
        preview = client.post(
            url,
            {"action": "preview", "version": "1", "context": '{"name":"Alexey"}'},
        )
        sent = client.post(
            url,
            {
                "action": "test-send",
                "version": "1",
                "context": '{"name":"Alexey"}',
                "recipient": "staff@example.com",
            },
        )
    assert b"Template version published" in published.content
    assert b"Hello Alexey" in preview.content
    assert b"Test message queued" in sent.content
    assert b"staff@example.com" not in sent.content


@pytest.mark.django_db
def test_catalog_studio_rejects_invalid_context_without_network_payload_leak(
    client, staff_user, relay_client
):
    client.force_login(staff_user)
    url = reverse("community_base_mail_template", args=("welcome",))
    with patch("community_base.mail.catalog_studio.configured_client", return_value=relay_client):
        response = client.post(url, {"action": "preview", "context": "not-json"})
    assert response.status_code == 200
    assert b"invalid_input" in response.content
    assert b"not-json" not in response.content


@pytest.mark.django_db
def test_catalog_studio_reports_unconfigured_relay(client, staff_user, settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "RELAY_BASE_URL": "",
        "RELAY_API_KEY": "",
    }
    client.force_login(staff_user)
    listing = client.get(reverse("community_base_mail_templates"))
    detail = client.get(reverse("community_base_mail_template", args=("welcome",)))
    assert listing.status_code == detail.status_code == 200
    assert b"relay_not_configured" in listing.content
    assert b"relay_not_configured" in detail.content
