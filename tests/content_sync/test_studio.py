from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.content_sync.models import ContentSource, SyncLog, SyncStatus
from community_base.jobs.models import JobIntent


@pytest.fixture
def staff_client(client, db):
    user = get_user_model().objects.create_user(username="operator", is_staff=True)
    client.force_login(user)
    return client


@pytest.fixture
def source(db):
    return ContentSource.objects.create(
        slug="source", repo_name="owner/repo", webhook_secret="existing-secret"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name",
    [
        "community_base_content_sources",
        "community_base_content_sync_history",
        "community_base_content_sync_worker",
    ],
)
def test_staff_surfaces_render(staff_client, name):
    assert staff_client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
def test_non_staff_cannot_access_sources(client):
    user = get_user_model().objects.create_user(username="member")
    client.force_login(user)

    response = client.get(reverse("community_base_content_sources"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_edit_preserves_blank_secret(staff_client, source):
    response = staff_client.post(
        reverse("community_base_content_source_edit", args=[source.pk]),
        {
            "repo_name": "owner/renamed",
            "is_enabled": "on",
            "max_files": 25,
            "webhook_secret": "",
        },
    )

    assert response.status_code == 302
    source.refresh_from_db()
    assert source.repo_name == "owner/renamed"
    assert source.webhook_secret == "existing-secret"


@pytest.mark.django_db(transaction=True)
def test_sync_action_queues_job_and_redirects_to_history(staff_client, source):
    backend = Mock()
    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        response = staff_client.post(
            reverse("community_base_content_source_sync", args=[source.pk])
        )

    assert response.status_code == 302
    assert response.url == reverse("community_base_content_sync_history")
    assert JobIntent.objects.get().payload["source_id"] == str(source.pk)
    source.refresh_from_db()
    assert source.last_sync_status == SyncStatus.QUEUED


@pytest.mark.django_db
def test_history_shows_counts_without_raw_parser_errors(staff_client, source):
    SyncLog.objects.create(
        source=source,
        status=SyncStatus.PARTIAL,
        items_created=2,
        errors=[{"error": "credential-canary"}],
    )

    response = staff_client.get(reverse("community_base_content_sync_history"))

    assert response.status_code == 200
    assert b"Created 2" in response.content
    assert b"credential-canary" not in response.content
