import hashlib
import json
from unittest.mock import Mock, patch

import pytest

from community_base.content_sync.models import ContentSource, SyncStatus
from community_base.content_sync.orchestration import (
    UpsertResult,
    release_source_lock,
    sync_content_source,
)
from community_base.content_sync.parsers import SourceItem, register_parser
from testproject.models import FixtureContent

pytestmark = pytest.mark.django_db


class FixtureParser:
    def discover(self, checkout, source):
        for path in checkout.files():
            if path.suffix != ".json":
                continue
            payload = checkout.read_bytes(path)
            data = json.loads(payload)
            yield SourceItem(
                key=path.stem,
                path=path,
                data=data,
            )

    def upsert(self, item, source, media):
        del media
        fingerprint = hashlib.sha256(json.dumps(item.data, sort_keys=True).encode()).hexdigest()
        existing = FixtureContent.objects.filter(source=source, source_key=item.key).first()
        if existing is None:
            obj = FixtureContent.objects.create(
                source=source,
                source_key=item.key,
                title=item.data["title"],
                fingerprint=fingerprint,
            )
            return UpsertResult(obj, "created")
        if existing.fingerprint == fingerprint and existing.is_active:
            return UpsertResult(existing, "unchanged")
        existing.title = item.data["title"]
        existing.fingerprint = fingerprint
        existing.is_active = True
        existing.save(update_fields=("title", "fingerprint", "is_active"))
        return UpsertResult(existing, "updated")

    def soft_delete_missing(self, seen_keys, source):
        return (
            FixtureContent.objects.filter(source=source, is_active=True)
            .exclude(source_key__in=seen_keys)
            .update(is_active=False)
        )


@pytest.fixture
def source():
    return ContentSource.objects.create(
        slug="fixture", repo_name="example/fixture", webhook_secret="secret"
    )


def test_disk_sync_is_idempotent_and_soft_deletes_missing(tmp_path, source):
    register_parser("fixture", FixtureParser())
    first_file = tmp_path / "first.json"
    second_file = tmp_path / "second.json"
    first_file.write_text('{"title": "First"}')
    second_file.write_text('{"title": "Second"}')

    first = sync_content_source(source, repo_dir=tmp_path)
    assert first.status == SyncStatus.SUCCESS
    assert first.items_created == 2
    assert FixtureContent.objects.filter(is_active=True).count() == 2

    second = sync_content_source(source, repo_dir=tmp_path)
    assert second.status == SyncStatus.SUCCESS
    assert second.items_unchanged == 2
    assert second.total_items == 0

    second_file.unlink()
    third = sync_content_source(source, repo_dir=tmp_path)
    assert third.items_deleted == 1
    assert list(FixtureContent.objects.filter(is_active=True).values_list("title", flat=True)) == [
        "First"
    ]


def test_parser_failure_is_observable_as_partial(tmp_path, source):
    class BrokenParser(FixtureParser):
        def discover(self, checkout, source):
            raise ValueError("authored content is malformed")

    register_parser("broken", BrokenParser())

    log = sync_content_source(source, repo_dir=tmp_path)

    assert log.status == SyncStatus.PARTIAL
    assert log.errors == [{"content_type": "broken", "error": "authored content is malformed"}]


def test_active_source_lock_requests_follow_up(source):
    from django.utils import timezone

    source.sync_locked_at = timezone.now()
    source.save(update_fields=("sync_locked_at",))

    log = sync_content_source(source, repo_dir="unused")

    source.refresh_from_db()
    assert log.status == SyncStatus.SKIPPED
    assert source.sync_requested is True


@pytest.mark.django_db(transaction=True)
def test_lock_release_dispatches_requested_follow_up(source):
    source.sync_requested = True
    source.save(update_fields=("sync_requested",))
    backend = Mock()

    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        release_source_lock(source, follow_up_key="log-id")

    source.refresh_from_db()
    assert source.sync_locked_at is None
    assert source.sync_requested is False
    backend.submit.assert_called_once()
