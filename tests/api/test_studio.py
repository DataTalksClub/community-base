import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.api.models import APIKey


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        email="admin@example.invalid",
        password="not-used",
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(email="staff@example.com", is_staff=True)


def test_api_key_studio_requires_superuser(client, staff_user):
    client.force_login(staff_user)

    response = client.get(reverse("community_base_api_keys"))

    assert response.status_code == 403


def test_api_key_studio_creates_key_with_one_time_display(client, superuser):
    client.force_login(superuser)

    response = client.post(
        reverse("community_base_api_keys"),
        {
            "user": superuser.pk,
            "name": "Automation",
            "kind": APIKey.Kind.STAFF,
            "scopes": "fixtures.read, settings.write",
        },
    )

    assert response.status_code == 200
    assert b"Copy this key now" in response.content
    api_key = APIKey.objects.get()
    plaintext = response.context["plaintext"]
    assert plaintext.encode() in response.content
    assert plaintext not in api_key.key_hash
    assert "no-cache" in response.headers["Cache-Control"]

    refreshed = client.get(reverse("community_base_api_keys"))
    assert plaintext.encode() not in refreshed.content


def test_api_key_studio_requires_explicit_revocation_confirmation(client, superuser):
    client.force_login(superuser)
    api_key, _ = APIKey.create_for_user(
        user=superuser,
        name="Automation",
        scopes=["fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )
    url = reverse("community_base_api_key_revoke", args=(api_key.pk,))

    response = client.post(url, {"confirmation": "yes"})
    api_key.refresh_from_db()
    assert response.status_code == 302
    assert not api_key.is_revoked

    response = client.post(url, {"confirmation": "revoke"})
    api_key.refresh_from_db()
    assert response.status_code == 302
    assert api_key.is_revoked


def test_api_key_revoke_rejects_get(client, superuser):
    client.force_login(superuser)
    api_key, _ = APIKey.create_for_user(
        user=superuser,
        name="Automation",
        scopes=["fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )

    response = client.get(reverse("community_base_api_key_revoke", args=(api_key.pk,)))

    assert response.status_code == 405
