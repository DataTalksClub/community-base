import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from community_base.api.models import APIKey


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def fixture_key(db):
    user = get_user_model().objects.create_user(username="api-user", is_staff=True)
    _, plaintext = APIKey.create_for_user(
        user=user,
        name="Fixture reader",
        scopes=["fixtures.read"],
        kind=APIKey.Kind.STAFF,
    )
    return plaintext


def test_registered_route_requires_bearer_auth(api_client):
    response = api_client.get("/api/v1/fixtures/ping")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Valid Bearer authentication is required.",
            "details": {},
        }
    }


def test_registered_route_accepts_required_scope(api_client, fixture_key):
    response = api_client.get(
        "/api/v1/fixtures/ping",
        headers={"Authorization": f"Bearer {fixture_key}"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.django_db
def test_registered_route_rejects_wrong_scope(api_client):
    user = get_user_model().objects.create_user(username="wrong-scope", is_staff=True)
    _, plaintext = APIKey.create_for_user(
        user=user,
        name="Wrong scope",
        scopes=["settings.write"],
        kind=APIKey.Kind.STAFF,
    )

    response = api_client.get(
        "/api/v1/fixtures/ping",
        headers={"Authorization": f"Bearer {plaintext}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_authentication_happens_before_method_disclosure(api_client):
    response = api_client.delete("/api/v1/fixtures/ping")

    assert response.status_code == 401


def test_authenticated_wrong_method_uses_error_envelope(api_client, fixture_key):
    response = api_client.delete(
        "/api/v1/fixtures/ping",
        headers={"Authorization": f"Bearer {fixture_key}"},
    )

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
