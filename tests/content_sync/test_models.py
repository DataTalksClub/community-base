from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from community_base.content_sync.models import ContentSource, SyncLog, SyncStatus, WebhookLog

pytestmark = pytest.mark.django_db


def source(**overrides):
    values = {
        "slug": "community",
        "repo_name": "example/community",
        "webhook_secret": "secret",
    }
    values.update(overrides)
    return ContentSource.objects.create(**values)


def test_content_source_requires_webhook_secret_during_validation():
    item = ContentSource(slug="content", repo_name="example/content")

    with pytest.raises(ValidationError, match="webhook secret"):
        item.full_clean()


def test_sync_log_projects_counts_duration_and_commit():
    log = SyncLog.objects.create(
        source=source(),
        status=SyncStatus.SUCCESS,
        items_created=2,
        items_updated=3,
        items_deleted=1,
        commit_sha="a" * 40,
    )
    log.finished_at = log.started_at + timedelta(seconds=4)

    assert log.total_items == 6
    assert log.duration_seconds == 4


def test_webhook_delivery_key_is_unique():
    WebhookLog.objects.create(service="github", deduplication_key="delivery:one")

    with pytest.raises(IntegrityError):
        WebhookLog.objects.create(service="github", deduplication_key="delivery:one")
