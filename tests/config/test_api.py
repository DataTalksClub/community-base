import pytest
from django.contrib.auth import get_user_model

from community_base.api.models import APIKey
from community_base.config import service
from tests.config.test_service import SECRET_KEY, STRING_KEY


@pytest.fixture
def scoped_keys(db):
    user = get_user_model().objects.create_user(username="config-api", is_staff=True)
    _, read_key = APIKey.create_for_user(
        user=user,
        name="Config reader",
        scopes=["settings.read"],
        kind=APIKey.Kind.STAFF,
    )
    _, write_key = APIKey.create_for_user(
        user=user,
        name="Config writer",
        scopes=["settings.write"],
        kind=APIKey.Kind.STAFF,
    )
    return read_key, write_key


def _bearer(plaintext):
    return {"Authorization": f"Bearer {plaintext}"}


@pytest.mark.django_db(transaction=True)
def test_settings_api_enforces_read_and_write_scopes(client, scoped_keys):
    read_key, write_key = scoped_keys

    denied_write = client.put(
        f"/api/v1/settings/{STRING_KEY}",
        {"value": "new"},
        content_type="application/json",
        headers=_bearer(read_key),
    )
    denied_read = client.get("/api/v1/settings", headers=_bearer(write_key))
    allowed_write = client.put(
        f"/api/v1/settings/{STRING_KEY}",
        {"value": "new"},
        content_type="application/json",
        headers=_bearer(write_key),
    )
    allowed_read = client.get(f"/api/v1/settings/{STRING_KEY}", headers=_bearer(read_key))

    assert denied_write.status_code == 403
    assert denied_read.status_code == 403
    assert allowed_write.status_code == 200
    assert allowed_read.status_code == 200
    assert allowed_read.json()["value"] == "new"
    assert allowed_read.json()["source"] == "db"


@pytest.mark.django_db(transaction=True)
def test_settings_api_masks_secrets_in_list_detail_and_export(client, scoped_keys):
    read_key, _ = scoped_keys
    service.set(SECRET_KEY, "api-secret-value", "test:actor")

    listed = client.get("/api/v1/settings?limit=100", headers=_bearer(read_key))
    detailed = client.get(f"/api/v1/settings/{SECRET_KEY}", headers=_bearer(read_key))
    exported = client.get("/api/v1/settings/export", headers=_bearer(read_key))

    listed_secret = next(item for item in listed.json()["settings"] if item["key"] == SECRET_KEY)
    assert listed_secret["value"] == "[REDACTED]"
    assert detailed.json()["value"] == "[REDACTED]"
    assert exported.json()["settings"][SECRET_KEY] == "[REDACTED]"
    assert b"api-secret-value" not in listed.content + detailed.content + exported.content


@pytest.mark.django_db(transaction=True)
def test_settings_import_updates_known_values_and_skips_redacted_secrets(client, scoped_keys):
    _, write_key = scoped_keys

    response = client.post(
        "/api/v1/settings/import",
        {"settings": {STRING_KEY: "imported", SECRET_KEY: "[REDACTED]"}},
        content_type="application/json",
        headers=_bearer(write_key),
    )

    assert response.status_code == 200
    assert response.json() == {"updated": [STRING_KEY]}
    assert service.get(STRING_KEY) == "imported"


def test_settings_api_returns_standard_not_found_envelope(client, scoped_keys):
    read_key, _ = scoped_keys

    response = client.get("/api/v1/settings/UNKNOWN_KEY", headers=_bearer(read_key))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "setting_not_found"
