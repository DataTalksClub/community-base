import json

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command

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
        obj = FixtureContent.objects.filter(source=source, source_key=item.key).first()
        if obj is None:
            obj = FixtureContent.objects.create(
                source=source,
                source_key=item.key,
                title=item.data["title"],
                fingerprint=item.data["title"],
            )
            return UpsertResult(obj, "created")
        if obj.fingerprint == item.data["title"] and obj.is_active:
            return UpsertResult(obj, "unchanged")
        obj.title = item.data["title"]
        obj.fingerprint = item.data["title"]
        obj.is_active = True
        obj.save(update_fields=("title", "fingerprint", "is_active"))
        return UpsertResult(obj, "updated")

    def soft_delete_missing(self, seen_keys, source):
        return (
            FixtureContent.objects.filter(source=source, is_active=True)
            .exclude(source_key__in=seen_keys)
            .update(is_active=False)
        )


def test_sync_content_from_disk(settings, tmp_path, capsys):
    source = ContentSource.objects.create(
        slug="fixture", repo_name="example/fixture", webhook_secret="secret"
    )
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    first.write_text('{"title": "One"}')
    second.write_text('{"title": "Two"}')
    register_parser("fixture", CommandParser())

    call_command("sync_content", source_slug=source.slug, from_disk=str(tmp_path))
    first_output = capsys.readouterr().out
    call_command("sync_content", source_slug=source.slug, from_disk=str(tmp_path))
    second_output = capsys.readouterr().out
    second.unlink()
    call_command("sync_content", source_slug=source.slug, from_disk=str(tmp_path))
    third_output = capsys.readouterr().out

    assert FixtureContent.objects.get(source_key="one").title == "One"
    assert "created=2" in first_output
    assert "created=0 updated=0 unchanged=2 deleted=0" in second_output
    assert "created=0 updated=0 unchanged=1 deleted=1" in third_output
    assert FixtureContent.objects.get(source_key="two").is_active is False


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


def test_seed_validation_rolls_back_all_sources(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "CONTENT_SOURCES": [
            {"slug": "valid", "repo_name": "example/valid", "webhook_secret": "secret"},
            {"slug": "invalid", "repo_name": "example/invalid", "webhook_secret": ""},
        ],
    }

    with pytest.raises(ValidationError, match="webhook secret"):
        call_command("seed_content_sources")

    assert not ContentSource.objects.exists()


def test_force_allows_disabled_source_from_disk(tmp_path, capsys):
    source = ContentSource.objects.create(
        slug="disabled",
        repo_name="example/disabled",
        webhook_secret="secret",
        is_enabled=False,
    )
    (tmp_path / "one.json").write_text('{"title": "One"}')
    register_parser("fixture", CommandParser())

    with pytest.raises(CommandError, match="No matching enabled"):
        call_command("sync_content", source_slug=source.slug, from_disk=str(tmp_path))
    call_command(
        "sync_content",
        source_slug=source.slug,
        from_disk=str(tmp_path),
        force=True,
    )

    assert FixtureContent.objects.get().title == "One"
    assert "disabled: success created=1" in capsys.readouterr().out
