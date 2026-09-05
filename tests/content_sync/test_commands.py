import json

import pytest
from django.core.management import call_command

from community_base.content_sync.models import ContentSource
from community_base.content_sync.orchestration import UpsertResult
from community_base.content_sync.parsers import SourceItem, register_parser
from testproject.models import FixtureContent

pytestmark = pytest.mark.django_db


class CommandParser:
    def discover(self, checkout, source):
        for path in checkout.files():
            if path.suffix == ".json":
                yield SourceItem(path.stem, path, json.loads(checkout.read_text(path)))

    def upsert(self, item, source, media):
        del media
        obj, created = FixtureContent.objects.update_or_create(
            source=source,
            source_key=item.key,
            defaults={"title": item.data["title"], "fingerprint": item.data["title"]},
        )
        return UpsertResult(obj, "created" if created else "unchanged")

    def soft_delete_missing(self, seen_keys, source):
        return 0


def test_sync_content_from_disk(settings, tmp_path, capsys):
    source = ContentSource.objects.create(
        slug="fixture", repo_name="example/fixture", webhook_secret="secret"
    )
    (tmp_path / "one.json").write_text('{"title": "One"}')
    register_parser("fixture", CommandParser())

    call_command("sync_content", source_slug=source.slug, from_disk=str(tmp_path))

    assert FixtureContent.objects.get().title == "One"
    assert "fixture: success created=1" in capsys.readouterr().out


def test_seed_content_sources_is_idempotent(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "CONTENT_SOURCES": [
            {
                "slug": "docs",
                "repo_name": "example/docs",
                "webhook_secret": "secret",
                "max_files": 50,
            }
        ],
    }

    call_command("seed_content_sources")
    call_command("seed_content_sources")

    source = ContentSource.objects.get()
    assert source.repo_name == "example/docs"
    assert source.max_files == 50
