from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model

from community_base.api.models import APIKey
from community_base.content_sync.models import ContentSource, SyncStatus
from community_base.jobs.models import JobIntent


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture
def source(db):
    return ContentSource.objects.create(
        slug="source", repo_name="owner/repo", webhook_secret="webhook-secret"
    )


@pytest.fixture
def scoped_keys(db):
    user = get_user_model().objects.create_user(email="content-api@example.com", is_staff=True)
    _, read_key = APIKey.create_for_user(
        user=user,
        name="Content reader",
        scopes=["content_sync.read"],
        kind=APIKey.Kind.STAFF,
    )
    _, write_key = APIKey.create_for_user(
        user=user,
        name="Content writer",
        scopes=["content_sync.write"],
        kind=APIKey.Kind.STAFF,
    )
    return read_key, write_key


@pytest.mark.django_db(transaction=True)
def test_sources_api_enforces_scopes_and_never_exposes_secret(client, source, scoped_keys):
    read_key, write_key = scoped_keys

    denied = client.get("/api/v1/content-sources", headers=bearer(write_key))
    allowed = client.get("/api/v1/content-sources", headers=bearer(read_key))

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["sources"][0]["repository"] == "owner/repo"
    assert b"webhook-secret" not in allowed.content


@pytest.mark.django_db(transaction=True)
def test_single_source_trigger_creates_batch_job(client, source, scoped_keys):
    _, write_key = scoped_keys
    backend = Mock()
    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        response = client.post(
            f"/api/v1/content-sources/{source.pk}/sync",
            data={},
            content_type="application/json",
            headers=bearer(write_key),
        )

    assert response.status_code == 202
    body = response.json()
    assert len(body["jobs"]) == 1
    intent = JobIntent.objects.get()
    assert intent.payload["source_id"] == str(source.pk)
    assert intent.payload["batch_id"] == body["batch_id"]
    source.refresh_from_db()
    assert source.last_sync_status == SyncStatus.QUEUED


@pytest.mark.django_db(transaction=True)
def test_bulk_trigger_queues_one_job_per_enabled_source(client, source, scoped_keys):
    ContentSource.objects.create(slug="second", repo_name="owner/second", webhook_secret="secret")
    ContentSource.objects.create(
        slug="disabled", repo_name="owner/disabled", webhook_secret="secret", is_enabled=False
    )
    _, write_key = scoped_keys
    backend = Mock()
    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        response = client.post(
            "/api/v1/content-sources/sync",
            data={},
            content_type="application/json",
            headers=bearer(write_key),
        )

    assert response.status_code == 202
    assert len(response.json()["jobs"]) == 2
    assert JobIntent.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_disabled_source_requires_explicit_force(client, source, scoped_keys):
    source.is_enabled = False
    source.save(update_fields=("is_enabled",))
    _, write_key = scoped_keys

    denied = client.post(
        f"/api/v1/content-sources/{source.pk}/sync",
        data={},
        content_type="application/json",
        headers=bearer(write_key),
    )
    backend = Mock()
    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        allowed = client.post(
            f"/api/v1/content-sources/{source.pk}/sync",
            data={"force": True},
            content_type="application/json",
            headers=bearer(write_key),
        )

    assert denied.status_code == 409
    assert allowed.status_code == 202
    assert JobIntent.objects.get().payload["force"] is True
